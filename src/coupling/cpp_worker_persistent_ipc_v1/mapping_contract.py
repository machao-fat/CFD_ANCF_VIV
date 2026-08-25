"""Canonical source-to-target identity mapping for restart segments."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .protocol import FrameError, canonical_tick_delta


@dataclass(frozen=True)
class SourceMapping:
    """Validate global-step, bridge-step, time and integer-tick continuity."""

    source_global_step: int
    source_time_s: float
    source_tick: int
    dt_s: float
    source_bridge_step: int = 0

    def __post_init__(self) -> None:
        if (isinstance(self.source_global_step, bool) or
                not isinstance(self.source_global_step, int) or self.source_global_step < 0 or
                isinstance(self.source_bridge_step, bool) or
                not isinstance(self.source_bridge_step, int) or self.source_bridge_step < 0):
            raise FrameError("source mapping steps must be non-negative integers")
        if (isinstance(self.source_time_s, bool) or not isinstance(self.source_time_s, (int, float)) or
                not math.isfinite(float(self.source_time_s)) or float(self.source_time_s) < 0.0 or
                isinstance(self.dt_s, bool) or not isinstance(self.dt_s, (int, float)) or
                not math.isfinite(float(self.dt_s)) or float(self.dt_s) <= 0.0):
            raise FrameError("source mapping time contract is invalid")
        if (isinstance(self.source_tick, bool) or not isinstance(self.source_tick, int) or
                self.source_tick < 0 or self.source_tick > 0xFFFFFFFFFFFFFFFF):
            raise FrameError("source mapping tick is invalid")
        if self.source_tick != round(float(self.source_time_s) * 1.0e9):
            raise FrameError("source mapping tick does not match source time")
        canonical_tick_delta(float(self.dt_s))

    def target(self, *, global_step: int, case_local_bridge_step: int,
               time_s: float, integer_tick: int) -> tuple[int, int]:
        if (isinstance(global_step, bool) or not isinstance(global_step, int) or
                isinstance(case_local_bridge_step, bool) or
                not isinstance(case_local_bridge_step, int) or
                isinstance(integer_tick, bool) or not isinstance(integer_tick, int) or
                integer_tick < 0 or integer_tick > 0xFFFFFFFFFFFFFFFF or
                isinstance(time_s, bool) or not isinstance(time_s, (int, float)) or
                not math.isfinite(float(time_s))):
            raise FrameError("target mapping identity is malformed")
        if global_step <= self.source_global_step:
            raise FrameError("target global step is not an advance")
        if case_local_bridge_step <= self.source_bridge_step:
            raise FrameError("target bridge step is not an advance")
        bridge_delta = case_local_bridge_step - self.source_bridge_step
        if global_step - self.source_global_step != bridge_delta:
            raise FrameError("global step and case-local bridge step are inconsistent")
        try:
            expected_time = float(self.source_time_s) + bridge_delta * float(self.dt_s)
            tick_delta = bridge_delta * canonical_tick_delta(float(self.dt_s))
        except (OverflowError, ValueError) as exc:
            raise FrameError("target mapping exceeds numeric range") from exc
        expected_tick = self.source_tick + tick_delta
        if expected_tick > 0xFFFFFFFFFFFFFFFF:
            raise FrameError("target tick overflows the wire contract")
        if not math.isfinite(expected_time) or not math.isclose(
                float(time_s), expected_time, rel_tol=0.0, abs_tol=1.0e-12):
            raise FrameError("target time does not match source mapping")
        if integer_tick != expected_tick or integer_tick != round(float(time_s) * 1.0e9):
            raise FrameError("target tick does not match source mapping")
        return bridge_delta, expected_tick


DEFAULT_STEP559_MAPPING = SourceMapping(
    source_global_step=559,
    source_time_s=2.2075,
    source_tick=2_207_500_000,
    dt_s=0.00125,
)
