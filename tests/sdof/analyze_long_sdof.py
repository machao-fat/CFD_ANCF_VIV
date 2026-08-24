from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path

try:
    from .analyze_campaign import (
        detrend,
        frequency_reliable,
        read_rows,
        relative_frequency_difference,
        zero_crossing_frequency,
    )
except ImportError:  # Direct script execution remains supported.
    from analyze_campaign import (
        detrend,
        frequency_reliable,
        read_rows,
        relative_frequency_difference,
        zero_crossing_frequency,
    )


def merge_rows(paths: list[Path]) -> list[dict[str, float]]:
    rows = []
    for path in paths:
        rows.extend(read_rows(path))
    rows.sort(key=lambda row: row["time_s"])
    merged: list[dict[str, float]] = []
    for row in rows:
        if merged and abs(row["time_s"] - merged[-1]["time_s"]) <= 1.0e-12:
            if row["step"] != merged[-1]["step"]:
                raise ValueError(f"duplicate time with different step: {row['time_s']}")
            continue
        merged.append(row)
    if any(b["time_s"] <= a["time_s"] for a, b in zip(merged, merged[1:])):
        raise ValueError("merged time series is not strictly increasing")
    return merged


def window(rows: list[dict[str, float]], start: float, end: float) -> list[dict[str, float]]:
    selected = [row for row in rows if start - 1.0e-12 <= row["time_s"] <= end + 1.0e-12]
    if len(selected) < 2 or abs(selected[0]["time_s"] - start) > 1.0e-9 or abs(selected[-1]["time_s"] - end) > 1.0e-9:
        raise ValueError(f"window not fully represented: {start} -> {end}")
    return selected


def trap(rows: list[dict[str, float]], key: str) -> float:
    return sum(
        0.5 * (rows[i - 1][key] + rows[i][key]) * (rows[i]["time_s"] - rows[i - 1]["time_s"])
        for i in range(1, len(rows))
    )


def spectral_peak_frequency(values: list[float], dt: float, fmin: float = 0.01, fmax: float = 0.6, bins: int = 600) -> float:
    """Small direct-DFT spectrum used when numpy is unavailable."""
    x = detrend(values)
    best_f = fmin
    best_amp = -1.0
    for index in range(bins + 1):
        frequency = fmin + (fmax - fmin) * index / bins
        real = sum(value * math.cos(2.0 * math.pi * frequency * i * dt) for i, value in enumerate(x))
        imag = sum(value * math.sin(2.0 * math.pi * frequency * i * dt) for i, value in enumerate(x))
        amplitude = real * real + imag * imag
        if amplitude > best_amp:
            best_amp = amplitude
            best_f = frequency
    return best_f


def metrics(rows: list[dict[str, float]], start: float, end: float, ur: float, *, include_spectrum: bool = False) -> dict[str, float | int]:
    selected = window(rows, start, end)
    dt = statistics.fmean(selected[i]["time_s"] - selected[i - 1]["time_s"] for i in range(1, len(selected)))
    t = [row["time_s"] for row in selected]
    y = [row["y_m"] for row in selected]
    fy = [row["force_y_N"] for row in selected]
    cl = [row["Cl"] for row in selected]
    f_zero = zero_crossing_frequency(y, t)
    f_lift_zero = zero_crossing_frequency(fy, t)
    power = trap(selected, "instantaneous_power_W") / (end - start)
    f_dft = spectral_peak_frequency(y, dt) if include_spectrum else 0.0
    f_lift_dft = spectral_peak_frequency(fy, dt) if include_spectrum else 0.0
    response_frequency_difference = relative_frequency_difference(f_dft, f_zero) if include_spectrum else float("inf")
    lift_frequency_difference = relative_frequency_difference(f_lift_dft, f_lift_zero) if include_spectrum else float("inf")
    return {
        # For the present U=D=1 benchmark, the natural period is Ur seconds.
        # Keep this generic so campaign points are not mislabeled as Ur=5.2.
        "start_s": start, "end_s": end, "cycles": (end - start) / ur,
        "samples": len(selected), "dt_s": dt,
        "y_rms_m": math.sqrt(statistics.fmean(value * value for value in y)),
        "y_peak_m": max(abs(value) for value in y),
        "fy_rms_N": math.sqrt(statistics.fmean(value * value for value in fy)),
        "cl_rms": math.sqrt(statistics.fmean(value * value for value in cl)),
        "cd_mean": statistics.fmean(row["Cd"] for row in selected),
        "response_frequency_Hz_dft": f_dft,
        "response_frequency_Hz_fft": f_dft,
        "response_frequency_Hz_zero_crossing": f_zero,
        "response_frequency_Hz": f_dft,
        "response_frequency_method": "dft_primary",
        "response_frequency_reliable": frequency_reliable(f_dft, f_zero) if include_spectrum else False,
        "response_dft_zero_crossing_relative_difference": response_frequency_difference,
        "lift_frequency_Hz_dft": f_lift_dft,
        "lift_frequency_Hz_fft": f_lift_dft,
        "lift_frequency_Hz_zero_crossing": f_lift_zero,
        "lift_frequency_Hz": f_lift_dft,
        "lift_frequency_method": "dft_primary",
        "lift_zero_crossing_reliable": frequency_reliable(f_lift_dft, f_lift_zero) if include_spectrum else False,
        "lift_dft_zero_crossing_relative_difference": lift_frequency_difference,
        "f_over_fn_zero_crossing": f_zero / (1.0 / (ur * 1.0)),
        "mean_power_W": power,
        "fluid_work_J": trap(selected, "instantaneous_power_W"),
        "damping_dissipation_increment_J": selected[-1]["damping_dissipation_J"] - selected[0]["damping_dissipation_J"],
    }


