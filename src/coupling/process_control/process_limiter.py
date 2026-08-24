"""Real admission control and interval evidence for heavy solver processes.

The limiter reserves a slot before spawning a child and releases it from a
watcher that waits on the actual child process.  This is deliberately a
small, process-agnostic component so unit tests can exercise the exact
failure paths without starting OpenFOAM.
"""

from __future__ import annotations

import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class ProcessLimiterError(RuntimeError):
    """Raised when process admission or lifecycle accounting is invalid."""


@dataclass(frozen=True)
class ProcessInterval:
    run_id: str
    process_id: int | str | None
    slice_id: int
    global_step: int
    start_time_ns: int
    end_time_ns: int | None
    exit_code: int | None
    condition: str

    @property
    def active(self) -> bool:
        return self.end_time_ns is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "process_id": self.process_id,
            "slice_id": self.slice_id,
            "global_step": self.global_step,
            "start_time_ns": self.start_time_ns,
            "end_time_ns": self.end_time_ns,
            "exit_code": self.exit_code,
            "condition": self.condition,
        }


class ProcessPermit:
    """A single reserved slot, released exactly once."""

    def __init__(self, limiter: "ProcessLimiter", token: str, slice_id: int, global_step: int) -> None:
        self._limiter = limiter
        self.token = token
        self.slice_id = int(slice_id)
        self.global_step = int(global_step)
        self.process_id: int | str | None = None
        self.start_time_ns: int | None = None
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def attach(self, process_id: int | str, *, start_time_ns: int | None = None) -> None:
        if self._released:
            raise ProcessLimiterError("cannot attach a released permit")
        if self.process_id is not None:
            raise ProcessLimiterError("permit is already attached")
        self.process_id = process_id
        self.start_time_ns = int(start_time_ns if start_time_ns is not None else time.time_ns())
        self._limiter._attach(self)

    def release(self, *, exit_code: int | None, condition: str = "completed", end_time_ns: int | None = None) -> None:
        if self._released:
            raise ProcessLimiterError("permit released more than once")
        self._limiter._release(self, exit_code=exit_code, condition=condition, end_time_ns=end_time_ns)
        self._released = True

    def __enter__(self) -> "ProcessPermit":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._released:
            self.release(exit_code=None, condition="exception")


