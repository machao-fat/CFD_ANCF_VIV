from __future__ import annotations

from dataclasses import dataclass
import math

from coupling.cpp_worker_persistent_ipc_v1.protocol import FrameError


@dataclass(frozen=True)
class SourceMapping:
    """Canonical source-to-target mapping for an isolated restart segment."""

    source_global_step: int
    source_time_s: float
    source_tick: int
    dt_s: float
    source_bridge_step: int = 0

    def __post_init__(self) -> None:
        if self.source_global_step < 0 or self.source_bridge_step < 0:
            raise FrameError("source mapping steps must be non-negative")
        if not math.isfinite(self.source_time_s) or not math.isfinite(self.dt_s) or self.dt_s <= 0.0:
            raise FrameError("source mapping time contract is invalid")
        if self.source_tick < 0:
            raise FrameError("source mapping tick must be non-negative")
        expected_tick = round(self.source_time_s * 1.0e9)
        if self.source_tick != expected_tick:
            raise FrameError("source mapping tick does not match source time")

    def target(self, *, global_step: int, case_local_bridge_step: int,
               time_s: float, integer_tick: int) -> None:
        if global_step <= self.source_global_step:
            raise FrameError("target global step is not an advance")
        if case_local_bridge_step <= self.source_bridge_step:
            raise FrameError("target bridge step is not an advance")
        bridge_delta = case_local_bridge_step - self.source_bridge_step
        if global_step - self.source_global_step != bridge_delta:
            raise FrameError("global step and case-local bridge step are inconsistent")
        expected_time = self.source_time_s + bridge_delta * self.dt_s
        expected_tick = self.source_tick + round(bridge_delta * self.dt_s * 1.0e9)
        if not math.isfinite(time_s) or not math.isclose(time_s, expected_time, rel_tol=0.0, abs_tol=1.0e-12):
            raise FrameError("target time does not match source mapping")
        if integer_tick != expected_tick or integer_tick != round(time_s * 1.0e9):
            raise FrameError("target tick does not match source mapping")


DEFAULT_STEP559_MAPPING = SourceMapping(
    source_global_step=559,
    source_time_s=2.2075,
    source_tick=2207500000,
    dt_s=0.00125,
)
