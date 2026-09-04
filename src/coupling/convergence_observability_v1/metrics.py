from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable, Mapping


class ObservationError(ValueError):
    """Raised when an observable violates the time/identity contract."""


def _finite(value: float, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ObservationError(f"{name} is not numeric") from exc
    if not math.isfinite(result):
        raise ObservationError(f"{name} is NaN/Inf")
    return result


@dataclass(frozen=True)
class StepObservation:
    global_step: int
    case_local_bridge_step: int
    time_s: float
    integer_tick: int
    slice_force_y: Mapping[str, float]
    q_norm: float | None = None
    qdot_norm: float | None = None
    worker_residual: float | None = None
    worker_iterations: int | None = None
    courant_max: float | None = None
    continuity_global: float | None = None
    virtual_work_error: float | None = None
    return_code: int = 0
    finite_value_audit: bool = True

    def validate(self, slice_ids: Iterable[str], dt_s: float) -> None:
        expected = tuple(slice_ids)
        if not expected or set(self.slice_force_y) != set(expected):
            raise ObservationError("slice force identity mismatch")
        if not isinstance(self.global_step, int) or self.global_step < 1:
            raise ObservationError("global_step is invalid")
        if not isinstance(self.case_local_bridge_step, int) or self.case_local_bridge_step < 1:
            raise ObservationError("case_local_bridge_step is invalid")
        time_s = _finite(self.time_s, "time_s")
        if time_s <= 0.0 or self.integer_tick != int(round(time_s * 1.0e9)):
            raise ObservationError("time/tick mismatch")
        if not math.isfinite(dt_s) or dt_s <= 0.0:
            raise ObservationError("dt_s is invalid")
        for sid in expected:
            _finite(self.slice_force_y[sid], f"{sid}.force_y")
        for name in ("q_norm", "qdot_norm", "worker_residual", "courant_max", "continuity_global", "virtual_work_error"):
            value = getattr(self, name)
            if value is not None:
                _finite(value, name)
        if self.worker_iterations is not None and (not isinstance(self.worker_iterations, int) or self.worker_iterations < 0):
            raise ObservationError("worker_iterations is invalid")
        if not isinstance(self.return_code, int) or self.return_code != 0:
            raise ObservationError("non-zero solver return code")
        if self.finite_value_audit is not True:
            raise ObservationError("finite value audit failed")


def _relative_delta(values: list[float]) -> float | None:
    if not values:
        return None
    scale = max(abs(statistics.median(values)), 1.0e-30)
    return (max(values) - min(values)) / scale


def _fft_frequency(samples: list[dict[str, float | int | None]]) -> float | None:
    """Return the detrended scalar FFT peak when NumPy is available."""
    if len(samples) < 4:
        return None
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return None
    values = np.asarray([float(item["force_y"]) for item in samples], dtype=float)
    if not np.isfinite(values).all():
        return None
    times = np.asarray([float(item["time_s"]) for item in samples], dtype=float)
    dt = float(np.median(np.diff(times))) if len(times) > 1 else 0.0
    if dt <= 0.0:
        return None
    values = values - np.polyval(np.polyfit(np.arange(len(values)), values, 1), np.arange(len(values)))
    spectrum = np.abs(np.fft.rfft(values))
    if len(spectrum) < 2:
        return None
    index = int(np.argmax(spectrum[1:]) + 1)
    return float(np.fft.rfftfreq(len(values), d=dt)[index])


class ConvergenceAccumulator:
    """Streaming scalar recorder; no field arrays are retained."""

    def __init__(self, *, dt_s: float, slice_ids: Iterable[str], sample_every_steps: int = 10,
                 window_count: int = 3, minimum_cycles: int = 15, tolerance: float = 0.05) -> None:
        self.dt_s = _finite(dt_s, "dt_s")
        if self.dt_s <= 0.0 or sample_every_steps < 1 or window_count != 3 or minimum_cycles < 1:
            raise ObservationError("invalid convergence accumulator contract")
        self.slice_ids = tuple(slice_ids)
        if not self.slice_ids or len(set(self.slice_ids)) != len(self.slice_ids):
            raise ObservationError("slice_ids are invalid")
        self.sample_every_steps = int(sample_every_steps)
        self.window_count = int(window_count)
        self.minimum_cycles = int(minimum_cycles)
        self.tolerance = _finite(tolerance, "tolerance")
        if not 0.0 < self.tolerance < 1.0:
            raise ObservationError("tolerance is invalid")
        self._samples: list[dict[str, float | int | None]] = []
        self._last_step: int | None = None
        self._errors: list[str] = []

    def observe(self, observation: StepObservation) -> bool:
        """Validate and retain only configured scalar samples."""
        try:
            observation.validate(self.slice_ids, self.dt_s)
            if self._last_step is not None and observation.global_step <= self._last_step:
                raise ObservationError("global_step is stale or out of order")
            self._last_step = observation.global_step
            if observation.global_step % self.sample_every_steps:
                return False
            force_y = statistics.fmean(float(observation.slice_force_y[sid]) for sid in self.slice_ids)
            self._samples.append({
                "global_step": observation.global_step,
                "case_local_bridge_step": observation.case_local_bridge_step,
                "time_s": float(observation.time_s),
                "integer_tick": observation.integer_tick,
                "force_y": force_y,
                "q_norm": observation.q_norm,
                "qdot_norm": observation.qdot_norm,
                "worker_residual": observation.worker_residual,
                "worker_iterations": observation.worker_iterations,
                "courant_max": observation.courant_max,
                "continuity_global": observation.continuity_global,
                "virtual_work_error": observation.virtual_work_error,
            })
            return True
        except ObservationError as exc:
            self._errors.append(str(exc))
            raise

    @staticmethod
    def _peaks(samples: list[dict[str, float | int | None]], minimum_separation_s: float = 2.0) -> list[dict[str, float]]:
        if len(samples) < 3:
            return []
        result: list[dict[str, float]] = []
        for index in range(1, len(samples) - 1):
            left = float(samples[index - 1]["force_y"])
            current = float(samples[index]["force_y"])
            right = float(samples[index + 1]["force_y"])
            if current >= left and current > right:
                if result and float(samples[index]["time_s"]) - result[-1]["time_s"] < minimum_separation_s:
                    if current > result[-1]["value"]:
                        result[-1] = {"time_s": float(samples[index]["time_s"]), "value": current}
                else:
                    result.append({"time_s": float(samples[index]["time_s"]), "value": current})
        return result

    @staticmethod
    def _window(samples: list[dict[str, float | int | None]], peaks: list[dict[str, float]]) -> dict[str, object]:
        values = [float(item["force_y"]) for item in samples]
        periods = [peaks[index + 1]["time_s"] - peaks[index]["time_s"] for index in range(len(peaks) - 1)]
        return {
            "start_time_s": float(samples[0]["time_s"]) if samples else None,
            "end_time_s": float(samples[-1]["time_s"]) if samples else None,
            "sample_count": len(samples),
            "cycle_count": len(periods),
            "mean_force_y": statistics.fmean(values) if values else None,
            "rms_force_y": math.sqrt(statistics.fmean(value * value for value in values)) if values else None,
            "peak_to_peak_force_y": max(values) - min(values) if values else None,
            "mean_period_s": statistics.fmean(periods) if periods else None,
            "frequency_hz": 1.0 / statistics.fmean(periods) if periods and statistics.fmean(periods) > 0.0 else None,
        }

    def finalize(self) -> dict[str, object]:
        samples = list(self._samples)
        peaks = self._peaks(samples)
        periods = [peaks[index + 1]["time_s"] - peaks[index]["time_s"] for index in range(len(peaks) - 1)]
        overall_frequency = 1.0 / statistics.fmean(periods) if periods and statistics.fmean(periods) > 0.0 else None
        windows: list[dict[str, object]] = []
        if samples:
            width = max(1, len(samples) // self.window_count)
            for index in range(self.window_count):
                part = samples[index * width:(index + 1) * width] if index < self.window_count - 1 else samples[index * width:]
                if part:
                    lo, hi = float(part[0]["time_s"]), float(part[-1]["time_s"])
                    window_peaks = [peak for peak in peaks if lo <= peak["time_s"] <= hi]
                    windows.append(self._window(part, window_peaks))
        frequencies = [float(item["frequency_hz"]) for item in windows if item.get("frequency_hz") is not None]
        amplitudes = [float(item["peak_to_peak_force_y"]) for item in windows if item.get("peak_to_peak_force_y") is not None]
        frequency_drift = _relative_delta(frequencies)
        amplitude_drift = _relative_delta(amplitudes)
        fft_frequency = _fft_frequency(samples)
        reasons: list[str] = list(self._errors)
        if len(samples) < 300:
            reasons.append("fewer than 300 scalar samples")
        if len(periods) < self.minimum_cycles:
            reasons.append(f"fewer than {self.minimum_cycles} valid cycles")
        if len(windows) != self.window_count or any(int(window["sample_count"]) == 0 for window in windows):
            reasons.append("three stable windows are not available")
        if frequency_drift is None or frequency_drift > self.tolerance:
            reasons.append("window frequency drift exceeds 5% or is unavailable")
        if amplitude_drift is None or amplitude_drift > self.tolerance:
            reasons.append("window amplitude drift exceeds 5% or is unavailable")
        peak_frequency = overall_frequency
        if fft_frequency is None or peak_frequency is None:
            reasons.append("FFT/peak frequency comparison is unavailable")
        elif abs(fft_frequency - peak_frequency) / max(abs(fft_frequency), abs(peak_frequency), 1.0e-30) > self.tolerance:
            reasons.append("FFT and peak frequency differ by more than 5%")
        quality_fields = ("worker_residual", "courant_max", "continuity_global", "virtual_work_error")
        missing_quality = [field for field in quality_fields if not any(item[field] is not None for item in samples)]
        if missing_quality:
            reasons.append("missing quality observables: " + ",".join(missing_quality))
        return {
            "schema_version": 1,
            "sample_count": len(samples),
            "cycle_count": len(periods),
            "peak_count": len(peaks),
            "overall_frequency_hz": overall_frequency,
            "fft_frequency_hz": fft_frequency,
            "frequency_drift_fraction": frequency_drift,
            "amplitude_drift_fraction": amplitude_drift,
            "peaks": peaks,
            "windows": windows,
            "quality_observables": {
                field: {"min": min(float(item[field]) for item in samples if item[field] is not None),
                        "max": max(float(item[field]) for item in samples if item[field] is not None)}
                for field in quality_fields if any(item[field] is not None for item in samples)
            },
            "formal_convergence": "pass" if not reasons else "not_completed",
            "reasons": reasons,
            "storage": {"retained": "scalar samples, peaks, three window summaries", "full_fields_retained": False},
        }
