from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


class TelemetryError(ValueError):
    """Invalid real benchmark telemetry; caller must fail closed."""


REQUIRED_PHASES = ("matlab", "wsl", "openfoam", "ipc", "checkpoint_audit", "total")


@dataclass(frozen=True)
class StepTiming:
    run_id: str
    case_id: str
    global_step: int
    case_local_bridge_step: int
    time_s: float
    integer_tick: int
    request_id: str
    transaction_id: str
    phases_s: Mapping[str, float]
    matlab_pid: int | None = None
    openfoam_pids: Mapping[str, int] = field(default_factory=dict)
    wsl_pids: Mapping[str, int] = field(default_factory=dict)
    return_codes: Mapping[str, int] = field(default_factory=dict)
    owned_residual: int = 0

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StepTiming":
        required = {"run_id", "case_id", "global_step", "case_local_bridge_step", "time_s", "integer_tick",
                    "request_id", "transaction_id", "phases_s"}
        missing = required - value.keys()
        if missing: raise TelemetryError("missing timing fields: " + ",".join(sorted(missing)))
        phases = dict(value["phases_s"])
        if any(key not in phases for key in REQUIRED_PHASES):
            raise TelemetryError("phase timing missing")
        if any(not math.isfinite(float(item)) or float(item) < 0 for item in phases.values()):
            raise TelemetryError("phase timing is non-finite or negative")
        if int(value["global_step"]) < 0 or int(value["case_local_bridge_step"]) < 0 or int(value["integer_tick"]) < 0:
            raise TelemetryError("negative timing identity")
        if int(value.get("owned_residual", 0)) != 0:
            raise TelemetryError("owned residual is nonzero")
        if any(int(item) != 0 for item in value.get("return_codes", {}).values()):
            raise TelemetryError("nonzero process return code")
        return cls(str(value["run_id"]), str(value["case_id"]), int(value["global_step"]),
                   int(value["case_local_bridge_step"]), float(value["time_s"]), int(value["integer_tick"]),
                   str(value["request_id"]), str(value["transaction_id"]), phases,
                   value.get("matlab_pid"), value.get("openfoam_pids", {}), value.get("wsl_pids", {}),
                   value.get("return_codes", {}), int(value.get("owned_residual", 0)))


def summarize_timings(records: list[StepTiming]) -> dict[str, Any]:
    if not records: raise TelemetryError("empty timing trace")
    ordered = sorted(records, key=lambda item: item.global_step)
    identity = (ordered[0].run_id, ordered[0].case_id)
    if any((item.run_id, item.case_id) != identity for item in ordered): raise TelemetryError("trace identity mismatch")
    if any(item.global_step != ordered[0].global_step + index for index, item in enumerate(ordered)):
        raise TelemetryError("trace has missing or duplicate steps")
    for previous, current in zip(ordered, ordered[1:]):
        if current.case_local_bridge_step != previous.case_local_bridge_step + 1:
            raise TelemetryError("bridge step is not contiguous")
        if current.integer_tick <= previous.integer_tick or current.time_s <= previous.time_s:
            raise TelemetryError("time/tick is not strictly increasing")
    def stats(values: list[float]) -> dict[str, float]:
        ordered_values = sorted(values); n = len(ordered_values)
        return {"average": statistics.fmean(values), "p50": ordered_values[(n - 1) * 50 // 100],
                "p95": ordered_values[(n - 1) * 95 // 100], "max": max(values)}
    return {"run_id": identity[0], "case_id": identity[1], "steps": len(ordered),
            "step_total_s": stats([item.phases_s["total"] for item in ordered]),
            "phase_s": {phase: stats([item.phases_s[phase] for item in ordered]) for phase in REQUIRED_PHASES},
            "matlab_start_count": len({item.matlab_pid for item in ordered if item.matlab_pid is not None}),
            "openfoam_start_count": len({pid for item in ordered for pid in item.openfoam_pids.values()}),
            "wsl_start_count": len({pid for item in ordered for pid in item.wsl_pids.values()}),
            "owned_residual": max(item.owned_residual for item in ordered)}


def validate_source_mapping(records: list[StepTiming], *, source_global_step: int,
                            source_time_s: float, source_tick: int, dt_s: float) -> None:
    """Validate absolute/global and case-local identities against the source."""
    if not records:
        raise TelemetryError("empty source mapping trace")
    for item in records:
        bridge = item.global_step - int(source_global_step)
        if bridge <= 0 or item.case_local_bridge_step != bridge:
            raise TelemetryError("global/case-local bridge mapping mismatch")
        expected_time = float(source_time_s) + bridge * float(dt_s)
        expected_tick = int(source_tick) + int(round(bridge * float(dt_s) * 1_000_000_000))
        if not math.isclose(item.time_s, expected_time, rel_tol=0.0, abs_tol=1e-12):
            raise TelemetryError("source/target time mapping mismatch")
        if item.integer_tick != expected_tick:
            raise TelemetryError("source/target tick mapping mismatch")
