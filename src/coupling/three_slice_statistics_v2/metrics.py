"""Statistics for three-slice VIV evidence without changing legacy Gates.

The module deliberately distinguishes a physical integrated force from a
normalized arithmetic average.  The latter is useful for phase-cancellation
diagnostics but is not an admissible physical total unless tributary measures
are declared by the run contract.
"""
from __future__ import annotations

import math
import statistics
from itertools import combinations
from typing import Mapping, Sequence


SLICE_IDS = ("slice_0000", "slice_0001", "slice_0002")


class StatisticalContractError(ValueError):
    """Raised when evidence cannot support a declared statistical conclusion."""


def _finite(value: object) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise StatisticalContractError("non-numeric evidence value") from exc
    if not math.isfinite(value):
        raise StatisticalContractError("non-finite evidence value")
    return value


def _relative_drift(values: Sequence[float]) -> float | None:
    if not values:
        return None
    checked = [_finite(value) for value in values]
    scale = max(abs(statistics.median(checked)), 1.0e-30)
    return (max(checked) - min(checked)) / scale


def _circular_span_deg(values: Sequence[float]) -> float | None:
    """Smallest arc containing phase values represented on [-180, 180)."""
    if not values:
        return None
    angles = sorted((_finite(value) % 360.0) for value in values)
    if len(angles) == 1:
        return 0.0
    gaps = [right - left for left, right in zip(angles, angles[1:])]
    gaps.append(angles[0] + 360.0 - angles[-1])
    return 360.0 - max(gaps)


def validate_contract(contract: Mapping[str, object]) -> dict[str, object]:
    """Validate the V2 statistical contract before a new or offline audit."""
    checks = {
        "schema_version": contract.get("schema_version") == 2,
        "slice_ids": tuple(contract.get("slice_ids", ())) == SLICE_IDS,
        "primary_observables": set(contract.get("primary_observables", ())) >= {
            "per_slice_force_y", "structure_displacement_y", "phase_relation",
        },
        "demeaned_rms": contract.get("amplitude_definition") == "demeaned_rms_and_peak_to_peak",
        "frequency_method": set(contract.get("frequency_methods", ())) >= {"detrended_fft", "prominent_positive_peaks"},
        "physical_total_policy": contract.get("physical_total_force_policy")
        in {"requires_declared_tributary_measure", "not_evaluable_from_legacy_evidence"},
        "quality_separate": contract.get("quality_gate_separate") is True,
        "legacy_immutable": contract.get("legacy_gate_unchanged") is True,
        "no_interpolation": contract.get("missing_value_policy") == "fail_closed_no_interpolation",
        "offline_only": contract.get("real_process_allowed") is False,
    }
    return {"checks": checks, "status": "pass" if all(checks.values()) else "do_not_pass"}


def demeaned_rms(values: Sequence[float]) -> float:
    checked = [_finite(value) for value in values]
    if len(checked) < 2:
        raise StatisticalContractError("at least two samples are required")
    mean = statistics.fmean(checked)
    return math.sqrt(statistics.fmean((value - mean) ** 2 for value in checked))


def _validate_signal(times: Sequence[float], values: Sequence[float]) -> tuple[list[float], list[float], float]:
    if len(times) != len(values) or len(times) < 4:
        raise StatisticalContractError("time and value streams are incomplete")
    checked_times = [_finite(value) for value in times]
    checked_values = [_finite(value) for value in values]
    deltas = [right - left for left, right in zip(checked_times, checked_times[1:])]
    if any(delta <= 0.0 for delta in deltas):
        raise StatisticalContractError("time evidence is stale, duplicate, or out of order")
    dt = statistics.median(deltas)
    if any(abs(delta - dt) > max(1.0e-9, abs(dt) * 1.0e-6) for delta in deltas):
        raise StatisticalContractError("time evidence is not uniformly sampled")
    return checked_times, checked_values, dt


def detrended_fft_frequency(times: Sequence[float], values: Sequence[float]) -> float | None:
    """Return the non-zero FFT maximum after removing a linear trend."""
    checked_times, checked_values, dt = _validate_signal(times, values)
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return None
    indices = np.arange(len(checked_values), dtype=float)
    signal = np.asarray(checked_values, dtype=float)
    trend = np.polyval(np.polyfit(indices, signal, 1), indices)
    spectrum = np.abs(np.fft.rfft(signal - trend))
    if len(spectrum) < 2:
        return None
    index = int(np.argmax(spectrum[1:]) + 1)
    return float(np.fft.rfftfreq(len(signal), d=dt)[index])


