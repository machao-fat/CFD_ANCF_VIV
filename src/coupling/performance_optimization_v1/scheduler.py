from __future__ import annotations

import concurrent.futures
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from .contracts import IPCMessage, OptimizationConfig, ProtocolViolation, SCHEMA_VERSION, finite_audit
from .ipc import PersistentIPC
from .workers import MockMatlabWorker, MockOpenFOAMSlice, WorkerLifecycleError


class BarrierError(ProtocolViolation):
    pass


@dataclass
class StepRecord:
    global_step: int
    time_s: float
    integer_tick: int
    total_s: float
    phases: dict[str, float]
    slice_completion_order: list[int]
    barrier_passed: bool
    checkpoint_committed: bool

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class SchedulerResult:
    records: list[StepRecord]
    matlab_start_count: int
    openfoam_start_counts: dict[int, int]
    process_audits: list[dict[str, Any]]
    ipc_stats: dict[int, dict[str, Any]]
    owned_residual: int
    external_process_starts: int
    status: str = "passed"
    worker_exchanges: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [r.to_dict() for r in self.records],
            "matlab_start_count": self.matlab_start_count,
            "openfoam_start_counts": self.openfoam_start_counts,
            "process_audits": self.process_audits,
            "ipc_stats": self.ipc_stats,
            "owned_residual": self.owned_residual,
            "external_process_starts": self.external_process_starts,
            "status": self.status,
            "worker_exchanges": self.worker_exchanges,
        }


