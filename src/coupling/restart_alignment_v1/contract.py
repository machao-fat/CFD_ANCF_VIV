from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Sequence


class RestartAlignmentError(ValueError):
    """Raised when a restart state is not explicitly aligned to saved fields."""


def _finite(values: Sequence[float], name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result or any(not math.isfinite(value) for value in result):
        raise RestartAlignmentError(f"{name} is empty or non-finite")
    return result


@dataclass(frozen=True)
class RestartBootstrap:
    """A state intentionally lagged from a final state for field bootstrap."""

    source_global_step: int
    field_time_s: float
    state_time_s: float
    lag_steps: int
    dt_s: float
    q: tuple[float, ...]
    qdot: tuple[float, ...]
    qddot: tuple[float, ...]
    direct_final_q_rejected: bool = True

    @property
    def q_sha256(self) -> str:
        import struct
        return hashlib.sha256(struct.pack("<" + "d" * len(self.q), *self.q)).hexdigest()

    def validate(self) -> None:
        if self.source_global_step < 1 or self.lag_steps < 1 or self.dt_s <= 0.0:
            raise RestartAlignmentError("invalid restart identity or lag contract")
        if not all(math.isfinite(value) for value in (self.field_time_s, self.state_time_s, self.dt_s)):
            raise RestartAlignmentError("restart times are non-finite")
        expected = self.field_time_s - self.lag_steps * self.dt_s
        if abs(self.state_time_s - expected) > 1.0e-12:
            raise RestartAlignmentError("state_time does not match field_time and lag_steps")
        if not self.direct_final_q_rejected:
            raise RestartAlignmentError("direct final_q use must be rejected")
        _finite(self.q, "q")
        _finite(self.qdot, "qdot")
        _finite(self.qddot, "qddot")
        if not len(self.q) == len(self.qdot) == len(self.qddot):
            raise RestartAlignmentError("restart state dimensions differ")


def build_bootstrap(
    *,
    source_global_step: int,
    field_time_s: float,
    final_q: Sequence[float],
    final_qdot: Sequence[float],
    final_qddot: Sequence[float],
    dt_s: float,
    lag_steps: int = 2,
) -> RestartBootstrap:
    """Build a provisional lagged state; caller must still run a fresh smoke."""
    q = _finite(final_q, "final_q")
    qdot = _finite(final_qdot, "final_qdot")
    qddot = _finite(final_qddot, "final_qddot")
    if len(q) != len(qdot) or len(q) != len(qddot):
        raise RestartAlignmentError("final state dimensions differ")
    if lag_steps < 1 or not math.isfinite(float(dt_s)) or dt_s <= 0.0:
        raise RestartAlignmentError("invalid lag_steps or dt_s")
    horizon = float(lag_steps) * float(dt_s)
    lag_q = tuple(a - horizon * b + 0.5 * horizon * horizon * c for a, b, c in zip(q, qdot, qddot))
    lag_qdot = tuple(b - horizon * c for b, c in zip(qdot, qddot))
    bootstrap = RestartBootstrap(
        source_global_step=int(source_global_step), field_time_s=float(field_time_s),
        state_time_s=float(field_time_s) - horizon, lag_steps=int(lag_steps), dt_s=float(dt_s),
        q=lag_q, qdot=lag_qdot, qddot=qddot,
    )
    bootstrap.validate()
    return bootstrap
