from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .protocol import ProtocolError, WorkerRequest, WorkerResponse, canonical_json, canonical_sha256


@dataclass
class WorkerProcessAudit:
    pid: int
    creation_time_ns: int
    parent_pid: int
    command_line: list[str]
    cwd: str
    executable: str
    start_time_ns: int
    end_time_ns: int | None = None
    return_code: int | None = None
    owned: bool = True
    cleanup_result: str = "open"

    def close(self, return_code: int = 0) -> None:
        self.end_time_ns = time.time_ns()
        self.return_code = int(return_code)
        self.cleanup_result = "closed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OfflineMatlabWorker:
    """Persistent worker model; it never starts MATLAB or another process."""

    external_process_starts = 0
    _next_pid = 61000

    def __init__(self, *, run_id: str, case_id: str, runtime: str | Path,
                 first_global_step: int | None = 0, first_bridge_step: int | None = 0,
                 dt_s: float = 0.0025, fault: str | None = None,
                 compute: Callable[[WorkerRequest], Any] | None = None) -> None:
        self.run_id, self.case_id = run_id, case_id
        self.runtime = Path(runtime)
        self.first_global_step, self.first_bridge_step, self.dt_s = first_global_step, first_bridge_step, dt_s
        self.fault, self.compute = fault, compute or (lambda request: {"state": request.global_step, "time_s": request.time_s})
        self.audit: WorkerProcessAudit | None = None
        self.started = False
        self.failed = False
        self.last_global_step: int | None = None
        self.last_bridge_step: int | None = None
        self.last_phase: str | None = None
        self.requests: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.seen_request_ids: set[str] = set()
        self.seen_transactions: set[str] = set()
        self.start_count = 0
        self.request_count = 0
        self.initialized = False

    def start(self) -> WorkerProcessAudit:
        if self.started:
            raise ProtocolError("worker already started")
        self.runtime.mkdir(parents=True, exist_ok=True)
        type(self)._next_pid += 1
        now = time.time_ns()
        self.audit = WorkerProcessAudit(type(self)._next_pid, now, os.getpid(),
                                        ["offline-matlab-worker", self.run_id], str(self.runtime),
                                        "offline-mock-matlab-worker", now)
        self.started = True
        self.start_count += 1
        return self.audit

    def _expected(self, global_step: int, bridge_step: int) -> None:
        expected_global = global_step if self.last_global_step is None and self.first_global_step is None else (self.first_global_step if self.last_global_step is None else self.last_global_step + 1)
        expected_bridge = bridge_step if self.last_bridge_step is None and self.first_bridge_step is None else (self.first_bridge_step if self.last_bridge_step is None else self.last_bridge_step + 1)
        if (global_step, bridge_step) != (expected_global, expected_bridge):
            raise ProtocolError("stale, duplicate, out-of-order, or bridge-step mismatch")

    def initialize(self, *, global_step: int, case_local_bridge_step: int, time_s: float,
                   integer_tick: int, request_id: str, transaction_id: str) -> WorkerResponse:
        if not self.started or self.audit is None or self.failed:
            raise ProtocolError("worker unavailable")
        if self.initialized:
            raise ProtocolError("worker already initialized")
        if integer_tick != int(round(float(time_s) * 1_000_000_000)):
            raise ProtocolError("initialize time/tick mismatch")
        request = WorkerRequest.create(operation="initialize", run_id=self.run_id, case_id=self.case_id,
                                       global_step=global_step, case_local_bridge_step=case_local_bridge_step,
                                       time_s=time_s, integer_tick=integer_tick, request_id=request_id,
                                       transaction_id=transaction_id, payload={"operation": "initialize"})
        self.seen_request_ids.add(request_id); self.seen_transactions.add(transaction_id)
        self.requests.append(request.to_dict()); self.request_count += 1
        payload = {"initialized": True, "time_s": time_s}
        output = self.runtime / "initialize_response.json"
        output.write_bytes(canonical_json(payload)); stat = output.stat()
        response = WorkerResponse.create(request, payload=payload, output_sha256=canonical_sha256(payload),
                                         output_size=stat.st_size, output_mtime_ns=stat.st_mtime_ns, return_code=0,
                                         worker_pid=self.audit.pid, worker_creation_time=self.audit.creation_time_ns,
                                         parent_pid=self.audit.parent_pid, command_line=self.audit.command_line)
        response.validate(request); self.responses.append(response.to_dict()); self.initialized = True
        return response

    def process(self, *, global_step: int, case_local_bridge_step: int, time_s: float,
                integer_tick: int, request_id: str, transaction_id: str,
                operation: str = "prediction_correction") -> WorkerResponse:
        if not self.started or self.audit is None or self.failed:
            raise ProtocolError("worker unavailable")
        if integer_tick != int(round(float(time_s) * 1_000_000_000)):
            raise ProtocolError("request time/tick mismatch")
        if request_id in self.seen_request_ids or transaction_id in self.seen_transactions:
            raise ProtocolError("duplicate request or transaction")
        if operation not in {"prediction", "correction", "prediction_correction"}:
            raise ProtocolError("unsupported worker operation")
        if operation == "correction":
            if self.last_phase != "prediction" or (global_step, case_local_bridge_step) != (self.last_global_step, self.last_bridge_step):
                raise ProtocolError("correction must follow prediction at the same step")
        elif operation == "prediction":
            self._expected(global_step, case_local_bridge_step)
        else:
            self._expected(global_step, case_local_bridge_step)
        # The caller supplies the absolute case time; only finiteness is checked here.
        request = WorkerRequest.create(operation=operation, run_id=self.run_id, case_id=self.case_id,
                                       global_step=global_step, case_local_bridge_step=case_local_bridge_step,
                                       time_s=time_s, integer_tick=integer_tick, request_id=request_id,
                                       transaction_id=transaction_id, payload={"operation": "prediction_correction"})
        self.seen_request_ids.add(request_id); self.seen_transactions.add(transaction_id)
        self.requests.append(request.to_dict())
        self.request_count += 1
        self.initialized = True
        if self.fault in {"disconnect", "timeout", "crash"}:
            self.failed = True
            raise ProtocolError(f"worker {self.fault}")
        payload = self.compute(request)
        if self.fault == "nan":
            payload = {"state": float("nan")}
        return_code = 5001 if self.fault == "5001" else (1 if self.fault == "nonzero" else 0)
        if return_code != 0:
            self.failed = True
            raise ProtocolError(f"worker return code {return_code}")
        encoded = canonical_json(payload)
        output = self.runtime / f"response_{global_step:08d}.json"
        if self.fault == "missing_output":
            self.failed = True
            raise ProtocolError("worker output missing")
        output.write_bytes(encoded)
        stat = output.stat()
        response = WorkerResponse.create(request, payload=payload, output_sha256=canonical_sha256(payload),
                                         output_size=stat.st_size, output_mtime_ns=stat.st_mtime_ns,
                                         return_code=0, worker_pid=self.audit.pid,
                                         worker_creation_time=self.audit.creation_time_ns,
                                         parent_pid=self.audit.parent_pid,
                                         command_line=self.audit.command_line)
        if self.fault == "identity":
            response = WorkerResponse(**{**response.to_dict(), "case_id": "wrong-case"})
        elif self.fault == "tick_mismatch":
            response = WorkerResponse(**{**response.to_dict(), "integer_tick": integer_tick + 1})
        elif self.fault == "time_mismatch":
            response = WorkerResponse(**{**response.to_dict(), "time_s": time_s + self.dt_s})
        elif self.fault == "hash_mismatch":
            response = WorkerResponse(**{**response.to_dict(), "output_sha256": "0" * 64})
        response.validate(request)
        self.last_global_step, self.last_bridge_step = global_step, case_local_bridge_step
        self.last_phase = operation
        self.responses.append(response.to_dict())
        return response

    def stop(self, return_code: int = 0) -> WorkerProcessAudit:
        if self.audit is None:
            raise ProtocolError("worker has not started")
        if self.audit.cleanup_result != "closed":
            self.audit.close(return_code)
        self.started = False
        return self.audit

    @property
    def residual(self) -> int:
        return int(self.audit is not None and self.audit.cleanup_result != "closed")
