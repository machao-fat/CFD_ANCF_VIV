from __future__ import annotations

import os
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from .contracts import ProcessAudit, ProtocolViolation, WorkerEnvelope


class WorkerLifecycleError(ProtocolViolation):
    pass


def _write_audited_envelope(path: Path, envelope: WorkerEnvelope) -> WorkerEnvelope:
    """Write a self-consistent JSON envelope with exact size and mtime."""
    target_mtime_ns = time.time_ns()
    size = 0
    encoded = b""
    for _ in range(8):
        candidate = WorkerEnvelope(**{**envelope.to_dict(), "size": size, "mtime_ns": target_mtime_ns})
        encoded = (json.dumps(candidate.to_dict(), ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
        new_size = len(encoded)
        if new_size == size:
            break
        size = new_size
    path.write_bytes(encoded)
    os.utime(path, ns=(target_mtime_ns, target_mtime_ns))
    stat = path.stat()
    return WorkerEnvelope(**{**candidate.to_dict(), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})


class _PidAllocator:
    value = 40000

    @classmethod
    def next(cls) -> int:
        cls.value += 1
        return cls.value


class MockMatlabWorker:
    """Persistent MATLAB lifecycle model; no MATLAB executable is invoked."""

    external_process_started = False

    def __init__(self, *, run_id: str, case_id: str, output_dir: str | Path,
                 fault: str | None = None, compute: Callable[[int, float], Any] | None = None) -> None:
        self.run_id, self.case_id = run_id, case_id
        self.output_dir = Path(output_dir)
        self.fault, self.compute = fault, compute or (lambda step, t: {"q": float(step), "time_s": t})
        self.audit: ProcessAudit | None = None
        self.started = False
        self.failed = False
        self.failure_code: int | None = None
        self.start_count = 0
        self.request_count = 0
        self.request_audits: list[dict[str, Any]] = []
        self.response_audits: list[dict[str, Any]] = []

    @property
    def pid(self) -> int:
        if self.audit is None:
            raise WorkerLifecycleError("MATLAB worker has not started")
        return self.audit.pid

    def start(self) -> ProcessAudit:
        if self.started:
            raise WorkerLifecycleError("MATLAB worker already started")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.audit = ProcessAudit("matlab_worker", _PidAllocator.next(), time.time_ns(), os.getpid(),
                                  ["offline-mock-matlab-worker"], process_kind="offline_mock")
        self.started, self.start_count = True, self.start_count + 1
        return self.audit

    def process_step(self, *, global_step: int, case_local_bridge_step: int,
                     time_s: float, integer_tick: int, request_id: str | None = None,
                     transaction_id: str | None = None) -> WorkerEnvelope:
        if not self.started or self.audit is None or self.failed:
            raise WorkerLifecycleError("MATLAB worker is unavailable")
        if self.fault == "disconnect":
            self.failed = True
            self.failure_code = 1
            raise WorkerLifecycleError("MATLAB worker disconnected")
        request_payload = {"operation": "ancf_prediction_correction", "global_step": global_step, "time_s": time_s}
        request = WorkerEnvelope.build(
            run_id=self.run_id, case_id=self.case_id, global_step=global_step,
            case_local_bridge_step=case_local_bridge_step, time_s=time_s,
            integer_tick=integer_tick, request_id=request_id, transaction_id=transaction_id,
            payload=request_payload, worker_pid=self.pid,
        )
        request_path = self.output_dir / f"request_{global_step:06d}.json"
        request = _write_audited_envelope(request_path, request)
        self.request_audits.append(request.to_dict())
        payload = self.compute(global_step, time_s)
        return_code = 5001 if self.fault == "5001" else (1 if self.fault == "nonzero" else 0)
        if self.fault == "nan":
            payload = {"q": float("nan")}
            self.failed = True
            self.failure_code = 1
        self.request_count += 1
        envelope = WorkerEnvelope.build(
            run_id=self.run_id, case_id=self.case_id, global_step=global_step,
            case_local_bridge_step=case_local_bridge_step, time_s=time_s,
            integer_tick=integer_tick, request_id=request_id, transaction_id=transaction_id,
            payload=payload, size=len(str(payload).encode()), worker_pid=self.pid,
            return_code=return_code,
        )
        if self.fault == "identity":
            envelope = replace(envelope, case_id="unexpected_case")
        elif self.fault == "tick_mismatch":
            envelope = replace(envelope, integer_tick=integer_tick + 1)
        elif self.fault == "time_mismatch":
            envelope = replace(envelope, time_s=time_s + 1.0)
        if return_code != 0:
            self.failed = True
            self.failure_code = return_code
            raise WorkerLifecycleError(f"MATLAB return code {return_code}")
        if self.fault == "missing_output":
            self.failed = True
            self.failure_code = 1
            raise WorkerLifecycleError("MATLAB output missing")
        output_path = self.output_dir / f"response_{global_step:06d}.json"
        envelope = _write_audited_envelope(output_path, envelope)
        self.response_audits.append(envelope.to_dict())
        return envelope

    def stop(self, return_code: int | None = None) -> ProcessAudit:
        if self.audit is None:
            raise WorkerLifecycleError("MATLAB worker has not started")
        if self.audit.cleanup_status == "closed":
            return self.audit
        self.audit.close(self.failure_code if return_code is None and self.failure_code is not None else (0 if return_code is None else return_code))
        self.started = False
        return self.audit


class MockOpenFOAMSlice:
    """Persistent per-slice OpenFOAM lifecycle model with force output."""

    external_process_started = False

    def __init__(self, *, run_id: str, case_id: str, slice_id: int,
                 output_dir: str | Path, fault: str | None = None,
                 compute: Callable[[int, float], Any] | None = None) -> None:
        self.run_id, self.case_id, self.slice_id = run_id, case_id, int(slice_id)
        self.output_dir = Path(output_dir)
        self.fault, self.compute = fault, compute or (lambda step, t: {"force_y_N": 1.0 + self.slice_id, "time_s": t})
        self.audit: ProcessAudit | None = None
        self.started = False
        self.failed = False
        self.failure_code: int | None = None
        self.start_count = 0
        self.advance_count = 0
        self.request_audits: list[dict[str, Any]] = []
        self.response_audits: list[dict[str, Any]] = []

    @property
    def pid(self) -> int:
        if self.audit is None:
            raise WorkerLifecycleError("OpenFOAM slice has not started")
        return self.audit.pid

    def start(self) -> ProcessAudit:
        if self.started:
            raise WorkerLifecycleError(f"slice {self.slice_id} already started")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.audit = ProcessAudit(f"openfoam_slice_{self.slice_id}", _PidAllocator.next(), time.time_ns(), os.getpid(),
                                  ["offline-mock-openfoam", f"--slice={self.slice_id}"], process_kind="offline_mock")
        self.started, self.start_count = True, self.start_count + 1
        return self.audit

    def advance(self, *, global_step: int, case_local_bridge_step: int,
                time_s: float, integer_tick: int, request_id: str,
                transaction_id: str) -> WorkerEnvelope:
        if not self.started or self.audit is None or self.failed:
            raise WorkerLifecycleError(f"slice {self.slice_id} is unavailable")
        if self.fault in {"disconnect", "timeout"}:
            self.failed = True
            self.failure_code = 1
            raise WorkerLifecycleError(f"slice {self.slice_id} {self.fault}")
        request_payload = {"operation": "openfoam_motion_consume", "slice_id": self.slice_id,
                           "global_step": global_step, "time_s": time_s}
        request = WorkerEnvelope.build(
            run_id=self.run_id, case_id=self.case_id, global_step=global_step,
            case_local_bridge_step=case_local_bridge_step, time_s=time_s,
            integer_tick=integer_tick, request_id=request_id, transaction_id=transaction_id,
            payload=request_payload, worker_pid=self.pid,
        )
        request_path = self.output_dir / f"request_{global_step:06d}.json"
        request = _write_audited_envelope(request_path, request)
        self.request_audits.append(request.to_dict())
        payload = self.compute(global_step, time_s)
        return_code = 5001 if self.fault == "5001" else (1 if self.fault == "nonzero" else 0)
        if self.fault == "nan":
            payload = {"force_y_N": float("nan")}
            self.failed = True
            self.failure_code = 1
        self.advance_count += 1
        envelope = WorkerEnvelope.build(
            run_id=self.run_id, case_id=self.case_id, global_step=global_step,
            case_local_bridge_step=case_local_bridge_step, time_s=time_s,
            integer_tick=integer_tick, request_id=request_id, transaction_id=transaction_id,
            payload=payload, size=len(str(payload).encode()), worker_pid=self.pid,
            return_code=return_code,
        )
        if self.fault == "identity":
            envelope = replace(envelope, case_id="unexpected_case")
        elif self.fault == "tick_mismatch":
            envelope = replace(envelope, integer_tick=integer_tick + 1)
        elif self.fault == "time_mismatch":
            envelope = replace(envelope, time_s=time_s + 1.0)
        if return_code != 0:
            self.failed = True
            self.failure_code = return_code
            raise WorkerLifecycleError(f"slice {self.slice_id} return code {return_code}")
        if self.fault == "missing_output":
            self.failed = True
            self.failure_code = 1
            raise WorkerLifecycleError(f"slice {self.slice_id} output missing")
        output_path = self.output_dir / f"load_{global_step:06d}.json"
        envelope = _write_audited_envelope(output_path, envelope)
        self.response_audits.append(envelope.to_dict())
        return envelope

    def stop(self, return_code: int | None = None) -> ProcessAudit:
        if self.audit is None:
            raise WorkerLifecycleError(f"slice {self.slice_id} has not started")
        if self.audit.cleanup_status == "closed":
            return self.audit
        self.audit.close(self.failure_code if return_code is None and self.failure_code is not None else (0 if return_code is None else return_code))
        self.started = False
        return self.audit
