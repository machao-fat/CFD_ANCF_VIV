from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


PHASES = ("matlab_initialize", "matlab_prediction", "matlab_correction", "wsl_start", "openfoam_start",
          "openfoam_solve", "motion_publish", "motion_ack_load", "force_parse", "checkpoint_audit", "snapshot_audit")


@dataclass
class StepTrace:
    run_id: str
    case_id: str
    global_step: int
    case_local_bridge_step: int
    time_s: float
    integer_tick: int
    request_id: str
    transaction_id: str
    step_start_ns: int
    step_end_ns: int
    phases_ns: dict[str, tuple[int, int]] = field(default_factory=dict)
    slice_events: list[dict[str, Any]] = field(default_factory=list)
    process_audits: list[dict[str, Any]] = field(default_factory=list)
    cleanup_result: str = "pending"
    owned_residual: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["phase_durations_s"] = {name: (end - start) / 1e9 for name, (start, end) in self.phases_ns.items()}
        data["step_total_s"] = (self.step_end_ns - self.step_start_ns) / 1e9
        for phase in PHASES:
            start, end = self.phases_ns.get(phase, (None, None))
            data[f"{phase}_start_ns"] = start
            data[f"{phase}_end_ns"] = end
        return data


class TraceRecorder:
    def __init__(self) -> None:
        self.traces: list[StepTrace] = []

    def record(self, *, run_id: str, case_id: str, global_step: int, case_local_bridge_step: int,
               time_s: float, integer_tick: int, request_id: str, transaction_id: str,
               phases_ns: dict[str, tuple[int, int]] | None = None,
               slice_events: list[dict[str, Any]] | None = None,
               process_audits: list[dict[str, Any]] | None = None,
               cleanup_result: str = "closed", owned_residual: int = 0) -> StepTrace:
        start = time.time_ns()
        phase_data = phases_ns or {}
        end = max([end for _, end in phase_data.values()] + [start])
        trace = StepTrace(run_id, case_id, int(global_step), int(case_local_bridge_step), float(time_s), int(integer_tick),
                          request_id, transaction_id, start, end, phase_data, slice_events or [], process_audits or [],
                          cleanup_result, int(owned_residual))
        self.traces.append(trace)
        return trace


def _stats(values: Iterable[float]) -> dict[str, float]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"average": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    def percentile(q: float) -> float:
        index = (len(ordered) - 1) * q
        lo, hi = int(index), min(int(index) + 1, len(ordered) - 1)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)
    return {"average": statistics.fmean(ordered), "p50": percentile(.5), "p95": percentile(.95), "max": max(ordered)}


def summarize_traces(traces: Iterable[StepTrace]) -> dict[str, Any]:
    items = list(traces)
    totals = [item.to_dict()["step_total_s"] for item in items]
    phase_values: dict[str, list[float]] = {}
    for item in items:
        for name, value in item.to_dict()["phase_durations_s"].items():
            phase_values.setdefault(name, []).append(value)
    return {"steps": len(items), "per_step_s": _stats(totals), "phase_s": {name: _stats(values) for name, values in phase_values.items()},
            "segment_wall_clock_s": sum(totals), "owned_residual_max": max((item.owned_residual for item in items), default=0),
            "external_process_starts": 0}
