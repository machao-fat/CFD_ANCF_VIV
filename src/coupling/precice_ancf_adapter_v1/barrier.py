from __future__ import annotations

from dataclasses import dataclass, field

from .mapping import BridgeClock
from .protocol import Envelope, ProtocolError


class BarrierError(ProtocolError):
    pass


@dataclass
class ThreeSliceBarrier:
    run_id: str
    case_id: str
    clock: BridgeClock
    slices: frozenset[str] = frozenset({"slice_0000", "slice_0001", "slice_0002"})
    _pending: dict[str, Envelope] = field(default_factory=dict)
    _next_global_step: int = -1
    committed_steps: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._next_global_step = self.clock.global_origin

    def submit(self, message: Envelope) -> bool:
        message.validate({"run_id": self.run_id, "case_id": self.case_id})
        if message.slice_id not in self.slices:
            raise BarrierError("unknown slice_id")
        if message.kind != "force_ack" or message.ack != "consumed":
            raise BarrierError("barrier requires consumed force_ack")
        if message.global_step != self._next_global_step:
            raise BarrierError("stale, duplicate, or out-of-order global_step")
        expected = self.clock.identity(message.global_step)
        if (message.global_step, message.case_local_bridge_step, message.time_s, message.integer_tick) != expected:
            raise BarrierError("canonical clock mismatch")
        if message.sequence != message.global_step - self.clock.global_origin + 1:
            raise BarrierError("stale, duplicate, or out-of-order sequence")
        if message.slice_id in self._pending:
            raise BarrierError("duplicate slice acknowledgement")
        self._pending[message.slice_id] = message
        return len(self._pending) == len(self.slices)

    def commit(self) -> tuple[Envelope, ...]:
        if len(self._pending) != len(self.slices):
            raise BarrierError("global barrier incomplete")
        result = tuple(self._pending[sid] for sid in sorted(self.slices))
        self.committed_steps.append(self._next_global_step)
        self._next_global_step += 1
        self._pending.clear()
        return result

    def fail_closed(self, classification: str) -> None:
        """Represent timeout/disconnect as a terminal barrier fault."""
        if classification not in {"timeout", "disconnect", "identity", "protocol"}:
            raise BarrierError("unknown transport fault")
        self._pending.clear()
        raise BarrierError(f"fail-closed: {classification}")
