"""Local signal, coherence, energy and beat diagnostics for retained evidence."""
from __future__ import annotations

from itertools import combinations
import math
from statistics import fmean, median
from typing import Mapping, Sequence

import numpy as np


SLICE_IDS = ("slice_0000", "slice_0001", "slice_0002")


class StatisticsV3Error(ValueError):
    pass


def _finite(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise StatisticsV3Error(f"{name} is not numeric") from exc
    if not math.isfinite(result):
        raise StatisticsV3Error(f"{name} is not finite")
    return result


def checked_signal(times: Sequence[object], values: Sequence[object]) -> tuple[np.ndarray, np.ndarray, float]:
    if len(times) != len(values) or len(times) < 8:
        raise StatisticsV3Error("signal must contain at least eight aligned samples")
    time = np.asarray([_finite(value, "time") for value in times], dtype=float)
    signal = np.asarray([_finite(value, "signal") for value in values], dtype=float)
    delta = np.diff(time)
    if np.any(delta <= 0.0):
        raise StatisticsV3Error("time samples are not strictly increasing")
    dt = float(np.median(delta))
    if not np.allclose(delta, dt, rtol=1.0e-6, atol=1.0e-9):
        raise StatisticsV3Error("time samples are not uniformly spaced")
    return time, signal, dt


def detrended_fft_frequency(times: Sequence[object], values: Sequence[object]) -> float:
    _, signal, dt = checked_signal(times, values)
    index = np.arange(len(signal), dtype=float)
    trend = np.polyval(np.polyfit(index, signal, 1), index)
    spectrum = np.abs(np.fft.rfft(signal - trend))
    if len(spectrum) < 2 or float(np.max(spectrum[1:])) <= 0.0:
        raise StatisticsV3Error("signal has no nonzero spectral component")
    return float(np.fft.rfftfreq(len(signal), dt)[int(np.argmax(spectrum[1:]) + 1)])


def prominent_peak_frequency(times: Sequence[object], values: Sequence[object], *, min_separation_s: float = 3.0,
                             prominence_fraction: float = 0.10) -> float | None:
    time, signal, _ = checked_signal(times, values)
    if min_separation_s <= 0.0 or not 0.0 < prominence_fraction < 1.0:
        raise StatisticsV3Error("invalid peak contract")
    centered = signal - np.mean(signal)
    threshold = prominence_fraction * float(np.ptp(centered))
    locations: list[tuple[float, float]] = []
    for index in range(1, len(centered) - 1):
        if centered[index] <= 0.0 or centered[index] < threshold:
            continue
        if centered[index] < centered[index - 1] or centered[index] <= centered[index + 1]:
            continue
        candidate = (float(time[index]), float(signal[index]))
        if locations and candidate[0] - locations[-1][0] < min_separation_s:
            if candidate[1] > locations[-1][1]:
                locations[-1] = candidate
        else:
            locations.append(candidate)
    if len(locations) < 2:
        return None
    periods = [right[0] - left[0] for left, right in zip(locations, locations[1:])]
    if any(period <= 0.0 for period in periods):
        raise StatisticsV3Error("invalid peak periods")
    return 1.0 / fmean(periods)


def signal_summary(times: Sequence[object], values: Sequence[object]) -> dict[str, float | int | None]:
    _, signal, _ = checked_signal(times, values)
    mean = float(np.mean(signal))
    return {
        "mean": mean,
        "demeaned_rms": float(np.sqrt(np.mean((signal - mean) ** 2))),
        "peak_to_peak": float(np.ptp(signal)),
        "fft_dominant_frequency_hz": detrended_fft_frequency(times, values),
        "peak_detection_frequency_hz": prominent_peak_frequency(times, values),
    }


def _welch_cross(times: Sequence[object], left: Sequence[object], right: Sequence[object]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    time, x, dt = checked_signal(times, left)
    _, y, _ = checked_signal(times, right)
    # Four or more independent-ish tapered sections retain nontrivial
    # coherence estimates in a 50 s window while resolving 0.16/0.20 Hz.
    length = min(512, len(time))
    if length < 64:
        raise StatisticsV3Error("insufficient samples for cross spectrum")
    hop = length // 2
    starts = list(range(0, len(time) - length + 1, hop))
    if len(starts) < 2:
        raise StatisticsV3Error("cross spectrum needs at least two windows")
    window = np.hanning(length)
    norm = float(np.sum(window * window))
    pxx = np.zeros(length // 2 + 1, dtype=complex)
    pyy = np.zeros_like(pxx)
    pxy = np.zeros_like(pxx)
    for start in starts:
        ix = np.arange(length, dtype=float)
        sx = x[start:start + length]
        sy = y[start:start + length]
        sx = (sx - np.polyval(np.polyfit(ix, sx, 1), ix)) * window
        sy = (sy - np.polyval(np.polyfit(ix, sy, 1), ix)) * window
        fx, fy = np.fft.rfft(sx), np.fft.rfft(sy)
        pxx += np.conj(fx) * fx / norm
        pyy += np.conj(fy) * fy / norm
        # Convention: arg(Pxy) is y relative to Fy for Pxy=conj(Fy)*Y.
        pxy += np.conj(fx) * fy / norm
    pxx /= len(starts)
    pyy /= len(starts)
    pxy /= len(starts)
    frequency = np.fft.rfftfreq(length, dt)
    coherence = np.abs(pxy) ** 2 / np.maximum(np.real(pxx) * np.real(pyy), np.finfo(float).tiny)
    return frequency, coherence, pxy, np.asarray([len(starts)], dtype=int)


def cross_spectrum_at_targets(times: Sequence[object], left: Sequence[object], right: Sequence[object], *,
                              target_hz: Sequence[float] = (0.16, 0.20)) -> dict[str, object]:
    frequency, coherence, pxy, segments = _welch_cross(times, left, right)
    entries: dict[str, object] = {}
    for target in target_hz:
        index = int(np.argmin(np.abs(frequency - target)))
        entries[f"{target:.2f}_Hz"] = {
            "requested_frequency_hz": target,
            "actual_frequency_hz": float(frequency[index]),
            "coherence": float(np.clip(coherence[index], 0.0, 1.0)),
            "phase_deg_y_relative_to_left": float(np.degrees(np.angle(pxy[index]))),
        }
    return {"method": "Welch Hann, 512 samples max, 50% overlap; Pxy=conj(left)*right", "segment_count": int(segments[0]), "targets": entries}


def power_summary(times: Sequence[object], force_y: Sequence[object], velocity_y: Sequence[object]) -> dict[str, object]:
    time, force, _ = checked_signal(times, force_y)
    _, velocity, _ = checked_signal(times, velocity_y)
    power = force * velocity
    cumulative = np.concatenate(([0.0], np.cumsum(0.5 * (power[:-1] + power[1:]) * np.diff(time))))
    return {
        "raw_unit": "legacy_force_scale_times_m_per_s; physical_W_not_evaluable",
        "mean_raw": float(np.mean(power)),
        "rms_raw": float(np.sqrt(np.mean(power ** 2))),
        "positive_fraction": float(np.mean(power > 0.0)),
        "negative_fraction": float(np.mean(power < 0.0)),
        "cumulative_raw_work": float(cumulative[-1]),
    }


def relative_drift(values: Sequence[float]) -> float:
    checked = [_finite(value, "drift value") for value in values]
    scale = max(abs(median(checked)), 1.0e-30)
    return (max(checked) - min(checked)) / scale


def local_stationarity(windows: Sequence[Mapping[str, object]], *, amplitude_limit: float = 0.05,
                       frequency_limit: float = 0.05) -> dict[str, object]:
    if len(windows) != 3:
        raise StatisticsV3Error("local stationarity requires the three adjacent 50 s windows")
    result: dict[str, object] = {}
    for sid in SLICE_IDS:
        fy = [float(dict(window["slices"])[sid]["Fy"]["demeaned_rms"]) for window in windows]
        y = [float(dict(window["slices"])[sid]["y"]["demeaned_rms"]) for window in windows]
        ffy = [float(dict(window["slices"])[sid]["Fy"]["fft_dominant_frequency_hz"]) for window in windows]
        fypos = [float(dict(window["slices"])[sid]["y"]["fft_dominant_frequency_hz"]) for window in windows]
        measures = {
            "Fy_rms_drift_fraction": relative_drift(fy),
            "Fy_frequency_drift_fraction": relative_drift(ffy),
            "y_rms_drift_fraction": relative_drift(y),
            "y_frequency_drift_fraction": relative_drift(fypos),
        }
        result[sid] = {**measures, "stable": all(value <= (amplitude_limit if "rms" in key else frequency_limit) for key, value in measures.items())}
    return {"thresholds": {"amplitude_drift_fraction_max": amplitude_limit, "frequency_drift_fraction_max": frequency_limit}, "by_slice": result,
            "status": "pass" if all(bool(item["stable"]) for item in result.values()) else "fail"}


def beat_diagnostic(full_window: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    slices = dict(full_window["slices"])
    for left, right in combinations(SLICE_IDS, 2):
        fleft = slices[left]["Fy"]["peak_detection_frequency_hz"]
        fright = slices[right]["Fy"]["peak_detection_frequency_hz"]
        if fleft is None or fright is None:
            result[f"{left}__{right}"] = {"status": "not_evaluable", "reason": "insufficient prominent peaks"}
            continue
        delta = abs(float(fleft) - float(fright))
        result[f"{left}__{right}"] = {
            "f_left_peak_hz": float(fleft), "f_right_peak_hz": float(fright), "delta_f_hz": delta,
            "estimated_beat_period_s": None if delta <= 1.0e-12 else 1.0 / delta,
            "phase_drift_deg_over_50s_from_delta_f": 360.0 * delta * 50.0,
            "interpretation": "diagnostic_only; finite-window peak estimates cannot prove a physical beating mechanism",
        }
    return result
