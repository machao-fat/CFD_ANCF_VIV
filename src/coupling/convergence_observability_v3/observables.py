"""Fail-closed, dependency-free convergence observations.

This module is deliberately independent of the solver and never fills missing
samples.  It is suitable for offline audits and synthetic fault injection.
"""
from __future__ import annotations

import math
import statistics
from typing import Iterable, Sequence


class AuditError(ValueError):
    """Raised when an evidence stream cannot be trusted."""


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def relative_drift(values: Iterable[float]) -> float | None:
    values = [float(value) for value in values]
    if not values:
        return None
    if any(not math.isfinite(value) for value in values):
        raise AuditError("non-finite drift input")
    scale = max(abs(statistics.median(values)), 1.0e-30)
    return (max(values) - min(values)) / scale


def _moving_average(values: Sequence[float], span: int) -> list[float]:
    if span < 1 or span > len(values):
        raise AuditError("invalid smoothing span")
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + float(value))
    half = span // 2
    result = [float(value) for value in values]
    for index in range(half, len(values) - (span - half - 1)):
        result[index] = (prefix[index + span - half] - prefix[index - half]) / span
    return result


def positive_peaks(
    times: Sequence[float],
    values: Sequence[float],
    *,
    smoothing_s: float = 0.0,
    minimum_separation_s: float = 4.0,
) -> list[dict[str, float]]:
    """Return only interior positive maxima, with deterministic spacing.

    Boundary points, negative maxima, non-finite values, and undersampled time
    streams are rejected rather than guessed.
    """
    if len(times) != len(values) or len(times) < 3:
        raise AuditError("time/value lengths are not auditable")
    if any(not _finite(value) for value in times + values):
        raise AuditError("non-finite peak input")
    deltas = [float(right) - float(left) for left, right in zip(times, times[1:])]
    if any(delta <= 0.0 for delta in deltas):
        raise AuditError("time stream is not strictly increasing")
    dt = statistics.median(deltas)
    span = max(1, int(round(float(smoothing_s) / dt)))
    smooth = _moving_average(values, span)
    margin = max(1, span)
    peaks: list[dict[str, float]] = []
    for index in range(margin, len(smooth) - margin):
        value = smooth[index]
        if value <= 0.0 or value < smooth[index - 1] or value <= smooth[index + 1]:
            continue
        candidate = {"time_s": float(times[index]), "value": float(value)}
        if peaks and candidate["time_s"] - peaks[-1]["time_s"] < minimum_separation_s:
            if candidate["value"] > peaks[-1]["value"]:
                peaks[-1] = candidate
        else:
            peaks.append(candidate)
    return peaks


def summarize_windows(
    times: Sequence[float],
    values: Sequence[float],
    windows: Sequence[tuple[float, float]],
    peaks: Sequence[dict[str, float]] = (),
) -> list[dict[str, object]]:
    if len(times) != len(values) or not times:
        raise AuditError("empty or mismatched window input")
    result: list[dict[str, object]] = []
    for start, stop in windows:
        selected = [float(value) for time_s, value in zip(times, values) if start <= time_s < stop]
        if not selected or any(not math.isfinite(value) for value in selected):
            raise AuditError(f"window has no finite samples: {start}:{stop}")
        selected_peaks = [peak for peak in peaks if start <= peak["time_s"] < stop]
        periods = [right["time_s"] - left["time_s"] for left, right in zip(selected_peaks, selected_peaks[1:])]
        result.append({
            "start_time_s": start,
            "end_time_s": min(stop, max(times)),
            "sample_count": len(selected),
            "mean": statistics.fmean(selected),
            "rms": math.sqrt(statistics.fmean(value * value for value in selected)),
            "peak_to_peak": max(selected) - min(selected),
            "peak_count": len(selected_peaks),
            "frequency_hz": 1.0 / statistics.fmean(periods) if periods else None,
        })
    return result


def audit_identity_rows(
    rows: Sequence[dict[str, object]],
    *,
    source_global_step: int,
    source_local_step: int = 0,
    slice_ids: Sequence[str] = ("slice_0000", "slice_0001", "slice_0002"),
    dt_s: float,
) -> dict[str, object]:
    checks = {
        "record_count": bool(rows),
        "continuous_global_step": True,
        "continuous_local_step": True,
        "time_tick_identity": True,
        "slice_identity": True,
        "no_duplicate_step": True,
    }
    seen: set[int] = set()
    for index, row in enumerate(rows, start=1):
        global_step = row.get("global_step")
        local_step = row.get("case_local_bridge_step")
        time_s = row.get("time_s")
        tick = row.get("integer_tick")
        checks["continuous_global_step"] &= global_step == source_global_step + index
        checks["continuous_local_step"] &= local_step == source_local_step + index
        checks["time_tick_identity"] &= _finite(time_s) and tick == int(round(float(time_s) * 1.0e9))
        checks["no_duplicate_step"] &= isinstance(global_step, int) and global_step not in seen
        if isinstance(global_step, int):
            seen.add(global_step)
        positions = row.get("interface_positions_xy")
        checks["slice_identity"] &= isinstance(positions, list) and len(positions) == len(slice_ids)
    return {"checks": checks, "status": "pass" if all(checks.values()) else "do_not_pass"}


def audit_quality_records(
    records: Sequence[dict[str, object]],
    *,
    expected_times: Sequence[float],
    courant_limit: float | None = None,
) -> dict[str, object]:
    """Require one finite, time-aligned quality record per expected sample."""
    checks = {
        "record_count": len(records) == len(expected_times),
        "time_alignment": len(records) == len(expected_times),
        "required_fields": True,
        "finite": True,
        "courant_limit": True,
    }
    for record, expected in zip(records, expected_times):
        checks["time_alignment"] &= _finite(record.get("time_s")) and abs(float(record["time_s"]) - expected) <= 1.0e-9
        required = ("time_s", "courant_max", "residual_max", "continuity_global", "iterations_max")
        checks["required_fields"] &= all(field in record for field in required)
        if all(field in record for field in required):
            checks["finite"] &= all(_finite(record[field]) for field in required)
            if courant_limit is not None:
                checks["courant_limit"] &= float(record["courant_max"]) <= courant_limit
    return {"checks": checks, "status": "pass" if all(checks.values()) else "do_not_pass"}


def validate_observability_contract(contract: dict[str, object]) -> dict[str, object]:
    """Validate the evidence requirements before a future short-window run."""
    checks = {
        "schema_version": contract.get("schema_version") == 1,
        "identity_fields": set(contract.get("identity_fields", ())) >= {
            "run_id", "case_id", "slice_id", "global_step", "case_local_bridge_step",
            "time_s", "integer_tick", "request_id", "transaction_id",
        },
        "quality_fields": set(contract.get("quality_fields", ())) >= {
            "time_s", "courant_max", "residual_max", "continuity_global", "iterations_max",
        },
        "slice_ids": isinstance(contract.get("slice_ids"), list)
        and len(contract["slice_ids"]) == 3
        and len(set(contract["slice_ids"])) == 3,
        "terminal_quality_required": contract.get("terminal_quality_required") is True,
        "no_interpolation": contract.get("missing_value_policy") == "fail_closed_no_interpolation",
        "finite_required": contract.get("finite_required") is True,
        "real_process_guard": contract.get("real_process_allowed") is False,
        "formal_status_preserved": contract.get("preserve_formal_status") is True,
    }
    return {"checks": checks, "status": "pass" if all(checks.values()) else "do_not_pass"}
