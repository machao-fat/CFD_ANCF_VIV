from __future__ import annotations

from dataclasses import dataclass, field
from .protocol import ExchangeMessage, ProtocolError


class BarrierError(ProtocolError):
    pass


@dataclass
class GlobalBarrier:
    """Require every participant to acknowledge one global step exactly once."""

    participants: frozenset[str]
    _received: dict[str, ExchangeMessage] = field(default_factory=dict)
    _last_step: int = -1
    _identity: tuple[object, ...] | None = None

    def submit(self, message: ExchangeMessage) -> bool:
        message.validate()
        if message.slice_id not in self.participants:
            raise BarrierError("unknown slice")
        if message.global_step != self._last_step + 1:
            raise BarrierError("stale, duplicate, or out-of-order global_step")
        if message.slice_id in self._received:
            raise BarrierError("duplicate slice acknowledgement")
        identity = (
            message.run_id, message.case_id, message.global_step,
            message.case_local_bridge_step, message.time_s, message.integer_tick,
        )
        if self._identity is None:
            self._identity = identity
        elif identity != self._identity:
            raise BarrierError("barrier identity/time mismatch")
        self._received[message.slice_id] = message
        return len(self._received) == len(self.participants)

    def commit(self) -> tuple[ExchangeMessage, ...]:
        if len(self._received) != len(self.participants):
            raise BarrierError("global barrier incomplete")
        values = tuple(self._received[s] for s in sorted(self._received))
        self._last_step += 1
        self._received.clear()
        self._identity = None
        return values
