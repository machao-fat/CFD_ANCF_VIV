from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isfinite

from .protocol import FrameError


@dataclass(frozen=True)
class SliceAck:
    slice_id: int
    global_step: int
    case_local_bridge_step: int
    time_s: float
    integer_tick: int
    transaction_id: int


class GlobalBarrierMock:
    """Offline three-slice barrier with fail-closed identity and ordering checks."""

    def __init__(self, slice_ids: tuple[int, ...] = (0, 1, 2), source_step: int = 559,
                 source_time_s: float = 2.2075, source_tick: int = 2207500000,
                 dt_s: float = 0.00125) -> None:
        self.slice_ids = frozenset(slice_ids)
        self.source_step = source_step
        self.source_time_s = source_time_s
        self.source_tick = source_tick
        self.dt_s = dt_s
        self.next_step = source_step + 1
        self._pending: dict[int, SliceAck] = {}
        self.released: list[int] = []

    def submit(self, ack: SliceAck) -> bool:
        if ack.slice_id not in self.slice_ids or ack.global_step != self.next_step:
            raise FrameError("barrier step or slice identity is not monotonic")
        expected_bridge = ack.global_step - self.source_step
        expected_time = self.source_time_s + expected_bridge * self.dt_s
        expected_tick = self.source_tick + expected_bridge * round(self.dt_s * 1e9)
        if ack.case_local_bridge_step != expected_bridge or ack.integer_tick != expected_tick:
            raise FrameError("barrier bridge step/tick mismatch")
        if not isfinite(ack.time_s) or not isclose(ack.time_s, expected_time, rel_tol=0.0, abs_tol=1e-12):
            raise FrameError("barrier time mismatch")
        if ack.slice_id in self._pending:
            raise FrameError("duplicate slice acknowledgement")
        self._pending[ack.slice_id] = ack
        if set(self._pending) == set(self.slice_ids):
            self.released.append(self.next_step)
            self.next_step += 1
            self._pending.clear()
            return True
        return False


class CheckpointAudit:
    """Offline checkpoint lineage contract for a bounded 40-step segment."""

    def __init__(self, source_step: int = 559, source_time_s: float = 2.2075,
                 source_tick: int = 2207500000, dt_s: float = 0.00125) -> None:
        self.source_step = source_step
        self.source_time_s = source_time_s
        self.source_tick = source_tick
        self.dt_s = dt_s
        self.last_step = source_step
        self.last_bridge = 0
        self.committed: list[dict[str, int | float]] = []

    def commit(self, *, global_step: int, case_local_bridge_step: int,
               time_s: float, integer_tick: int) -> None:
        expected = self.last_step + 1
        if global_step != expected or case_local_bridge_step != self.last_bridge + 1:
            raise FrameError("checkpoint lineage is not continuous")
        expected_time = self.source_time_s + case_local_bridge_step * self.dt_s
        expected_tick = self.source_tick + case_local_bridge_step * round(self.dt_s * 1e9)
        if not isfinite(time_s) or not isclose(time_s, expected_time, rel_tol=0.0, abs_tol=1e-12) or integer_tick != expected_tick:
            raise FrameError("checkpoint time/tick mismatch")
        self.committed.append({"global_step": global_step, "case_local_bridge_step": case_local_bridge_step,
                               "time_s": time_s, "integer_tick": integer_tick})
        self.last_step = global_step
        self.last_bridge = case_local_bridge_step


class OwnershipAudit:
    def __init__(self) -> None:
        self.started: list[int] = []
        self.closed: list[int] = []

    def start(self, pid: int) -> None:
        if pid <= 0 or pid in self.started:
            raise FrameError("invalid or duplicate owned process")
        self.started.append(pid)

    def close(self, pid: int) -> None:
        if pid not in self.started or pid in self.closed:
            raise FrameError("close is not for an owned live process")
        self.closed.append(pid)

    @property
    def residual(self) -> int:
        return len(set(self.started) - set(self.closed))