class ManagedProcess:
    """A subprocess paired with the watcher-owned limiter permit."""

    def __init__(self, process: subprocess.Popen[Any], permit: ProcessPermit, command: Sequence[str]) -> None:
        self.process = process
        self.permit = permit
        self.command = list(command)
        self._watcher = threading.Thread(target=self._watch, name=f"process-watch-{process.pid}", daemon=True)
        self._watcher.start()

    def _watch(self) -> None:
        code = self.process.wait()
        if not self.permit.released:
            self.permit.release(exit_code=int(code), condition="completed" if code == 0 else "failed")

    @property
    def pid(self) -> int:
        return int(self.process.pid)

    def poll(self) -> int | None:
        return self.process.poll()

    def wait(self, timeout: float | None = None) -> int:
        try:
            code = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5.0)
            self._watcher.join(timeout=5.0)
            raise TimeoutError(f"process {self.pid} timed out")
        self._watcher.join(timeout=5.0)
        return int(code)

    def terminate(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.kill()


class ProcessLimiter:
    """Bounded runtime admission with independent overlap calculation."""

    def __init__(self, max_processes: int, *, run_id: str | None = None) -> None:
        if int(max_processes) < 1:
            raise ValueError("max_processes must be at least one")
        self.max_processes = int(max_processes)
        self.run_id = str(run_id or f"process_limiter_{uuid.uuid4().hex}")
        self._condition = threading.Condition()
        self._active: dict[str, ProcessPermit] = {}
        self._records: list[ProcessInterval] = []
        self._peak_active_count = 0
        self._closed = False

    @property
    def active_count(self) -> int:
        with self._condition:
            return len(self._active)

    @property
    def peak_active_count(self) -> int:
        with self._condition:
            return self._peak_active_count

    def acquire(self, *, slice_id: int, global_step: int, timeout_s: float | None = None) -> ProcessPermit:
        deadline = None if timeout_s is None else time.monotonic() + float(timeout_s)
        with self._condition:
            while len(self._active) >= self.max_processes:
                if self._closed:
                    raise ProcessLimiterError("limiter is shut down")
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0.0:
                    raise TimeoutError("timed out waiting for process limiter permit")
                self._condition.wait(timeout=remaining)
            if self._closed:
                raise ProcessLimiterError("limiter is shut down")
            token = uuid.uuid4().hex
            permit = ProcessPermit(self, token, slice_id, global_step)
            self._active[token] = permit
            self._peak_active_count = max(self._peak_active_count, len(self._active))
            return permit

    def launch(
        self,
        command: Sequence[str],
        *,
        slice_id: int,
        global_step: int,
        timeout_s: float | None = None,
        **popen_kwargs: Any,
    ) -> ManagedProcess:
        permit = self.acquire(slice_id=slice_id, global_step=global_step, timeout_s=timeout_s)
        try:
            process = subprocess.Popen(list(command), **popen_kwargs)
            permit.attach(process.pid)
            return ManagedProcess(process, permit, command)
        except BaseException:
            if not permit.released:
                permit.release(exit_code=None, condition="spawn_failed")
            raise

    def _attach(self, permit: ProcessPermit) -> None:
        # Attachment is retained on the permit; this hook gives tests and
        # future process managers one synchronization point for lifecycle.
        with self._condition:
            if permit.token not in self._active:
                raise ProcessLimiterError("unknown permit")
            self._condition.notify_all()

    def _release(self, permit: ProcessPermit, *, exit_code: int | None, condition: str, end_time_ns: int | None) -> None:
        with self._condition:
            active = self._active.pop(permit.token, None)
            if active is None:
                raise ProcessLimiterError("unknown or already released permit")
            start = int(permit.start_time_ns if permit.start_time_ns is not None else time.time_ns())
            end = int(end_time_ns if end_time_ns is not None else time.time_ns())
            if end < start:
                raise ProcessLimiterError("process end precedes process start")
            self._records.append(ProcessInterval(
                run_id=self.run_id,
                process_id=permit.process_id,
                slice_id=permit.slice_id,
                global_step=permit.global_step,
                start_time_ns=start,
                end_time_ns=end,
                exit_code=None if exit_code is None else int(exit_code),
                condition=str(condition),
            ))
            self._condition.notify_all()

    def records(self) -> list[ProcessInterval]:
        with self._condition:
            return list(self._records)

    def audit(self) -> dict[str, Any]:
        records = self.records()
        events: list[tuple[int, int]] = []
        for item in records:
            if item.end_time_ns is None:
                continue
            events.append((item.start_time_ns, 1))
            events.append((item.end_time_ns, -1))
        active = 0
        interval_peak = 0
        for timestamp, delta in sorted(events, key=lambda value: (value[0], 0 if value[1] < 0 else 1)):
            active += delta
            interval_peak = max(interval_peak, active)
        return {
            "run_id": self.run_id,
            "max_processes": self.max_processes,
            "active_count": self.active_count,
            "peak_active_count": self.peak_active_count,
            "interval_peak_active_count": interval_peak,
            "records": [item.to_dict() for item in records],
            "permit_leak": self.active_count != 0,
            "enforced": interval_peak <= self.max_processes and self.peak_active_count <= self.max_processes,
        }

    def assert_no_leaks(self) -> None:
        if self.active_count:
            raise ProcessLimiterError(f"{self.active_count} process permits remain active")

    def shutdown(self, *, force: bool = False) -> dict[str, Any]:
        with self._condition:
            if self._active and not force:
                raise ProcessLimiterError("cannot shut down with active process permits")
            self._closed = True
            active = list(self._active.values())
        if force:
            for permit in active:
                if not permit.released:
                    permit.release(exit_code=None, condition="shutdown")
        return self.audit()