def max_cfl(log: Path) -> float:
    pattern = re.compile(r"Courant Number mean:\s*[-+0-9.eE]+\s+max:\s*([-+0-9.eE]+)")
    values = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.search(line)
        if match:
            values.append(float(match.group(1)))
    return max(values, default=float("nan"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segments", type=Path, nargs="+", required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--ur", type=float, default=5.2)
    parser.add_argument("--window-start", type=float, default=8.0)
    parser.add_argument("--end-time", type=float, default=60.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = merge_rows(args.segments)
    first_end = args.window_start + 5.0 * args.ur
    second_end = first_end + 5.0 * args.ur
    if second_end > args.end_time + 1.0e-9:
        raise ValueError("end-time must contain two adjacent five-cycle windows")
    first = metrics(rows, args.window_start, first_end, args.ur, include_spectrum=True)
    second = metrics(rows, first_end, second_end, args.ur, include_spectrum=True)
    def rel(key: str) -> float:
        return abs(float(second[key]) - float(first[key])) / max(abs(float(first[key])), 1.0e-30)
    rolling = {key + "_relative_change": rel(key) for key in ("y_rms_m", "y_peak_m", "fy_rms_N", "mean_power_W", "cl_rms")}
    rolling["response_frequency_relative_change"] = abs(float(second["response_frequency_Hz_zero_crossing"]) - float(first["response_frequency_Hz_zero_crossing"])) / max(abs(float(first["response_frequency_Hz_zero_crossing"])), 1.0e-30)
    energy_cycles = []
    for index in range(10):
        start = args.window_start + index * args.ur
        end = start + args.ur
        item = metrics(rows, start, end, args.ur)
        energy_cycles.append({"cycle_index": index + 1, "start_s": start, "end_s": end, "fluid_work_J": item["fluid_work_J"], "damping_dissipation_increment_J": item["damping_dissipation_increment_J"], "mean_power_W": item["mean_power_W"]})
    stable = all(rolling[key] < limit for key, limit in {
        "y_rms_m_relative_change": 0.05, "y_peak_m_relative_change": 0.05,
        "fy_rms_N_relative_change": 0.05, "mean_power_W_relative_change": 0.05,
        "cl_rms_relative_change": 0.05, "response_frequency_relative_change": 0.02,
    }.items())
    payload = {
        "status": "accepted_10_cycle_window" if stable else "long_window_completed_but_rolling_stability_not_met",
        "ur": args.ur, "natural_frequency_Hz": 1.0 / (args.ur * 1.0),
        "time_start_s": rows[0]["time_s"], "time_end_s": rows[-1]["time_s"],
        "total_cycles_from_window_start": (rows[-1]["time_s"] - args.window_start) / args.ur,
        "rows": len(rows), "max_abs_y_m": max(abs(row["y_m"]) for row in rows),
        "max_cfl": max_cfl(args.log), "window_1": first, "window_2": second,
        "frequency_methods": {
            "zero_crossing": "alternating-sign crossings with linear interpolation; one full period per two crossings",
            "dft": "detrended direct-DFT spectral scan, 0.01-0.60 Hz",
            "fft_legacy_fields": "compatibility aliases for dft fields only; never zero-crossing values",
        },
        "rolling_window_relative_changes": rolling,
        "rolling_stability_pass": stable,
        "cycle_energy_audit": energy_cycles,
        "safety_limits": {"max_abs_y_m": 1.5, "max_cfl": 0.5},
        "interpretation": "Two adjacent five-cycle windows are compared; the last half of a run is not automatically called steady.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
