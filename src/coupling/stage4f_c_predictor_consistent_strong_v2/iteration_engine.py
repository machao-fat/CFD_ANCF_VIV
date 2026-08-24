"""Predictor-consistent candidate engine.

The v1 candidate transaction deliberately stages the structural corrector so
that rejected fixed-point iterates can be rolled back.  That is useful for
convergence diagnostics, but it must not make the corrector state appear in a
checkpoint after CFD consumed predictor motion.  This sidecar freezes the
predictor state immediately after ``predict_all`` and permits promotion only
from that frozen native/JSON pair.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..multi_slice_mapping.mapping import LoadRecord, atomic_write_json, motion_from_ancf_state, sha256_file
from ..stage4f_c_strong_coupling_preflight_v1 import iteration_engine as v1


class PredictorSnapshotError(RuntimeError):
    """The state released to CFD cannot be proven to be the checkpoint state."""


def _canonical_sha256(value: Mapping[str, Any] | Sequence[Any]) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite_state(raw: Mapping[str, Any]) -> dict[str, list[float]]:
    state: dict[str, list[float]] = {}
    for key in ("q", "qdot", "qddot"):
        values = raw.get(key)
        if not isinstance(values, (list, tuple)) or not values:
            raise PredictorSnapshotError(f"predictor state is missing nonempty {key}")
        row = [float(value) for value in values]
        if not all(math.isfinite(value) for value in row):
            raise PredictorSnapshotError(f"predictor state {key} contains NaN/Inf")
        state[key] = row
    return state


class _PredictorCheckpointFacade:
    """Expose only a frozen predictor snapshot to AtomicCheckpointManager."""

    def __init__(self, snapshot: Mapping[str, Any]) -> None:
        self.snapshot = dict(snapshot)

    def export_staged_checkpoint(self) -> Mapping[str, object]:
        state = _finite_state(self.snapshot["state"])
        return {**state, "checkpoint_token": str(self.snapshot["state_sha256"])}

    def export_runner_checkpoint(self, destination: str | Path) -> None:
        source = Path(str(self.snapshot["native_path"]))
        if not source.is_file():
            raise PredictorSnapshotError("frozen predictor native checkpoint is missing")
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if sha256_file(target) != self.snapshot["native_sha256"]:
            raise PredictorSnapshotError("copied predictor native checkpoint hash mismatch")

    def finalize_committed(self, _checkpoint_token: object | None = None) -> None:
        # The runner was restored to this predictor before prepare().
        return None


class CandidateIterationEngine(v1.CandidateIterationEngine):
    """v1 candidate lifecycle with predictor-only promotion semantics."""

    def __init__(self, plan: Mapping[str, Any]):
        super().__init__(plan)
        self._predictor_snapshot: dict[str, Any] | None = None
        self._predictor_restored_for_promotion = False

    def _state_view(self) -> Mapping[str, Any]:
        provider = getattr(self.adapter, "state_provider", None)
        if callable(provider):
            return provider()
        view = getattr(self.runner, "state_view", None)
        if callable(view):
            return view()
        reader = getattr(self.adapter, "_read_state", None)
        if callable(reader):
            return reader()
        raise PredictorSnapshotError("ANCF predictor JSON state view is unavailable")

    def _motion_rows_from_state(self, state: Mapping[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        references = getattr(self.adapter, "reference_positions_m", {})
        h_by_slice = getattr(self.adapter, "H_by_slice_id", None)
        if not isinstance(h_by_slice, Mapping):
            raise PredictorSnapshotError("ANCF predictor H mapping is unavailable")
        for spec in self.manifest.slices:
            row = motion_from_ancf_state(
                self.manifest, spec.slice_id, h_by_slice[spec.slice_id],
                state["q"], state["qdot"], state["qddot"], step=self.physical_step,
                time_s=self.target_time_s, reference_position_m=references.get(spec.slice_id),
            )
            rows.append(row.to_dict())
        return rows

    def _capture_predictor_snapshot(self, predicted: Sequence[Any]) -> None:
        if self._predictor_snapshot is not None:
            raise PredictorSnapshotError("predictor snapshot was captured more than once")
        state = _finite_state(self._state_view())
        actual_rows = []
        for row in predicted:
            serial = row.to_dict() if hasattr(row, "to_dict") else dict(row)
            actual_rows.append(dict(serial))
        expected_rows = self._motion_rows_from_state(state)
        if actual_rows != expected_rows:
            raise PredictorSnapshotError("published CFD motion is not generated by the frozen predictor q/qdot/qddot")
        native_path = self.root / "predictor_snapshot" / "ancf_predictor.mat"
        native_path.parent.mkdir(parents=True, exist_ok=True)
        saver = getattr(self.runner, "save_checkpoint", None)
        if not callable(saver):
            raise PredictorSnapshotError("ANCF runner cannot save predictor native checkpoint")
        saver(native_path)
        if not native_path.is_file() or native_path.stat().st_size == 0:
            raise PredictorSnapshotError("ANCF runner did not create predictor native checkpoint")
        json_path = native_path.with_suffix(".json")
        state_sha256 = _canonical_sha256(state)
        motion_sha256 = _canonical_sha256(actual_rows)
        payload = {
            "schema": "stage4f-c-predictor-consistent-strong-v2-predictor-snapshot-1.0.0",
            "step": self.physical_step,
            "time_s": self.target_time_s,
            "state": state,
            "state_sha256": state_sha256,
            "published_motion": actual_rows,
            "published_motion_sha256": motion_sha256,
            "native_path": str(native_path),
            "native_sha256": sha256_file(native_path),
        }
        atomic_write_json(json_path, payload)
        audit = {
            "schema": "stage4f-c-predictor-consistent-strong-v2-state-coherence-1.0.0",
            "status": "passed",
            "mixed_predictor_cfd_corrector_forbidden": True,
            "cfd_motion_state_role": "predictor_snapshot",
            "checkpoint_state_role": "predictor_snapshot",
            "corrector_state_role": "diagnostic_only_never_promoted",
            "predictor_snapshot_json": str(json_path),
            "predictor_snapshot_json_sha256": sha256_file(json_path),
            "predictor_native_sha256": payload["native_sha256"],
            "predictor_state_sha256": state_sha256,
            "published_motion_sha256": motion_sha256,
            "coherence_sha256": _canonical_sha256({"state": state_sha256, "motion": motion_sha256, "native": payload["native_sha256"]}),
        }
        audit_path = self.root / "state_coherence_audit.json"
        atomic_write_json(audit_path, audit)
        self._predictor_snapshot = {**payload, "json_path": str(json_path), "audit": audit, "audit_path": str(audit_path)}

    def _restore_predictor_for_promotion(self) -> None:
        snapshot = self._predictor_snapshot
        if snapshot is None:
            raise PredictorSnapshotError("promotion requires a predictor native/JSON snapshot")
        if self._predictor_restored_for_promotion:
            return
        self.adapter.discard_staged()
        restored = _finite_state(self._state_view())
        expected = _finite_state(snapshot["state"])
        if restored != expected:
            raise PredictorSnapshotError("restored ANCF state does not equal the CFD predictor snapshot")
        audit = dict(snapshot["audit"])
        audit["predictor_restored_before_promotion"] = True
        audit["restored_state_sha256"] = _canonical_sha256(restored)
        audit["status"] = "passed" if audit["restored_state_sha256"] == snapshot["state_sha256"] else "failed"
        if audit["status"] != "passed":
            raise PredictorSnapshotError("restored predictor state hash mismatch")
        atomic_write_json(Path(str(snapshot["audit_path"])), audit)
        snapshot["audit"] = audit
        self._predictor_restored_for_promotion = True

    def run_trial(self, *, previous_slice_forces_N: list[list[float]] | tuple[tuple[float, ...], ...] | None = None) -> Mapping[str, Any]:
        """Run v1 trial while freezing the predictor before CFD publication."""
        original_predict = self.adapter.predict_all

        def capture_predictor(step: int, time_s: float, forces: Sequence[Sequence[float]]):
            predicted = list(original_predict(step, time_s, forces))
            self._capture_predictor_snapshot(predicted)
            return predicted

        self.adapter.predict_all = capture_predictor
        try:
            result = dict(super().run_trial(previous_slice_forces_N=previous_slice_forces_N))
        finally:
            self.adapter.predict_all = original_predict
        if self._predictor_snapshot is None:
            raise PredictorSnapshotError("candidate trial completed without a predictor snapshot")
        corrector_geometry = result.pop("geometry_audit", [])
        result["state_role"] = "predictor_snapshot_for_cfd_and_promotion"
        result["geometry_state_role"] = "corrector_diagnostic_only"
        result["corrector_diagnostics"] = {
            "state_role": "corrector_diagnostic_only_never_promoted",
            "geometry_audit": corrector_geometry,
            "position_difference_over_D": result["position_difference_over_D"],
            "velocity_difference_over_U": result["velocity_difference_over_U"],
        }
        result["predictor_snapshot"] = {
            key: self._predictor_snapshot[key]
            for key in ("json_path", "native_path", "state_sha256", "native_sha256", "published_motion_sha256")
        }
        result["state_coherence_audit"] = dict(self._predictor_snapshot["audit"])
        result["mixed_predictor_cfd_corrector_forbidden"] = True
        self._trial = result
        atomic_write_json(self.root / "trial_evidence.json", self._trial)
        return dict(self._trial)

    def promote(self) -> Path:
        """Commit only the predictor state that generated the CFD motion."""
        if self._trial is None or self._trial_discarded:
            raise RuntimeError("only an undiscarded staged candidate can be promoted")
        if self._promoted_checkpoint is not None:
            raise RuntimeError("candidate has already been promoted")
        if self.scheduler.state != v1.SchedulerState.STRUCTURE_CORRECTED:
            raise RuntimeError("candidate is not at staged-correction state")
        self._restore_predictor_for_promotion()
        snapshot = self._predictor_snapshot
        assert snapshot is not None
        observed = [[float(row[0]), float(row[1]), float(row[2])] for row in self._trial["observed_slice_forces_N"]]
        facade = _PredictorCheckpointFacade(snapshot)
        prepared = self.scheduler.checkpoint_manager.prepare(
            step=self.physical_step, time_s=self.target_time_s, coupling_iteration=0,
            slice_processes=self.scheduler.processes, structure=facade,
            previous_slice_forces_N=observed,
            previous_generalized_force=[float(value) for value in self._trial["generalized_force_N"]],
        )
        self.scheduler._active_checkpoint = prepared
        self.scheduler._transition(v1.SchedulerState.CHECKPOINT_PREPARED, step=self.physical_step, time_s=self.target_time_s)
        checkpoint = self.scheduler.checkpoint_manager.commit(prepared)
        facade.finalize_committed(prepared.staged_token)
        self.scheduler._transition(v1.SchedulerState.COMMITTED, step=self.physical_step, time_s=self.target_time_s)
        self.scheduler.last_committed_step = self.physical_step
        self.scheduler.last_committed_time_s = self.target_time_s
        self.scheduler.previous_slice_forces_N = observed
        self.scheduler.previous_generalized_force = [float(value) for value in self._trial["generalized_force_N"]]
        self.scheduler._active_correction = None
        self.scheduler._active_checkpoint = None
        self._promoted_checkpoint = Path(checkpoint)
        self._trial.update({
            "formal_checkpoint_created": True,
            "checkpoint": str(checkpoint),
            "checkpoint_sha256": sha256_file(checkpoint),
            "staged_correction_discarded": True,
            "observed_force_persisted": observed == self._trial["observed_slice_forces_N"],
            "checkpoint_state_role": "predictor_snapshot",
            "mixed_predictor_cfd_corrector_forbidden": True,
        })
        atomic_write_json(self.root / "trial_evidence.json", self._trial)
        return self._promoted_checkpoint


def candidate_factory(plan: Mapping[str, Any]):
    engine = CandidateIterationEngine(plan)
    return engine, engine.shutdown
