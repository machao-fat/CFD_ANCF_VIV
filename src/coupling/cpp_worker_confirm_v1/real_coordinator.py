from __future__ import annotations

import os
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from coupling.performance_optimization_v2.coordinator import CoordinatorError, SliceResult, StepIdentity
from coupling.multi_slice_mapping.mapping import MotionRecord, SliceManifest, motion_from_ancf_state

from .contracts import CppConfirmContract, ContractError, REAL_AUTHORIZATION_TOKEN
from .barrier import Stage100SliceBarrier


class ExternalProcessSlice(Protocol):
    slice_id: int
    start_count: int
    owned_residual: int

    def start(self) -> None: ...
    def advance(self, identity: StepIdentity, motion_payload: Any = None) -> SliceResult: ...
    def stop(self) -> None: ...


class LaunchGuard:
    """The only boundary allowed to unlock OpenFOAM/WSL/CFD launch."""

    @staticmethod
    def require(contract: CppConfirmContract, authorization: str | None) -> None:
        if not contract.allow_real_external_processes:
            raise ContractError("real external process launch is disabled by contract")
        if authorization != REAL_AUTHORIZATION_TOKEN or contract.authorization != REAL_AUTHORIZATION_TOKEN:
            raise ContractError("explicit real CFD authorization is missing")


