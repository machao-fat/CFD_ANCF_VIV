"""Production ANCF wrapper using the existing persistent runner.

The wrapper owns the multi-slice protocol boundary and H/H^T calls.  It does
not reimplement ANCF matrices or element mechanics.  A ``state_provider`` is
accepted because the frozen stage-three MATLAB worker exposes motion and
energy, but not q/qdot/qddot as JSON fields; production integration must
provide that state view before a real closed-loop claim is made.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..multi_slice_mapping.mapping import (
    LoadRecord,
    MotionRecord,
    SliceManifest,
    build_H_for_manifest,
    map_integrated_slice_forces,
    motion_from_ancf_state,
)


class ANCFAdapterError(RuntimeError):
    pass


StateProvider = Callable[[], Mapping[str, Sequence[float]]]


def _finite_vector(values: Sequence[Any], name: str) -> list[float]:
    result = []
    for index, value in enumerate(values):
        try:
            item = float(value)
        except (TypeError, ValueError) as exc:
            raise ANCFAdapterError(f"{name}[{index}] is not numeric") from exc
        if not math.isfinite(item):
            raise ANCFAdapterError(f"{name}[{index}] is NaN/Inf")
        result.append(item)
    return result


class ProductionANCFAdapter:
    """Adapt ``PersistentMatlabRunner`` to the 0.2.1 staged interface."""

    def __init__(
        self,
        *,
        runner: object,
        manifest: SliceManifest,
        mesh_nodes: Sequence[float],
        state_provider: StateProvider | None = None,
        reference_positions_m: Mapping[int, Sequence[float]] | None = None,
        runner_step_offset: int = 0,
        runner_time_offset_s: float = 0.0,
    ) -> None:
        self.runner = runner
        self.manifest = manifest
        self.manifest.validate()
        self.mesh_nodes = tuple(float(value) for value in mesh_nodes)
        self.H_by_slice_id = build_H_for_manifest(self.manifest, self.mesh_nodes)
        self.state_provider = state_provider
        self.reference_positions_m = dict(reference_positions_m or {
            item.slice_id: (0.0, 0.0, item.s_ref_m) for item in self.manifest.slices
        })
        self.runner_step_offset = int(runner_step_offset)
        self.runner_time_offset_s = float(runner_time_offset_s)
        self._pending_token: str | None = None
        self._pending_state: dict[str, list[float]] | None = None
        self._snapshot_path: Path | None = None
        self._committed_token: str | None = None
        self._last_generalized_force: list[float] = []
        self.case_id = manifest.case_id

    def set_case_id(self, case_id: str) -> None:
        if case_id != self.manifest.case_id:
            raise ANCFAdapterError("case_id cannot differ from formal manifest")
        self.case_id = case_id

    def h_by_slice_id(self):
        return self.H_by_slice_id

    def _read_state(self) -> dict[str, list[float]]:
        if self.state_provider is None:
            raise ANCFAdapterError("production runner state_provider must expose q/qdot/qddot")
        raw = self.state_provider()
        if not isinstance(raw, Mapping):
            raise ANCFAdapterError("state_provider must return a mapping")
        result = {}
        for key in ("q", "qdot", "qddot"):
            if key not in raw:
                raise ANCFAdapterError(f"state_provider missing {key}")
            result[key] = _finite_vector(raw[key], key)
        return result

    def _save_runner_snapshot(self) -> None:
        saver = getattr(self.runner, "save_checkpoint", None)
        if saver is None:
            return
        if self._snapshot_path is None:
            handle = tempfile.NamedTemporaryFile(prefix="ancf_pre_correction_", suffix=".mat", delete=False)
            handle.close()
            self._snapshot_path = Path(handle.name)
        saver(self._snapshot_path)

    def _restore_runner_snapshot(self) -> None:
        if self._snapshot_path is None:
            return
        loader = getattr(self.runner, "load_checkpoint", None)
        if loader is None:
            raise ANCFAdapterError("runner cannot restore staged correction")
        loader(self._snapshot_path)

    def predict_all(self, step: int, time_s: float, previous_slice_forces: Sequence[Sequence[float]]) -> list[MotionRecord]:
        load = [[float(value) for value in row] for row in previous_slice_forces]
        if len(load) != len(self.manifest.slices) or any(len(row) != 3 for row in load):
            raise ANCFAdapterError("previous slice force matrix is not N x 3")
        predictor = getattr(self.runner, "predict", None)
        if predictor is None:
            raise ANCFAdapterError("runner does not expose predict")
        runner_step = step + self.runner_step_offset
        runner_time = time_s + self.runner_time_offset_s
        response, motion_rows = predictor(runner_step, runner_time, load)
        # The stage-three persistent worker reports its committed state step
        # in the predictor response; prediction itself is intentionally held
        # in pending_prediction, so that response is one step behind.
        if isinstance(response, Mapping) and response.get("step") not in (None, runner_step, runner_step - 1):
            raise ANCFAdapterError("runner predict returned wrong step")
        try:
            state = self._read_state()
        except ANCFAdapterError:
            state = None
        if state is not None:
            return [motion_from_ancf_state(
                self.manifest, item.slice_id, self.H_by_slice_id[item.slice_id],
                state["q"], state["qdot"], state["qddot"], step=step,
                time_s=time_s, reference_position_m=self.reference_positions_m[item.slice_id],
            ) for item in self.manifest.slices]
        records = []
        for row in motion_rows:
            record = row if isinstance(row, MotionRecord) else MotionRecord.from_mapping(row)
            records.append(record)
        if len(records) != len(self.manifest.slices):
            raise ANCFAdapterError("runner did not provide complete 0.2.1 motion or q state")
        return records

    def accept_generalized_force(self, value: Sequence[float]) -> None:
        self._last_generalized_force = _finite_vector(value, "generalized_force")

    def correct_all(self, step: int, time_s: float, integrated_slice_forces: Sequence[Mapping[str, object] | LoadRecord]) -> Mapping[str, object]:
        records = [item if isinstance(item, LoadRecord) else LoadRecord.from_mapping(item, self.manifest.R_GL) for item in integrated_slice_forces]
        by_id = {item.slice_id: item for item in records}
        mapping = map_integrated_slice_forces(self.manifest, self.H_by_slice_id, by_id)
        self.accept_generalized_force(mapping.generalized_force)
        self._save_runner_snapshot()
        corrector = getattr(self.runner, "correct", None)
        if corrector is None:
            raise ANCFAdapterError("runner does not expose correct")
        runner_step = step + self.runner_step_offset
        runner_time = time_s + self.runner_time_offset_s
        response, _ = corrector(runner_step, runner_time, [list(by_id[item.slice_id].force_N) for item in self.manifest.slices])
        self._pending_state = self._read_state()
        self._pending_token = hashlib.sha256(f"{self.case_id}:{step}:{time_s:.17g}".encode("utf-8")).hexdigest()
        audit = response.get("audit", {}) if isinstance(response, Mapping) else {}
        return {
            "step": step, "time_s": time_s,
            "generalized_force": list(mapping.generalized_force),
            "checkpoint_token": self._pending_token,
            "audit": audit,
        }

    def export_staged_checkpoint(self) -> Mapping[str, object]:
        if self._pending_state is None or self._pending_token is None:
            raise ANCFAdapterError("no staged ANCF correction")
        return {**copy.deepcopy(self._pending_state), "checkpoint_token": self._pending_token}

    def export_runner_checkpoint(self, path: str | Path) -> None:
        """Export the native runner snapshot alongside the formal JSON state.

        The formal checkpoint remains the 0.2.1 JSON/q-state contract.  The
        optional native snapshot is only a production-runner restoration aid;
        it avoids reconstructing MATLAB handle state from arrays in a restart.
        """

        saver = getattr(self.runner, "save_checkpoint", None)
        if saver is None:
            raise ANCFAdapterError("runner cannot export a native checkpoint")
        saver(path)

    def finalize_committed(self, checkpoint_token: object | None = None) -> None:
        token = str(checkpoint_token) if checkpoint_token is not None else self._pending_token
        if token is not None and self._pending_token not in (None, token):
            raise ANCFAdapterError("checkpoint token mismatch")
        # runner.correct has already advanced the runner after the snapshot;
        # finalization only makes that state the acknowledged committed state.
        self._committed_token = token
        self._pending_token = None
        self._pending_state = None

    def discard_staged(self) -> None:
        if self._pending_token is None:
            return
        self._restore_runner_snapshot()
        self._pending_token = None
        self._pending_state = None

    def load_checkpoint(self, path: str | Path) -> None:
        loader = getattr(self.runner, "load_checkpoint", None)
        if loader is None:
            raise ANCFAdapterError("runner does not expose load_checkpoint")
        checkpoint_path = Path(path)
        native_path = checkpoint_path.with_suffix(".mat") if checkpoint_path.suffix == ".json" else checkpoint_path
        loader(native_path if native_path.is_file() else checkpoint_path)
        if checkpoint_path.suffix == ".json" and checkpoint_path.is_file():
            try:
                payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ANCFAdapterError("formal ANCF checkpoint JSON is invalid") from exc
            state = self._read_state()
            for key in ("q", "qdot", "qddot"):
                expected = _finite_vector(payload.get(key, []), f"checkpoint.{key}")
                actual = state[key]
                if len(expected) != len(actual) or any(abs(a - b) > 1.0e-12 * max(1.0, abs(a), abs(b)) for a, b in zip(expected, actual)):
                    raise ANCFAdapterError(f"native runner state disagrees with formal checkpoint {key}")
        self._pending_token = None
        self._pending_state = None