class GlobalBarrierScheduler:
    """Step scheduler with optional lifecycle/IPC optimizations.

    The global barrier is explicit: no checkpoint callback and no next-step
    MATLAB request occur until every slice completed motion consume, CFD
    advance, force/load, and identity validation for the current step.
    """

    def __init__(self, *, config: OptimizationConfig, run_id: str, case_id: str,
                 runtime_dir: str | Path, persistent_matlab: bool = True,
                 persistent_openfoam: bool = True, parallel_slices: bool = True,
                 persistent_ipc: bool = True, faults: dict[int, str] | None = None,
                 slice_compute: Callable[[int, int, float], Any] | None = None,
                 checkpoint_callback: Callable[[int, Sequence[Any]], None] | None = None) -> None:
        config.validate()
        self.config, self.run_id, self.case_id = config, run_id, case_id
        self.runtime_dir = Path(runtime_dir)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.persistent_matlab = persistent_matlab
        self.persistent_openfoam = persistent_openfoam
        self.parallel_slices = parallel_slices
        self.persistent_ipc = persistent_ipc
        self.faults = dict(faults or {})
        self.slice_compute = slice_compute
        self.checkpoint_callback = checkpoint_callback
        self.matlab: MockMatlabWorker | None = None
        self.slices: dict[int, MockOpenFOAMSlice] = {}
        self._all_matlab: list[MockMatlabWorker] = []
        self._all_slices: dict[int, list[MockOpenFOAMSlice]] = {sid: [] for sid in range(config.slice_count)}
        self.channels: dict[int, PersistentIPC] = {}
        self._failed = False
        self._persistent_matlab_start_s = 0.0
        self._persistent_openfoam_start_s = 0.0

    def _new_matlab(self) -> MockMatlabWorker:
        worker = MockMatlabWorker(run_id=self.run_id, case_id=self.case_id,
                                  output_dir=self.runtime_dir / "matlab", fault=self.faults.get(-1))
        worker.start()
        self._all_matlab.append(worker)
        return worker

    def _new_slice(self, slice_id: int) -> MockOpenFOAMSlice:
        compute = None if self.slice_compute is None else (lambda step, t, sid=slice_id: self.slice_compute(sid, step, t))
        worker = MockOpenFOAMSlice(run_id=self.run_id, case_id=self.case_id, slice_id=slice_id,
                                   output_dir=self.runtime_dir / f"slice_{slice_id}", fault=self.faults.get(slice_id),
                                   compute=compute)
        worker.start()
        self._all_slices[slice_id].append(worker)
        return worker

    def _start_persistent(self) -> None:
        if self.persistent_matlab:
            started = time.perf_counter()
            self.matlab = self._new_matlab()
            self._persistent_matlab_start_s = time.perf_counter() - started
        for sid in range(self.config.slice_count):
            if self.persistent_openfoam:
                started = time.perf_counter()
                self.slices[sid] = self._new_slice(sid)
                self._persistent_openfoam_start_s += time.perf_counter() - started
            if self.persistent_ipc:
                self.channels[sid] = PersistentIPC(run_id=self.run_id, case_id=self.case_id, slice_id=sid)

    def _step_matlab(self, step: int, t: float, tick: int):
        start_elapsed = 0.0
        if self.persistent_matlab:
            worker = self.matlab
        else:
            started = time.perf_counter()
            worker = self._new_matlab()
            start_elapsed = time.perf_counter() - started
        req, txn = uuid.uuid4().hex, uuid.uuid4().hex
        try:
            result = worker.process_step(global_step=step, case_local_bridge_step=step,
                                         time_s=t, integer_tick=tick, request_id=req, transaction_id=txn)
            try:
                result.validate_against(run_id=self.run_id, case_id=self.case_id, global_step=step,
                                        case_local_bridge_step=step, time_s=t, integer_tick=tick)
            except ProtocolViolation:
                worker.failed = True
                worker.failure_code = 1
                raise
            return result, start_elapsed
        finally:
            if not self.persistent_matlab:
                worker.stop()

    def _step_slice(self, sid: int, step: int, t: float, tick: int):
        start_elapsed = 0.0
        if self.persistent_openfoam:
            worker = self.slices[sid]
        else:
            started = time.perf_counter()
            worker = self._new_slice(sid)
            start_elapsed = time.perf_counter() - started
        req, txn = uuid.uuid4().hex, uuid.uuid4().hex
        handshake_started = time.perf_counter()
        if self.persistent_ipc:
            channel = self.channels[sid]
            motion = IPCMessage.create(run_id=self.run_id, case_id=self.case_id, slice_id=sid,
                                       global_step=step, case_local_bridge_step=step, time_s=t,
                                       integer_tick=tick, request_id=req, transaction_id=txn,
                                       sequence=2 * step + 1, producer="matlab", consumer=f"openfoam_{sid}",
                                       ack=False, payload={"motion": step})
            channel.send(motion)
            consumed = channel.receive(timeout_s=0.5)
            if consumed.transaction_id != txn or consumed.consumer != f"openfoam_{sid}":
                raise BarrierError("motion ack transaction mismatch")
            motion_ack = channel.ack(motion, producer=f"openfoam_{sid}", consumer="matlab", sequence=2 * step + 1)
            channel.send(motion_ack)
            received_ack = channel.receive(timeout_s=0.5)
            if not received_ack.ack or received_ack.transaction_id != txn or received_ack.consumer != "matlab":
                raise BarrierError("motion acknowledgement validation failed")
        else:
            # Offline representation of the legacy small-file handshake.  It
            # is deliberately isolated from the persistent IPC path so both
            # costs can be measured without launching external engines.
            file_path = self.runtime_dir / f"slice_{sid}" / f"file_handshake_{step:06d}.json"
            file_payload = {
                "schema_version": SCHEMA_VERSION, "run_id": self.run_id, "case_id": self.case_id,
                "slice_id": sid, "global_step": step, "case_local_bridge_step": step,
                "time_s": t, "integer_tick": tick, "request_id": req, "transaction_id": txn,
                "producer": "matlab", "consumer": f"openfoam_{sid}", "ack": True,
                "payload": {"motion": step, "load": f"pending_{step}"},
            }
            finite_audit(file_payload["payload"], "file_handshake.payload")
            file_path.write_text(json.dumps(file_payload, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
            loaded = json.loads(file_path.read_text(encoding="utf-8"))
            if loaded != file_payload:
                raise BarrierError("file handshake readback mismatch")
        handshake_elapsed = time.perf_counter() - handshake_started if self.persistent_ipc else 0.0
        try:
            advance_started = time.perf_counter()
            result = worker.advance(global_step=step, case_local_bridge_step=step, time_s=t,
                                    integer_tick=tick, request_id=req, transaction_id=txn)
            advance_elapsed = time.perf_counter() - advance_started
            try:
                result.validate_against(run_id=self.run_id, case_id=self.case_id, global_step=step,
                                        case_local_bridge_step=step, time_s=t, integer_tick=tick)
            except ProtocolViolation:
                worker.failed = True
                worker.failure_code = 1
                raise
            if self.persistent_ipc:
                load_req, load_txn = uuid.uuid4().hex, uuid.uuid4().hex
                load = IPCMessage.create(run_id=self.run_id, case_id=self.case_id, slice_id=sid,
                                         global_step=step, case_local_bridge_step=step, time_s=t,
                                         integer_tick=tick, request_id=load_req, transaction_id=load_txn,
                                         sequence=2 * step + 2, producer=f"openfoam_{sid}", consumer="matlab",
                                         ack=False, payload={"load_hash": result.payload_hash})
                channel.send(load)
                received_load = channel.receive(timeout_s=0.5)
                if received_load.transaction_id != load_txn or received_load.consumer != "matlab":
                    raise BarrierError("load identity validation failed")
                load_ack = channel.ack(load, producer="matlab", consumer=f"openfoam_{sid}", sequence=2 * step + 2)
                channel.send(load_ack)
                received_load_ack = channel.receive(timeout_s=0.5)
                if not received_load_ack.ack or received_load_ack.transaction_id != load_txn:
                    raise BarrierError("load acknowledgement validation failed")
            return sid, result, start_elapsed, handshake_elapsed, advance_elapsed
        finally:
            if not self.persistent_openfoam:
                worker.stop()

    def run(self, *, steps: int | None = None) -> SchedulerResult:
        if self._failed:
            raise BarrierError("scheduler is fail-closed")
        count = self.config.steps_per_segment if steps is None else int(steps)
        if count <= 0 or count > self.config.steps_per_segment:
            raise BarrierError("step count exceeds the authorized segment")
        self._start_persistent()
        records: list[StepRecord] = []
        try:
            for step in range(count):
                started = time.perf_counter()
                t = step * self.config.global_dt_s
                tick = step
                phase: dict[str, float] = {}
                p = time.perf_counter(); _, matlab_start_s = self._step_matlab(step, t, tick)
                matlab_elapsed = time.perf_counter() - p
                phase["matlab_prediction_s"] = matlab_elapsed / 2.0
                phase["matlab_correction_s"] = matlab_elapsed / 2.0
                phase["matlab_prediction_correction_s"] = matlab_elapsed
                p = time.perf_counter(); completion: list[int] = []
                results: list[tuple[int, Any, float, float, float]] = []
                if self.parallel_slices:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.slice_count) as pool:
                        futures = [pool.submit(self._step_slice, sid, step, t, tick) for sid in range(self.config.slice_count)]
                        for future in concurrent.futures.as_completed(futures):
                            item = future.result()
                            results.append(item)
                            completion.append(item[0])
                else:
                    for sid in range(self.config.slice_count):
                        item = self._step_slice(sid, step, t, tick)
                        results.append(item)
                        completion.append(item[0])
                advance_times = [item[4] for item in results]
                handshake_times = [item[3] for item in results]
                start_times = [item[2] for item in results]
                phase["openfoam_solver_s"] = (sum(advance_times) if not self.parallel_slices else max(advance_times, default=0.0))
                phase["openfoam_s"] = phase["openfoam_solver_s"]
                phase["wsl_process_start_s"] = ((self._persistent_matlab_start_s + self._persistent_openfoam_start_s) if step == 0 else 0.0) + matlab_start_s + (sum(start_times) if not self.parallel_slices else max(start_times, default=0.0))
                phase["motion_ack_load_handshake_s"] = (sum(handshake_times) if not self.parallel_slices else max(handshake_times, default=0.0))
                if len(completion) != self.config.slice_count or set(completion) != set(range(self.config.slice_count)):
                    raise BarrierError("global barrier missing slice completion")
                p = time.perf_counter()
                self._checkpoint_snapshot_audit(step, t, tick, results)
                if self.checkpoint_callback is not None:
                    self.checkpoint_callback(step, results)
                phase["checkpoint_snapshot_audit_s"] = time.perf_counter() - p
                records.append(StepRecord(step, t, tick, time.perf_counter() - started, phase,
                                          completion, True, True))
        except Exception as exc:
            self._failed = True
            if isinstance(exc, BarrierError):
                raise
            raise BarrierError(str(exc)) from exc
        finally:
            self._close_workers()
        audits = [worker.audit.to_dict() for worker in self._all_matlab if worker.audit]
        audits.extend(worker.audit.to_dict() for workers in self._all_slices.values() for worker in workers if worker.audit)
        ipc_stats = {sid: channel.stats().__dict__ for sid, channel in self.channels.items()}
        worker_exchanges: dict[str, Any] = {}
        if self._all_matlab:
            worker_exchanges["matlab"] = {
                "requests": [item for worker in self._all_matlab for item in worker.request_audits],
                "responses": [item for worker in self._all_matlab for item in worker.response_audits],
            }
        worker_exchanges["slices"] = {
            str(sid): {
                "requests": [item for worker in workers for item in worker.request_audits],
                "responses": [item for worker in workers for item in worker.response_audits],
            }
            for sid, workers in self._all_slices.items()
        }
        return SchedulerResult(records, len(self._all_matlab),
                               {sid: len(workers) for sid, workers in self._all_slices.items()}, audits,
                               ipc_stats, self._owned_residual(), 0, "passed", worker_exchanges)

    def _owned_residual(self) -> int:
        """Count owned runtime resources that survived normal closeout."""
        residual = sum(1 for worker in self._all_matlab + [item for values in self._all_slices.values() for item in values]
                       if worker.audit is None or worker.audit.cleanup_status != "closed")
        residual += sum(1 for channel in self.channels.values() if channel.connected or channel.poisoned)
        residual += sum(getattr(channel, "_queue").qsize() for channel in self.channels.values())
        return residual

    def _checkpoint_snapshot_audit(self, step: int, time_s: float, integer_tick: int,
                                   results: Sequence[tuple[int, Any, float, float, float]]) -> None:
        """Commit a small auditable per-step checkpoint and raw snapshot."""
        checkpoint_dir = self.runtime_dir / "checkpoint_audit"
        snapshot_dir = self.runtime_dir / "raw_snapshot_audit"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        outputs = [
            {"slice_id": item[0], "payload_hash": item[1].payload_hash,
             "worker_pid": item[1].worker_pid, "request_id": item[1].request_id,
             "transaction_id": item[1].transaction_id}
            for item in sorted(results, key=lambda value: value[0])
        ]
        record = {
            "schema_version": SCHEMA_VERSION, "formal_protocol_version": "0.2.1",
            "run_id": self.run_id, "case_id": self.case_id, "global_step": step,
            "case_local_bridge_step": step, "time_s": time_s, "integer_tick": integer_tick,
            "outputs": outputs, "committed": True,
        }
        finite_audit(record, "checkpoint_snapshot")
        checkpoint_path = checkpoint_dir / f"checkpoint_{step:06d}.json"
        snapshot_path = snapshot_dir / f"snapshot_{step:06d}.json"
        encoded = json.dumps(record, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        checkpoint_path.write_text(encoded, encoding="utf-8")
        snapshot_path.write_text(encoded, encoding="utf-8")
        for path in (checkpoint_path, snapshot_path):
            committed = json.loads(path.read_text(encoding="utf-8"))
            if committed != record or not committed["committed"]:
                raise BarrierError(f"checkpoint/snapshot audit mismatch: {path.name}")

    def _close_workers(self) -> None:
        if self.matlab and self.matlab.audit and self.matlab.audit.cleanup_status != "closed":
            self.matlab.stop()
        for worker in self.slices.values():
            if worker.audit and worker.audit.cleanup_status != "closed":
                worker.stop()
        for channel in self.channels.values():
            channel.close()
