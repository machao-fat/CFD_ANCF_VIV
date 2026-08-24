"""Canonical offline mapping for staged restart bridge identities.

This module contains only identity/time validation. It does not launch or
control MATLAB, OpenFOAM, WSL, or any CFD process.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


class RestartBridgeContractError(ValueError):
    """Raised for any inconsistent restart bridge identity."""


@dataclass(frozen=True)
class RestartBridgeMapping:
    source_global_step: int
    source_time_s: float
    source_tick: int
    dt_s: float
    target_global_step: int
    target_time_s: float
    target_tick: int
    case_local_seed_step: int
    case_local_target_step: int

    @classmethod
    def from_source(cls, *, source_global_step: int, source_time_s: float,
                    source_tick: int, dt_s: float) -> "RestartBridgeMapping":
        if source_global_step < 0 or source_tick < 0 or dt_s <= 0:
            raise RestartBridgeContractError("invalid source identity or dt")
        if not math.isfinite(source_time_s) or source_time_s < 0:
            raise RestartBridgeContractError("invalid source time")
        target_step = source_global_step + 1
        target_time = source_time_s + dt_s
        target_tick = source_tick + int(round(dt_s * 1_000_000_000))
        return cls(source_global_step, source_time_s, source_tick, dt_s,
                   target_step, target_time, target_tick, 0, 1)

    def validate_seed(self, *, global_step: int, time_s: float, tick: int,
                      bridge_step: int) -> None:
        if (global_step, bridge_step) != (self.source_global_step, self.case_local_seed_step):
            raise RestartBridgeContractError("seed step identity mismatch")
        if not math.isclose(time_s, self.source_time_s, abs_tol=1e-12):
            raise RestartBridgeContractError("seed time mismatch")
        if tick != self.source_tick:
            raise RestartBridgeContractError("seed tick mismatch")

    def validate_target(self, *, global_step: int, time_s: float, tick: int,
                        bridge_step: int) -> None:
        if (global_step, bridge_step) != (self.target_global_step, self.case_local_target_step):
            raise RestartBridgeContractError("target step identity mismatch")
        if not math.isclose(time_s, self.target_time_s, abs_tol=1e-12):
            raise RestartBridgeContractError("target time mismatch")
        if tick != self.target_tick:
            raise RestartBridgeContractError("target tick mismatch")

    def validate_ack(self, *, bridge_step: int, time_s: float, tick: int,
                     global_step: int, consumed: bool) -> None:
        if not consumed:
            raise RestartBridgeContractError("ack is not consumed")
        self.validate_target(global_step=global_step, time_s=time_s,
                             tick=tick, bridge_step=bridge_step)

    def reject_stale(self, *, bridge_step: int, time_s: float, tick: int,
                     global_step: int) -> None:
        self.validate_target(global_step=global_step, time_s=time_s,
                             tick=tick, bridge_step=bridge_step)

