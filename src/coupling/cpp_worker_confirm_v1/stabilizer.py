"""Stage-local time-consistent load filtering for the C++ confirm path."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Sequence

TICK_HZ = 1_000_000_000
TAU_DECIMAL = "0.023728053952574758"
TAU_S = float(TAU_DECIMAL)
STATE_SCHEMA = "0.2.1+stabilizer.time-consistent.1"
ALGORITHM = "first_order_load_under_relaxation"
RAW_CD_LIMIT = 10.0
APPLIED_CD_LIMIT = 10.0


class StabilizerError(RuntimeError):
    """Fail-closed load-stabilizer violation."""


def _finite_matrix(values: Sequence[Sequence[float]], name: str) -> tuple[tuple[float, ...], ...]:
    rows = tuple(tuple(float(item) for item in row) for row in values)
    if len(rows) != 3 or any(len(row) != 3 for row in rows):
        raise StabilizerError(f"{name} must be a 3x3 matrix")
    if any(not math.isfinite(item) for row in rows for item in row):
        raise StabilizerError(f"{name} contains NaN/Inf")
    return rows


class CausalTimeConsistentLoadStabilizer:
    """Apply the accepted exponential physical-time load contract."""

    def __init__(self, *, previous_applied_force_N: Sequence[Sequence[float]],
                 source_step: int, source_tick: int, run_id: str, case_id: str,
                 scales_N: Sequence[float]) -> None:
        self._previous = _finite_matrix(previous_applied_force_N, "previous_applied_force_N")
        self._last_step = int(source_step)
        self._last_tick = int(source_tick)
        self.run_id, self.case_id = str(run_id), str(case_id)
        self.scales = tuple(float(value) for value in scales_N)
        if len(self.scales) != 3 or any(not math.isfinite(v) or v <= 0.0 for v in self.scales):
            raise StabilizerError("stabilizer scales are invalid")
        if self._last_tick < 0:
            raise StabilizerError("source tick is invalid")
        self._pending: dict[str, Any] | None = None

    @property
    def config_sha256(self) -> str:
        encoded = json.dumps({"algorithm": ALGORITHM, "scales": self.scales,
                              "tau_decimal": TAU_DECIMAL, "tick_hz": TICK_HZ},
                             sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def apply(self, *, step: int, time_s: float, integer_tick: int,
              raw_force_N: Sequence[Sequence[float]]) -> tuple[tuple[tuple[float, ...], ...], dict[str, Any]]:
        if self._pending is not None:
            raise StabilizerError("previous stabilizer step is not committed")
        step, tick = int(step), int(integer_tick)
        if step != self._last_step + 1:
            raise StabilizerError("stabilizer step is not contiguous")
        if not math.isfinite(float(time_s)) or abs(float(time_s) - tick / TICK_HZ) > 5e-13:
            raise StabilizerError("stabilizer time/tick mismatch")
        if tick <= self._last_tick:
            raise StabilizerError("stabilizer tick is stale or out of order")
        raw = _finite_matrix(raw_force_N, "raw_force_N")
        dt_s = (tick - self._last_tick) / TICK_HZ
        if not math.isfinite(dt_s) or dt_s <= 0.0:
            raise StabilizerError("stabilizer elapsed dt is invalid")
        alpha = -math.expm1(-dt_s / TAU_S)
        applied_rows: list[tuple[float, ...]] = []
        for sid, (raw_row, old_row) in enumerate(zip(raw, self._previous)):
            if abs(raw_row[0] / self.scales[sid]) > RAW_CD_LIMIT:
                raise StabilizerError(f"raw Cd hard gate failed at slice {sid}")
            value = tuple((1.0 - alpha) * old + alpha * current
                          for old, current in zip(old_row, raw_row))
            if any(not math.isfinite(item) for item in value):
                raise StabilizerError("applied force contains NaN/Inf")
            if abs(value[0] / self.scales[sid]) > APPLIED_CD_LIMIT:
                raise StabilizerError(f"applied Cd hard gate failed at slice {sid}")
            applied_rows.append(value)
        applied = tuple(applied_rows)
        state = {
            "schema": STATE_SCHEMA, "algorithm": ALGORITHM, "version": "1.0.0",
            "config_sha256": self.config_sha256, "tau_decimal": TAU_DECIMAL,
            "run_id": self.run_id, "case_id": self.case_id, "last_step": step,
            "last_time_tick": tick, "elapsed_dt_s": dt_s, "alpha_dt": alpha,
            "previous_applied_force_N": [list(row) for row in applied],
        }
        self._pending = {"step": step, "tick": tick, "raw": raw, "applied": applied}
        audit = dict(state)
        audit.update({"time_s": float(time_s), "raw_force_N": [list(row) for row in raw],
                      "applied_force_N": [list(row) for row in applied],
                      "raw_force_immutable": True})
        return applied, audit

    def commit(self) -> None:
        if self._pending is None:
            raise StabilizerError("no pending stabilizer step")
        self._previous = self._pending["applied"]
        self._last_step = int(self._pending["step"])
        self._last_tick = int(self._pending["tick"])
        self._pending = None

    def rollback(self) -> None:
        self._pending = None

    def state(self) -> dict[str, Any]:
        return {
            "schema": STATE_SCHEMA, "algorithm": ALGORITHM, "version": "1.0.0",
            "config_sha256": self.config_sha256, "tau_decimal": TAU_DECIMAL,
            "run_id": self.run_id, "case_id": self.case_id, "last_step": self._last_step,
            "last_time_tick": self._last_tick,
            "previous_applied_force_N": [list(row) for row in self._previous],
        }


__all__ = ["ALGORITHM", "APPLIED_CD_LIMIT", "CausalTimeConsistentLoadStabilizer",
           "RAW_CD_LIMIT", "STATE_SCHEMA", "StabilizerError", "TAU_DECIMAL", "TAU_S"]
