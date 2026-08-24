"""Stage-three v6 analysis using late, measured-response-cycle windows.

The v5 campaign used five nominal natural periods (5*Ur) for every point.
This module keeps those results intact, but adds a physically explicit
alternative: detrend the late displacement, locate positive zero crossings,
and compare adjacent windows bounded by six crossings (five measured
response periods).  The DFT/FFT-equivalent spectral estimate remains the
primary frequency; zero crossings are a diagnostic and window-construction
tool, never relabelled as an FFT frequency.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from bisect import bisect_right
from pathlib import Path

import numpy as np

try:
    from .analyze_campaign import detrend, frequency_reliable, read_rows
    from .analyze_long_sdof import max_cfl, merge_rows, trap
    from .lockin_classification_v6 import classify_lockin
except ImportError:  # Direct script execution remains supported.
    from analyze_campaign import detrend, frequency_reliable, read_rows
    from analyze_long_sdof import max_cfl, merge_rows, trap
    from lockin_classification_v6 import classify_lockin


def _detrend_time(values: list[float], times: list[float]) -> list[float]:
    if len(values) < 2:
        return list(values)
    x = np.asarray(times, dtype=float)
    y = np.asarray(values, dtype=float)
    slope, intercept = np.polyfit(x - x.mean(), y, 1)
    return (y - (intercept + slope * (x - x.mean()))).tolist()


def positive_crossings(values: list[float], times: list[float]) -> list[float]:
    """Return linearly interpolated positive-going crossings after detrending."""
    x = _detrend_time(values, times)
    crossings: list[float] = []
    for i in range(1, len(x)):
        if x[i - 1] <= 0.0 < x[i]:
            dx = x[i] - x[i - 1]
            fraction = -x[i - 1] / dx if dx else 0.0
            crossings.append(times[i - 1] + fraction * (times[i] - times[i - 1]))
    return crossings


def dft_frequency(values: list[float], times: list[float], fmin: float = 0.01, fmax: float = 0.6) -> float:
    """Estimate the dominant frequency from a detrended DFT.

    ``rfft`` is only the fast evaluation of the same discrete Fourier
    transform.  Zero padding improves the peak location without changing
    the data.  The output is explicitly named DFT in all JSON reports.
    """
    if len(values) < 16:
        return 0.0
    t = np.asarray(times, dtype=float)
    y = np.asarray(_detrend_time(values, times), dtype=float)
    dt = float(np.median(np.diff(t)))
    if not math.isfinite(dt) or dt <= 0.0:
        return 0.0
    nfft = 1 << max(12, int(math.ceil(math.log2(len(y) * 8))))
    frequencies = np.fft.rfftfreq(nfft, d=dt)
    spectrum = np.abs(np.fft.rfft(y, n=nfft))
    mask = (frequencies >= fmin) & (frequencies <= fmax)
    if not np.any(mask):
        return 0.0
    candidates = np.flatnonzero(mask)
    return float(frequencies[candidates[int(np.argmax(spectrum[candidates]))]])


def zc_frequency(values: list[float], times: list[float]) -> float:
    crossings = positive_crossings(values, times)
    if len(crossings) < 2:
        return 0.0
    return 1.0 / statistics.fmean(b - a for a, b in zip(crossings, crossings[1:]))


def interpolate_row(rows: list[dict[str, float]], time: float) -> dict[str, float]:
    times = [row["time_s"] for row in rows]
    if time < times[0] - 1.0e-9 or time > times[-1] + 1.0e-9:
        raise ValueError(f"boundary outside data: {time}")
    index = bisect_right(times, time)
    if index == 0:
        return dict(rows[0])
    if index >= len(rows):
        return dict(rows[-1])
    left, right = rows[index - 1], rows[index]
    if abs(right["time_s"] - time) <= 1.0e-12:
        return dict(right)
    alpha = (time - left["time_s"]) / (right["time_s"] - left["time_s"])
    return {key: left[key] + alpha * (right[key] - left[key]) for key in left}


def response_window(rows: list[dict[str, float]], start: float, end: float) -> list[dict[str, float]]:
    if end <= start:
        raise ValueError("response window must have positive length")
    selected = [row for row in rows if start < row["time_s"] < end]
    return [interpolate_row(rows, start), *selected, interpolate_row(rows, end)]


def phase(rows: list[dict[str, float]], key: str, frequency: float) -> float:
    t = np.asarray([row["time_s"] for row in rows], dtype=float)
    x = np.asarray(_detrend_time([row[key] for row in rows], t.tolist()), dtype=float)
    angle = 2.0 * math.pi * frequency * t
    real = float(np.sum(x * np.cos(angle)))
    imag = float(-np.sum(x * np.sin(angle)))
    return math.atan2(imag, real)


def metric(rows: list[dict[str, float]], start: float, end: float) -> dict[str, object]:
    selected = response_window(rows, start, end)
    t = [row["time_s"] for row in selected]
    y = [row["y_m"] for row in selected]
    fy = [row["force_y_N"] for row in selected]
    cl = [row["Cl"] for row in selected]
    response_dft = dft_frequency(y, t)
    lift_dft = dft_frequency(fy, t)
    response_zc = zc_frequency(y, t)
    lift_zc = zc_frequency(fy, t)
    duration = end - start
    fluid_work = trap(selected, "instantaneous_power_W")
    damping = selected[-1]["damping_dissipation_J"] - selected[0]["damping_dissipation_J"]
    mechanical = selected[-1]["mechanical_energy_J"] - selected[0]["mechanical_energy_J"]
    f_v_phase = math.degrees((phase(selected, "force_y_N", response_dft) - phase(selected, "vy_mps", response_dft) + math.pi) % (2.0 * math.pi) - math.pi) if response_dft > 0 else float("nan")
    f_y_phase = math.degrees((phase(selected, "force_y_N", response_dft) - phase(selected, "y_m", response_dft) + math.pi) % (2.0 * math.pi) - math.pi) if response_dft > 0 else float("nan")
    return {
        "start_s": start,
        "end_s": end,
        "response_cycle_count": 5.0,
        "duration_s": duration,
        "samples": len(selected),
        "dt_s": statistics.fmean(selected[i]["time_s"] - selected[i - 1]["time_s"] for i in range(1, len(selected))),
        "mean_y_m": statistics.fmean(y),
        "y_rms_m": math.sqrt(statistics.fmean(value * value for value in y)),
        "positive_peak_y_m": max(y),
        "negative_peak_y_m": min(y),
        "y_peak_m": max(abs(value) for value in y),
        "half_amplitude_y_m": 0.5 * (max(y) - min(y)),
        "fy_rms_N": math.sqrt(statistics.fmean(value * value for value in fy)),
        "cl_rms": math.sqrt(statistics.fmean(value * value for value in cl)),
        "cd_mean": statistics.fmean(row["Cd"] for row in selected),
        "response_frequency_Hz_dft": response_dft,
        "response_frequency_Hz_zero_crossing": response_zc,
        "response_dft_zero_crossing_relative_difference": abs(response_dft - response_zc) / max(abs(response_dft), 1.0e-30),
        "response_frequency_method": "dft_primary",
        "response_frequency_reliable": frequency_reliable(response_dft, response_zc),
        "lift_frequency_Hz_dft": lift_dft,
        "lift_frequency_Hz_zero_crossing": lift_zc,
        "lift_dft_zero_crossing_relative_difference": abs(lift_dft - lift_zc) / max(abs(lift_dft), 1.0e-30),
        "lift_frequency_method": "dft_primary",
        "lift_zero_crossing_reliable": frequency_reliable(lift_dft, lift_zc),
        "mean_power_W": fluid_work / duration,
        "fluid_work_J": fluid_work,
        "damping_dissipation_J": damping,
        "mechanical_energy_change_J": mechanical,
        "power_balance_relative": abs(fluid_work - damping) / max(abs(fluid_work), abs(damping), 1.0e-30),
        "energy_residual_relative": abs(fluid_work - damping - mechanical) / max(abs(fluid_work), abs(damping), abs(mechanical), 1.0e-30),
        "force_displacement_phase_deg": f_y_phase,
        "force_velocity_phase_deg": f_v_phase,
        "force_velocity_cosine": math.cos(math.radians(f_v_phase)) if math.isfinite(f_v_phase) else float("nan"),
    }


def relative(a: object, b: object) -> float:
    return abs(float(b) - float(a)) / max(abs(float(a)), 1.0e-30)


def cycle_audit(rows: list[dict[str, float]], crossings: list[float]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for start, end in zip(crossings[-4:-1], crossings[-3:]):
        item = metric(rows, start, end)
        result.append({
            "start_s": start,
            "end_s": end,
            "fluid_work_J": item["fluid_work_J"],
            "damping_dissipation_J": item["damping_dissipation_J"],
            "mechanical_energy_change_J": item["mechanical_energy_change_J"],
            "power_balance_relative": item["power_balance_relative"],
            "energy_residual_relative": item["energy_residual_relative"],
        })
    return result


def compare_pair(rows: list[dict[str, float]], crossings: list[float], index: int, ur: float, amplitude_baseline_m: float = 0.0) -> dict[str, object]:
    group = crossings[index:index + 11]
    if len(group) != 11:
        raise ValueError("a response-cycle pair requires 11 positive crossings")
    first = metric(rows, group[0], group[5])
    second = metric(rows, group[5], group[10])
    relative_changes = {
        "y_rms_m": relative(first["y_rms_m"], second["y_rms_m"]),
        "positive_peak_y_m": relative(first["positive_peak_y_m"], second["positive_peak_y_m"]),
        "negative_peak_y_m": relative(first["negative_peak_y_m"], second["negative_peak_y_m"]),
        "y_peak_m": relative(first["y_peak_m"], second["y_peak_m"]),
        "half_amplitude_y_m": relative(first["half_amplitude_y_m"], second["half_amplitude_y_m"]),
        "fy_rms_N": relative(first["fy_rms_N"], second["fy_rms_N"]),
        "cl_rms": relative(first["cl_rms"], second["cl_rms"]),
        "mean_power_W": relative(first["mean_power_W"], second["mean_power_W"]),
        "response_frequency_Hz_dft": relative(first["response_frequency_Hz_dft"], second["response_frequency_Hz_dft"]),
    }
    cycles = cycle_audit(rows, group)
    power1, power2 = abs(float(first["mean_power_W"])), abs(float(second["mean_power_W"]))
    high_power = power1 >= 0.5 and power2 >= 0.5
    amp_pass = all(relative_changes[key] < 0.05 for key in ("y_rms_m", "positive_peak_y_m", "negative_peak_y_m", "half_amplitude_y_m"))
    force_pass = relative_changes["fy_rms_N"] < 0.05 and relative_changes["cl_rms"] < 0.05
    freq_pass = relative_changes["response_frequency_Hz_dft"] < 0.02 and bool(first["response_frequency_reliable"]) and bool(second["response_frequency_reliable"])
    energy_pass = bool(cycles) and all(float(item["power_balance_relative"]) < 0.10 for item in cycles)
    mechanical = [float(item["mechanical_energy_change_J"]) for item in cycles]
    no_growth = not (len(mechanical) == 3 and all(value > 0.0 for value in mechanical) and mechanical[-1] >= mechanical[0])
    low_power_pass = (not high_power and power1 < 0.5 and power2 < 0.5 and amp_pass and force_pass and freq_pass and no_growth and bool(mechanical) and abs(statistics.fmean(mechanical)) < 0.5)
    energy_gate = energy_pass if high_power else low_power_pass
    final_pass = amp_pass and force_pass and freq_pass and energy_gate
    f_over_fn = float(second["response_frequency_Hz_dft"]) * ur
    frequency_state = "frequency_synchronized" if 0.95 <= f_over_fn <= 1.05 and freq_pass else "outside_frequency_sync" if freq_pass else "frequency_unresolved"
    power_floor = 0.5
    active_power = float(second["mean_power_W"]) > power_floor
    phase_positive = math.isfinite(float(second["force_velocity_cosine"])) and float(second["force_velocity_cosine"]) > 0.0
    physical = classify_lockin(
        final_steady_window_pass=final_pass,
        frequency_state=frequency_state,
        response_frequency_reliable=bool(first["response_frequency_reliable"]) and bool(second["response_frequency_reliable"]),
        y_rms_m=float(second["y_rms_m"]),
        amplitude_baseline_m=amplitude_baseline_m,
        mean_power_W=float(second["mean_power_W"]),
        force_velocity_phase_deg=float(second["force_velocity_phase_deg"]),
        power_noise_floor_W=power_floor,
    )
    return {
        "window_1": first,
        "window_2": second,
        "crossings_used_s": group,
        "relative_changes": relative_changes,
        "relative_power_criterion_applicable": high_power,
        "power_noise_floor_W": power_floor,
        "amplitude_stationarity_pass": amp_pass,
        "force_stationarity_pass": force_pass,
        "frequency_stationarity_pass": freq_pass,
        "energy_stationarity_pass": energy_pass,
        "absolute_low_power_criterion_pass": low_power_pass,
        "final_steady_window_pass": final_pass,
        "frequency_state": frequency_state,
        "physical_lockin_classification": physical,
        "f_over_fn_dft": f_over_fn,
        "last_three_cycle_energy_audit": cycles,
        "last_three_cycle_mechanical_energy_change_J": mechanical,
        "active_power_pass": active_power,
        "force_velocity_phase_gate_pass": phase_positive,
        "amplitude_baseline_m": amplitude_baseline_m,
        "ur": ur,
    }


def natural_pair(rows: list[dict[str, float]], ur: float) -> dict[str, object]:
    end = rows[-1]["time_s"]
    start = end - 10.0 * ur
    first_end = start + 5.0 * ur
    return {
        "window_1": metric(rows, start, first_end),
        "window_2": metric(rows, first_end, end),
        "relative_changes": {
            key: relative(metric(rows, start, first_end)[key], metric(rows, first_end, end)[key])
            for key in ("y_rms_m", "y_peak_m", "half_amplitude_y_m", "fy_rms_N", "cl_rms", "mean_power_W", "response_frequency_Hz_dft")
        },
        "window_definition": "5 natural periods = 5*Ur; retained as comparison only",
    }


def analyze(rows: list[dict[str, float]], logs: list[Path], ur: float, tail_start: float | None = None, amplitude_baseline_m: float = 0.0) -> dict[str, object]:
    end = rows[-1]["time_s"]
    if tail_start is None:
        # Retain enough post-release history to construct at least three
        # translated response-cycle pairs, while selecting only the latest
        # groups for acceptance.  This is not a shorter-window shortcut:
        # every accepted group still contains two complete five-cycle
        # windows and the tail origin is reported in the JSON.
        tail_start = max(rows[0]["time_s"], 0.3 * end)
    tail = [row for row in rows if row["time_s"] >= tail_start]
    t = [row["time_s"] for row in tail]
    y = [row["y_m"] for row in tail]
    crossings = positive_crossings(y, t)
    if len(crossings) < 11:
        raise ValueError(f"only {len(crossings)} positive crossings after tail_start={tail_start}")
    f_tail = dft_frequency(y, t)
    # The v6 rule is explicitly about the last reliable crossings.  A single
    # missed crossing earlier in the tail must not poison the reliability of
    # the final ten-cycle record.
    used_crossings = crossings[-11:]
    f_zc = 1.0 / statistics.fmean(b - a for a, b in zip(used_crossings, used_crossings[1:]))
    periods = [b - a for a, b in zip(used_crossings, used_crossings[1:])]
    period_mean = statistics.fmean(periods)
    period_cv = statistics.pstdev(periods) / period_mean if len(periods) > 1 else float("inf")
    # Use the last three possible groups when available.  Earlier crossings
    # are retained only to establish the response period; they are never
    # silently used as a final window if three late groups exist.
    starts = list(range(max(0, len(crossings) - 13), len(crossings) - 10))
    pair_results = [compare_pair(rows, crossings, index, ur, amplitude_baseline_m) for index in starts]
    passed = [bool(item["final_steady_window_pass"]) for item in pair_results]
    final = pair_results[-1]
    return {
        "status": "response_cycle_analysis_completed",
        "ur": ur,
        "fn_Hz": 1.0 / ur,
        "time_start_s": rows[0]["time_s"],
        "time_end_s": end,
        "tail_start_s": tail_start,
        "tail_end_s": end,
        "response_frequency_Hz_dft": f_tail,
        "response_period_s": 1.0 / f_tail if f_tail > 0 else float("nan"),
        "response_frequency_Hz_zero_crossing": f_zc,
        "dft_zero_crossing_difference": abs(f_tail - f_zc) / max(abs(f_tail), 1.0e-30),
        "crossing_count": len(crossings),
        "crossing_count_used": 11,
        "crossing_reliability": {"period_cv": period_cv, "period_cv_pass": period_cv < 0.05, "dft_zero_crossing_pass": abs(f_tail - f_zc) / max(abs(f_tail), 1.0e-30) < 0.05, "reliable": period_cv < 0.05 and abs(f_tail - f_zc) / max(abs(f_tail), 1.0e-30) < 0.05, "definition": "last 11 positive-going crossings; earlier missed crossings are retained in crossing_count but excluded from the final reliability gate"},
        "response_period_window_metrics": pair_results,
        "response_period_groups_tested": len(pair_results),
        "response_period_groups_passed": sum(passed),
        "response_period_robust_pass": sum(passed) >= min(2, len(passed)),
        "final_window_method_used": "response-cycle-aligned",
        "amplitude_baseline_m": amplitude_baseline_m,
        "natural_period_window_metrics": natural_pair(rows, ur),
        "final_response_pair": final,
        "frequency_methods": {"response_primary": "detrended zero-padded DFT (rFFT evaluation of the DFT)", "response_diagnostic": "positive-going zero crossings with linear interpolation", "lift_primary": "detrended zero-padded DFT", "lift_diagnostic": "positive-going zero crossings; diagnostic only"},
        "max_abs_y_m": max(abs(row["y_m"]) for row in rows),
        "max_cfl": max((max_cfl(path) for path in logs), default=float("nan")),
        "safety": {"max_abs_y_m": max(abs(row["y_m"]) for row in rows), "max_cfl": max((max_cfl(path) for path in logs), default=float("nan")), "limits": {"max_abs_y_m": 1.5, "max_cfl": 0.5}},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, nargs="+", required=True)
    parser.add_argument("--log", type=Path, nargs="+", required=True)
    parser.add_argument("--ur", type=float, required=True)
    parser.add_argument("--tail-start", type=float)
    parser.add_argument("--amplitude-baseline-m", type=float, default=0.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = merge_rows(args.audit)
    payload = analyze(rows, args.log, args.ur, args.tail_start, args.amplitude_baseline_m)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, allow_nan=True) + "\n", encoding="utf-8")
    print(json.dumps({"ur": args.ur, "end_s": payload["time_end_s"], "crossings": payload["crossing_count"], "groups": payload["response_period_groups_tested"], "passed": payload["response_period_groups_passed"], "final_pass": payload["final_response_pair"]["final_steady_window_pass"]}, indent=2))


if __name__ == "__main__":
    main()
