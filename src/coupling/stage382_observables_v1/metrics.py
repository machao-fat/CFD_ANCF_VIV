from __future__ import annotations

import math
import statistics
from typing import Sequence


class ObservationContractError(ValueError):
    pass


REQUIRED_CONTRACT_FIELDS = {
    "schema_version", "run_id", "case_id", "slice_ids", "sample_interval_s",
    "window_interval_s", "force_fields", "displacement_fields", "missing_value_policy",
    "formal_gate_unchanged",
}


def validate_contract(contract: dict[str, object]) -> dict[str, object]:
    checks = {
        "required_fields": REQUIRED_CONTRACT_FIELDS.issubset(contract),
        "schema_version": contract.get("schema_version") == 1,
        "three_slices": isinstance(contract.get("slice_ids"), list) and len(contract["slice_ids"]) == 3 and len(set(contract["slice_ids"])) == 3,
        "sample_interval": contract.get("sample_interval_s") == 0.05,
        "window_interval": contract.get("window_interval_s") in (10.0, 20.0),
        "no_interpolation": contract.get("missing_value_policy") == "fail_closed_no_interpolation",
        "formal_gate_unchanged": contract.get("formal_gate_unchanged") is True,
    }
    if not all(checks.values()):
        raise ObservationContractError("invalid observation contract: " + repr(checks))
    return {"checks": checks, "status": "pass"}


def _finite(values: Sequence[float], name: str) -> None:
    if not values or any(not math.isfinite(float(value)) for value in values):
        raise ObservationContractError(f"{name} is empty or non-finite")


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ObservationContractError("correlation input mismatch")
    _finite(left, "left")
    _finite(right, "right")
    mean_left, mean_right = statistics.fmean(left), statistics.fmean(right)
    a = [float(value) - mean_left for value in left]
    b = [float(value) - mean_right for value in right]
    denom = math.sqrt(sum(value * value for value in a) * sum(value * value for value in b))
    if denom == 0.0:
        raise ObservationContractError("zero-variance correlation input")
    return sum(x * y for x, y in zip(a, b)) / denom


def _lag(left: Sequence[float], right: Sequence[float], max_lag: int) -> tuple[int, float]:
    best_lag, best_corr = 0, -2.0
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            a, b = left[-lag:], right[:lag]
        elif lag > 0:
            a, b = left[:-lag], right[lag:]
        else:
            a, b = left, right
        if len(a) >= 2:
            corr = _correlation(a, b)
            if corr > best_corr:
                best_lag, best_corr = lag, corr
    if best_corr < -1.0:
        raise ObservationContractError("unable to determine phase lag")
    return best_lag, best_corr


def compute_window_metrics(
    times: Sequence[float],
    forces_by_slice: dict[str, Sequence[float]],
    displacement: Sequence[float],
    *,
    start_time_s: float,
    end_time_s: float,
    sample_interval_s: float = 0.05,
) -> dict[str, object]:
    if set(forces_by_slice) != {"slice_0000", "slice_0001", "slice_0002"}:
        raise ObservationContractError("slice identity mismatch")
    if len(times) != len(displacement) or any(len(values) != len(times) for values in forces_by_slice.values()):
        raise ObservationContractError("observable stream lengths mismatch")
    selected = [index for index, time_s in enumerate(times) if start_time_s <= float(time_s) < end_time_s]
    if len(selected) < 2:
        raise ObservationContractError("window has insufficient samples")
    window_times = [float(times[index]) for index in selected]
    if any(right <= left for left, right in zip(window_times, window_times[1:])):
        raise ObservationContractError("time stream is not increasing")
    forces = {sid: [float(values[index]) for index in selected] for sid, values in forces_by_slice.items()}
    disp = [float(displacement[index]) for index in selected]
    for sid, values in forces.items():
        _finite(values, sid)
    _finite(disp, "displacement")
    weights = {sid: 1.0 / 3.0 for sid in forces}
    weighted = [sum(weights[sid] * forces[sid][index] for sid in forces) for index in range(len(selected))]
    phase = {}
    ids = tuple(forces)
    max_lag = max(1, min(len(selected) // 4, round(2.0 / sample_interval_s)))
    for left_index, left_sid in enumerate(ids):
        for right_sid in ids[left_index + 1:]:
            lag, corr = _lag(forces[left_sid], forces[right_sid], max_lag)
            phase[f"{left_sid}__{right_sid}"] = {"lag_samples": lag, "lag_time_s": lag * sample_interval_s, "correlation": corr}
    def summary(values: Sequence[float]) -> dict[str, float]:
        return {"mean": statistics.fmean(values), "rms": math.sqrt(statistics.fmean(value * value for value in values)), "peak_to_peak": max(values) - min(values)}
    return {
        "start_time_s": start_time_s,
        "end_time_s": min(end_time_s, max(window_times)),
        "sample_count": len(selected),
        "force_by_slice": {sid: summary(values) for sid, values in forces.items()},
        "weighted_force": summary(weighted),
        "displacement_y": summary(disp),
        "phase": phase,
    }