@dataclass
class CppConfirmRun:
    contract: CppConfirmContract
    worker: Any
    slice_factory: Callable[[int, Path], ExternalProcessSlice]
    authorization: str | None = None

    def __post_init__(self) -> None:
        self._barrier: Stage100SliceBarrier | None = None
        self._started = False
        self._terminal = False
        self._records: list[dict[str, Any]] = []
        self._next_global_step = self.contract.source_global_step + 1
        self._preflighted = False

    def preflight(self, project_root: Path) -> None:
        self.contract.validate(project_root)
        if self.contract.allow_real_external_processes:
            LaunchGuard.require(self.contract, self.authorization)
        if self.contract.stage_id.startswith("stage96") or self.contract.run_id.startswith(("confirm_", "attempt")):
            raise ContractError("new C++ confirm identity is required")
        if self.contract.runtime.exists() and any(self.contract.runtime.iterdir()):
            raise ContractError("runtime must be fresh and empty")
        if self.contract.results.exists() and any(self.contract.results.iterdir()):
            raise ContractError("results must be fresh and empty")
        self._preflighted = True

    def start(self) -> None:
        if self._started or self._terminal:
            raise CoordinatorError("C++ confirm is already started or terminal")
        LaunchGuard.require(self.contract, self.authorization)
        if not self._preflighted:
            raise CoordinatorError("C++ confirm requires a successful preflight before start")
        # This method never falls back to MATLAB and never silently launches
        # external processes. Real slice factories are injected only after
        # preflight has validated the explicit authorization token.
        self.contract.runtime.mkdir(parents=True, exist_ok=False)
        self.contract.results.mkdir(parents=True, exist_ok=False)
        self.worker.start()
        self._barrier = Stage100SliceBarrier(
            run_id=self.contract.run_id, case_id=self.contract.case_id,
            source_global_step=self.contract.source_global_step, source_time_s=self.contract.source_time_s,
            source_tick=self.contract.source_tick, dt_s=self.contract.global_dt_s,
            runtime=self.contract.runtime, parallel=True, engine_factory=self.slice_factory,
        )
        try:
            self._barrier.start()
        except Exception:
            self.worker.stop()
            self._terminal = True
            raise
        self._started = True

    def commit_step(self, *, global_step: int, time_s: float,
                    worker_step: Callable[[int, float], Mapping[str, Any]],
                    motion_by_slice: Mapping[int, Any] | None = None) -> dict[str, Any]:
        if not self._started or self._terminal or self._barrier is None:
            raise CoordinatorError("C++ confirm is unavailable")
        if len(self._records) >= self.contract.steps:
            self._terminal = True
            raise CoordinatorError("step scope exceeded")
        try:
            expected_time = self.contract.source_time_s + (global_step - self.contract.source_global_step) * self.contract.global_dt_s
            if global_step != self._next_global_step or abs(float(time_s) - expected_time) > 1e-12:
                raise CoordinatorError("C++ confirm step/time is outside the exact bounded sequence")
            worker_response = dict(worker_step(global_step, time_s))
            required = ("global_step", "case_local_bridge_step", "time_s", "integer_tick",
                        "run_id", "case_id", "request_id", "transaction_id", "return_code",
                        "payload_hash", "finite_value_audit", "sequence", "ack")
            missing = [key for key in required if key not in worker_response]
            if missing:
                raise CoordinatorError("C++ worker response missing: " + ",".join(missing))
            expected_bridge = global_step - self.contract.source_global_step
            expected_tick = self.contract.source_tick + expected_bridge * round(self.contract.global_dt_s * 1e9)
            if (worker_response["global_step"] != global_step or
                    worker_response["case_local_bridge_step"] != expected_bridge or
                    worker_response["run_id"] != self.contract.run_id or
                    worker_response["case_id"] != self.contract.case_id or
                    worker_response["integer_tick"] != expected_tick or
                    abs(float(worker_response["time_s"]) - float(time_s)) > 1e-12 or
                    worker_response["return_code"] != 0 or
                    worker_response["finite_value_audit"] is not True or
                    worker_response["sequence"] != expected_bridge or
                    worker_response["ack"] not in (1, "ack", "committed") or
                    not worker_response["payload_hash"]):
                raise CoordinatorError("C++ worker response identity/return/finite audit mismatch")
            if motion_by_slice is None:
                raise CoordinatorError("C++ confirm requires motion_by_slice for each real slice")
            record = self._barrier.advance_step(global_step=global_step, time_s=time_s,
                                                motion_by_slice=motion_by_slice)
            if record.get("committed") is not True or record.get("barrier_passed") is not True:
                raise CoordinatorError("global barrier did not produce a committed record")
            record["worker_response"] = worker_response
            record["cpp_worker_start_count"] = 1
            self._records.append(record)
            self._next_global_step += 1
            return record
        except Exception:
            self._terminal = True
            raise

    def stop(self) -> dict[str, Any]:
        errors: list[str] = []
        if self._barrier is not None:
            try: self._barrier.stop()
            except Exception as exc: errors.append(str(exc))
        try:
            stop = getattr(self.worker, "stop", None)
            if not callable(stop):
                stop = getattr(self.worker, "shutdown", None)
            if not callable(stop):
                raise CoordinatorError("worker has no stop/shutdown lifecycle method")
            stop()
        except Exception as exc: errors.append(str(exc))
        self._started = False
        self._terminal = True
        residual = (self._barrier.owned_residual if self._barrier is not None else 0)
        residual += int(getattr(self.worker, "owned_residual", 0))
        worker_starts = int(getattr(self.worker, "start_count", 0))
        slice_starts = []
        external_starts = []
        if self._barrier is not None:
            for engine in self._barrier.engines.values():
                slice_starts.append(int(getattr(engine, "start_count", 0)))
                backend = getattr(engine, "backend", None)
                external_starts.append(int(getattr(backend, "start_count", 0)))
        starts = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
        if self.contract.allow_real_external_processes:
            starts = {"MATLAB": 0, "OpenFOAM": sum(external_starts),
                      "WSL": sum(external_starts), "CFD": sum(external_starts)}
        return {"errors": errors, "owned_residual": residual,
                "committed_steps": len(self._records), "worker_start_count": worker_starts,
                "slice_start_counts": slice_starts,
                "real_process_starts": starts,
                "parent_pid": os.getpid()}

    @staticmethod
    def _force_matrix(payloads: Mapping[int, Any]) -> tuple[tuple[float, float, float], ...]:
        """Extract only the already audited force/load values from slices."""
        rows = []
        for sid in range(3):
            payload = payloads.get(sid)
            load = payload.get("load") if isinstance(payload, Mapping) else None
            if not isinstance(load, Mapping):
                raise CoordinatorError(f"slice {sid} has no audited load payload")
            keys = ("force_x_N", "force_y_N", "force_z_N")
            if not all(key in load for key in keys):
                keys = ("force_2d_x_N", "force_2d_y_N", "force_2d_z_N")
            if not all(key in load for key in keys):
                raise CoordinatorError(f"slice {sid} load payload has no canonical force fields")
            values = tuple(float(load[key]) for key in keys)
            if not all(math.isfinite(value) for value in values):
                raise CoordinatorError(f"slice {sid} load payload is non-finite")
            rows.append(values)
        return tuple(rows)

    def commit_step_with_cpp_adapter(self, *, global_step: int, time_s: float,
                                     adapter: Any, previous_slice_forces: Mapping[int, Sequence[float]],
                                     motion_builder: Callable[[Mapping[str, Any], int], Any]) -> dict[str, Any]:
        """Run the complete predict -> barrier -> correct -> commit sequence.

        ``motion_builder`` is pure contract translation: it may only build the
        three canonical target motions from the predictor record and slice id.
        """
        if self._barrier is None or not self._started or self._terminal:
            raise CoordinatorError("C++ confirm is unavailable")
        if set(previous_slice_forces) != {0, 1, 2}:
            raise CoordinatorError("previous slice force set must contain exactly three slices")
        expected_time = self.contract.source_time_s + (global_step - self.contract.source_global_step) * self.contract.global_dt_s
        if (global_step != self._next_global_step or
                len(self._records) >= self.contract.steps or
                abs(float(time_s) - expected_time) > 1e-12):
            raise CoordinatorError("C++ confirm step/time is outside the exact bounded sequence")
        previous = tuple(tuple(float(value) for value in previous_slice_forces[sid]) for sid in range(3))
        try:
            prediction, _ = adapter.predict(global_step, time_s, previous)
            expected_bridge = global_step - self.contract.source_global_step
            expected_tick = self.contract.source_tick + expected_bridge * round(self.contract.global_dt_s * 1e9)
            if (prediction.get("global_step") != global_step or
                    prediction.get("case_local_bridge_step") != expected_bridge or
                    prediction.get("run_id") != self.contract.run_id or
                    prediction.get("case_id") != self.contract.case_id or
                    prediction.get("integer_tick") != expected_tick or
                    abs(float(prediction.get("time_s")) - float(time_s)) > 1e-12 or
                    prediction.get("ack") not in (1, "ack", "committed") or
                    prediction.get("finite_value_audit") is not True):
                raise CoordinatorError("C++ predictor identity/ack/finite audit mismatch")
            motions = {sid: motion_builder(prediction, sid) for sid in range(3)}
            prepared = self._barrier.prepare_step(global_step=global_step, time_s=time_s,
                                                  motion_by_slice=motions)
            force_rows = self._force_matrix(self._barrier.last_payloads)
            correction, _ = adapter.correct(global_step, time_s, force_rows)
            record = self._barrier.commit_prepared(worker_response=correction)
            adapter.finalize_committed()
            record["worker_prediction"] = prediction
            record["worker_correction"] = correction
            record["prepared_barrier"] = prepared
            self._records.append(record)
            self._next_global_step += 1
            return record
        except Exception:
            self._terminal = True
            raise