def prominent_positive_peaks(
    times: Sequence[float],
    values: Sequence[float],
    *,
    minimum_separation_s: float,
    prominence_fraction: float,
) -> list[dict[str, float]]:
    """Return positive, sufficiently prominent maxima with a physical spacing."""
    checked_times, checked_values, _ = _validate_signal(times, values)
    if minimum_separation_s <= 0.0 or not 0.0 < prominence_fraction < 1.0:
        raise StatisticalContractError("invalid peak contract")
    mean = statistics.fmean(checked_values)
    centered = [value - mean for value in checked_values]
    threshold = prominence_fraction * (max(centered) - min(centered))
    peaks: list[dict[str, float]] = []
    for index in range(1, len(centered) - 1):
        value = centered[index]
        if value <= 0.0 or value < threshold:
            continue
        if value < centered[index - 1] or value <= centered[index + 1]:
            continue
        candidate = {"time_s": checked_times[index], "value": checked_values[index]}
        if peaks and candidate["time_s"] - peaks[-1]["time_s"] < minimum_separation_s:
            if candidate["value"] > peaks[-1]["value"]:
                peaks[-1] = candidate
        else:
            peaks.append(candidate)
    return peaks


def peak_frequency(peaks: Sequence[Mapping[str, float]]) -> float | None:
    periods = [float(right["time_s"]) - float(left["time_s"]) for left, right in zip(peaks, peaks[1:])]
    if not periods or any(period <= 0.0 for period in periods):
        return None
    return 1.0 / statistics.fmean(periods)


def _phase_relation(
    times: Sequence[float],
    left: Sequence[float],
    right: Sequence[float],
    frequency_hz: float | None,
) -> dict[str, float | None]:
    checked_times, checked_left, dt = _validate_signal(times, left)
    _, checked_right, _ = _validate_signal(times, right)
    if frequency_hz is None or frequency_hz <= 0.0:
        return {"lag_time_s": None, "correlation": None, "phase_deg": None}
    max_lag = max(1, int(round(0.5 / (frequency_hz * dt))))
    best: tuple[float, int] | None = None
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            a, b = checked_left[-lag:], checked_right[:lag]
        elif lag > 0:
            a, b = checked_left[:-lag], checked_right[lag:]
        else:
            a, b = checked_left, checked_right
        if len(a) < 3:
            continue
        da = [value - statistics.fmean(a) for value in a]
        db = [value - statistics.fmean(b) for value in b]
        denom = math.sqrt(sum(value * value for value in da) * sum(value * value for value in db))
        if denom == 0.0:
            continue
        correlation = sum(x * y for x, y in zip(da, db)) / denom
        if best is None or correlation > best[0]:
            best = (correlation, lag)
    if best is None:
        raise StatisticalContractError("phase relation has zero variance")
    lag_s = best[1] * dt
    return {"lag_time_s": lag_s, "correlation": best[0], "phase_deg": lag_s * frequency_hz * 360.0}


def signal_summary(times: Sequence[float], values: Sequence[float], *, minimum_separation_s: float, prominence_fraction: float) -> dict[str, object]:
    _, checked_values, _ = _validate_signal(times, values)
    peaks = prominent_positive_peaks(times, checked_values, minimum_separation_s=minimum_separation_s, prominence_fraction=prominence_fraction)
    peak_hz = peak_frequency(peaks)
    fft_hz = detrended_fft_frequency(times, checked_values)
    agreement = None if peak_hz is None or fft_hz is None else abs(peak_hz - fft_hz) / max(peak_hz, fft_hz, 1.0e-30)
    return {
        "mean": statistics.fmean(checked_values),
        "demeaned_rms": demeaned_rms(checked_values),
        "peak_to_peak": max(checked_values) - min(checked_values),
        "peak_count": len(peaks),
        "peak_frequency_hz": peak_hz,
        "fft_frequency_hz": fft_hz,
        "frequency_disagreement_fraction": agreement,
    }