def build_predictor_motion_by_slice(*, prediction: Mapping[str, Any], manifest: SliceManifest,
                                    H_by_slice_id: Mapping[int, Any],
                                    reference_positions_m: Mapping[int, Sequence[float]],
                                    global_step: int, time_s: float) -> dict[int, MotionRecord]:
    """Build all target-time motions from one explicitly audited predictor.

    This helper is pure contract translation.  It requires predictor q,
    qdot and qddot from the same committed-state/Newmark prediction and
    rejects missing or dimensionally inconsistent fields before any slice
    process can be touched.
    """
    required = ("global_step", "case_local_bridge_step", "time_s", "integer_tick",
                "run_id", "case_id", "predictor", "predictor_qdot", "predictor_qddot")
    missing = [key for key in required if key not in prediction]
    if missing:
        raise CoordinatorError("predictor motion is missing: " + ",".join(missing))
    if int(prediction["global_step"]) != int(global_step) or abs(float(prediction["time_s"]) - float(time_s)) > 1e-12:
        raise CoordinatorError("predictor motion identity does not match target step/time")
    if set(H_by_slice_id) != {item.slice_id for item in manifest.slices}:
        raise CoordinatorError("predictor H mapping does not match the manifest")
    if set(reference_positions_m) != set(H_by_slice_id):
        raise CoordinatorError("predictor reference positions do not match the manifest")
    q = tuple(float(value) for value in prediction["predictor"])
    qdot = tuple(float(value) for value in prediction["predictor_qdot"])
    qddot = tuple(float(value) for value in prediction["predictor_qddot"])
    motions: dict[int, MotionRecord] = {}
    for item in manifest.slices:
        try:
            motions[item.slice_id] = motion_from_ancf_state(
                manifest, item.slice_id, H_by_slice_id[item.slice_id], q, qdot, qddot,
                step=int(global_step), time_s=float(time_s),
                reference_position_m=reference_positions_m[item.slice_id],
            )
        except Exception as exc:
            raise CoordinatorError(f"predictor motion construction failed for slice {item.slice_id}: {exc}") from exc
    return motions