def summarize_window(
    rows: Sequence[Mapping[str, object]],
    *,
    start_time_s: float,
    end_time_s: float,
    minimum_separation_s: float,
    prominence_fraction: float,
) -> dict[str, object]:
    selected = [row for row in rows if start_time_s <= _finite(row["time_s"]) < end_time_s]
    if len(selected) < 4:
        raise StatisticalContractError(f"window has insufficient evidence: {start_time_s}:{end_time_s}")
    times = [_finite(row["time_s"]) for row in selected]
    per_slice = {sid: [_finite(dict(row["slice_force_y"])[sid]) for row in selected] for sid in SLICE_IDS}
    displacement = [_finite(row["structure_displacement_y"]) for row in selected]
    forces = {sid: signal_summary(times, values, minimum_separation_s=minimum_separation_s, prominence_fraction=prominence_fraction) for sid, values in per_slice.items()}
    displacement_summary = signal_summary(times, displacement, minimum_separation_s=minimum_separation_s, prominence_fraction=prominence_fraction)
    reference_frequency = statistics.median([
        float(summary["fft_frequency_hz"])
        for summary in forces.values()
        if summary["fft_frequency_hz"] is not None
    ]) if any(summary["fft_frequency_hz"] is not None for summary in forces.values()) else None
    phases = {
        f"{left}__{right}": _phase_relation(times, per_slice[left], per_slice[right], reference_frequency)
        for left, right in combinations(SLICE_IDS, 2)
    }
    normalized_average = [statistics.fmean(per_slice[sid][index] for sid in SLICE_IDS) for index in range(len(times))]
    return {
        "start_time_s": start_time_s,
        "end_time_s": times[-1],
        "sample_count": len(selected),
        "per_slice_force_y": forces,
        "structure_displacement_y": displacement_summary,
        "phase_relation": phases,
        "normalized_slice_average_diagnostic": signal_summary(times, normalized_average, minimum_separation_s=minimum_separation_s, prominence_fraction=prominence_fraction),
        "physical_total_force": {"status": "not_evaluable", "reason": "legacy evidence has no declared tributary length or area weights"},
    }


def assess_trailing_windows(
    windows: Sequence[Mapping[str, object]],
    *,
    amplitude_drift_limit: float,
    frequency_drift_limit: float,
    phase_drift_limit_deg: float,
    phase_correlation_min: float,
) -> dict[str, object]:
    """Assess only primary per-slice and structural observables, never the average force."""
    if len(windows) != 3:
        raise StatisticalContractError("exactly three declared statistical windows are required")
    if not 0.0 < amplitude_drift_limit < 1.0 or not 0.0 < frequency_drift_limit < 1.0:
        raise StatisticalContractError("invalid stability threshold")
    if not 0.0 < phase_drift_limit_deg <= 180.0 or not -1.0 <= phase_correlation_min <= 1.0:
        raise StatisticalContractError("invalid phase stability threshold")
    per_slice: dict[str, object] = {}
    for sid in SLICE_IDS:
        amplitude = [float(dict(window["per_slice_force_y"])[sid]["demeaned_rms"]) for window in windows]
        frequency = [dict(window["per_slice_force_y"])[sid]["fft_frequency_hz"] for window in windows]
        finite_frequency = [float(value) for value in frequency if value is not None]
        amplitude_drift = _relative_drift(amplitude)
        frequency_drift = _relative_drift(finite_frequency) if len(finite_frequency) == len(windows) else None
        per_slice[sid] = {
            "amplitude_drift_fraction": amplitude_drift,
            "frequency_drift_fraction": frequency_drift,
            "amplitude_stable": amplitude_drift is not None and amplitude_drift <= amplitude_drift_limit,
            "frequency_stable": frequency_drift is not None and frequency_drift <= frequency_drift_limit,
        }
    structure_amplitude = [float(window["structure_displacement_y"]["demeaned_rms"]) for window in windows]
    structure_frequency = [window["structure_displacement_y"]["fft_frequency_hz"] for window in windows]
    structure_frequency_values = [float(value) for value in structure_frequency if value is not None]
    structure = {
        "amplitude_drift_fraction": _relative_drift(structure_amplitude),
        "frequency_drift_fraction": _relative_drift(structure_frequency_values) if len(structure_frequency_values) == len(windows) else None,
    }
    structure["amplitude_stable"] = structure["amplitude_drift_fraction"] is not None and structure["amplitude_drift_fraction"] <= amplitude_drift_limit
    structure["frequency_stable"] = structure["frequency_drift_fraction"] is not None and structure["frequency_drift_fraction"] <= frequency_drift_limit
    phase: dict[str, object] = {}
    for left, right in combinations(SLICE_IDS, 2):
        key = f"{left}__{right}"
        relations = [dict(window["phase_relation"])[key] for window in windows]
        phase_values = [relation["phase_deg"] for relation in relations]
        correlations = [relation["correlation"] for relation in relations]
        if any(value is None for value in phase_values + correlations):
            phase[key] = {"phase_span_deg": None, "minimum_correlation": None, "stable": False}
            continue
        span = _circular_span_deg([float(value) for value in phase_values])
        minimum_correlation = min(float(value) for value in correlations)
        phase[key] = {
            "phase_span_deg": span,
            "minimum_correlation": minimum_correlation,
            "stable": span is not None and span <= phase_drift_limit_deg and minimum_correlation >= phase_correlation_min,
        }
    primary_stable = (
        all(item["amplitude_stable"] and item["frequency_stable"] for item in per_slice.values())
        and structure["amplitude_stable"]
        and structure["frequency_stable"]
        and all(item["stable"] for item in phase.values())
    )
    return {"per_slice": per_slice, "structure": structure, "phase": phase, "primary_statistics_stable": primary_stable}
