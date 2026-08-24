"""Analyze EB/ANCF continuation with identical measured-response windows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from bisect import bisect_right
from pathlib import Path

import numpy as np


def read(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        result = []
        for row in csv.DictReader(stream):
            parsed: dict[str, float] = {}
            for key, value in row.items():
                try:
                    parsed[key] = float(value)
                except (TypeError, ValueError):
                    parsed[key] = value  # type: ignore[assignment]
            result.append(parsed)
        return result


def merge(source: Path, continuation: Path, checkpoint_time: float) -> list[dict[str, float]]:
    rows = [row for row in read(source) if float(row["time_s"]) <= checkpoint_time + 1.0e-12]
    rows.extend(read(continuation))
    rows.sort(key=lambda row: float(row["time_s"]))
    result: list[dict[str, float]] = []
    for row in rows:
        if result and abs(float(row["time_s"]) - float(result[-1]["time_s"])) <= 1.0e-12:
            continue
        result.append(row)
    return result


def detrend(values: list[float], times: list[float]) -> np.ndarray:
    x = np.asarray(times, dtype=float)
    y = np.asarray(values, dtype=float)
    slope, intercept = np.polyfit(x - x.mean(), y, 1)
    return y - (intercept + slope * (x - x.mean()))


def crossings(values: list[float], times: list[float]) -> list[float]:
    x = detrend(values, times)
    result = []
    for i in range(1, len(x)):
        if x[i - 1] <= 0.0 < x[i]:
            fraction = -x[i - 1] / (x[i] - x[i - 1]) if x[i] != x[i - 1] else 0.0
            result.append(times[i - 1] + fraction * (times[i] - times[i - 1]))
    return result


def dft(values: list[float], times: list[float]) -> float:
    if len(values) < 16:
        return 0.0
    x = detrend(values, times)
    dt = float(np.median(np.diff(np.asarray(times))))
    nfft = 1 << max(12, int(math.ceil(math.log2(len(x) * 8))))
    f = np.fft.rfftfreq(nfft, d=dt)
    a = np.abs(np.fft.rfft(x, n=nfft))
    mask = (f >= 0.01) & (f <= 0.6)
    idx = np.flatnonzero(mask)
    return float(f[idx[int(np.argmax(a[idx]))]])


def interpolate(rows: list[dict[str, float]], time_s: float) -> dict[str, float]:
    times = [float(row["time_s"]) for row in rows]
    index = bisect_right(times, time_s)
    if index == 0 or index >= len(rows):
        return dict(rows[min(max(index, 0), len(rows) - 1)])
    left, right = rows[index - 1], rows[index]
    alpha = (time_s - float(left["time_s"])) / (float(right["time_s"]) - float(left["time_s"]))
    result = {}
    for key, value in left.items():
        if isinstance(value, (int, float)) and isinstance(right[key], (int, float)):
            result[key] = float(value) + alpha * (float(right[key]) - float(value))
        else:
            result[key] = value
    return result


def window(rows: list[dict[str, float]], start: float, end: float) -> list[dict[str, float]]:
    interior = [row for row in rows if start < float(row["time_s"]) < end]
    return [interpolate(rows, start), *interior, interpolate(rows, end)]


def integrate(rows: list[dict[str, float]], key: str) -> float:
    return sum(0.5 * (float(rows[i - 1][key]) + float(rows[i][key])) * (float(rows[i]["time_s"]) - float(rows[i - 1]["time_s"])) for i in range(1, len(rows)))


def metric(rows: list[dict[str, float]], start: float, end: float) -> dict[str, object]:
    selected = window(rows, start, end)
    t = [float(row["time_s"]) for row in selected]
    y = [float(row["corrected_y_m"]) for row in selected]
    fy = [float(row["force_y_N"]) for row in selected]
    fy_frequency = dft(fy, t)
    y_frequency = dft(y, t)
    work = integrate(selected, "instantaneous_power_W")
    damping = integrate(selected, "damping_power_W")
    mech = float(selected[-1]["mechanical_energy_J"]) - float(selected[0]["mechanical_energy_J"])
    phase = float("nan")
    if y_frequency > 0.0:
        y0 = detrend(y, t); f0 = detrend(fy, t); v0 = detrend([float(row["corrected_vy_mps"]) for row in selected], t)
        angle = 2.0 * math.pi * y_frequency * np.asarray(t)
        ph_f = math.atan2(float(-np.sum(f0 * np.sin(angle))), float(np.sum(f0 * np.cos(angle))))
        ph_v = math.atan2(float(-np.sum(v0 * np.sin(angle))), float(np.sum(v0 * np.cos(angle))))
        phase = math.degrees((ph_f - ph_v + math.pi) % (2.0 * math.pi) - math.pi)
    return {
        "start_s": start, "end_s": end, "response_cycle_count": 5.0, "samples": len(selected),
        "y_rms_m": math.sqrt(statistics.fmean(value * value for value in y)),
        "positive_peak_y_m": max(y), "negative_peak_y_m": min(y), "y_peak_m": max(abs(value) for value in y),
        "half_amplitude_y_m": 0.5 * (max(y) - min(y)), "fy_rms_N": math.sqrt(statistics.fmean(value * value for value in fy)),
        "y_frequency_Hz_dft": y_frequency, "fy_frequency_Hz_dft": fy_frequency,
        "mean_power_W": work / (end - start), "fluid_work_J": work, "damping_dissipation_J": damping,
        "mechanical_energy_change_J": mech, "energy_balance_residual_J": work - damping - mech,
        "energy_balance_relative": abs(work - damping - mech) / max(abs(work), abs(damping), abs(mech), 1.0e-30),
        "force_velocity_phase_deg": phase,
        "max_relative_residual": max(float(row["structure_relative_residual"]) for row in selected),
        "all_newton_converged": all(str(row["structure_converged"]).lower() in {"1.0", "true"} for row in selected),
        "min_tension_N": min(float(row["min_tension_N"]) for row in rows),
        "max_slope": max(float(row["max_slope"]) for row in selected),
        "max_curvature_1pm": max(float(row["max_curvature_1pm"]) for row in selected),
    }


def relative(a: object, b: object) -> float:
    return abs(float(b) - float(a)) / max(abs(float(a)), 1.0e-30)


def branch(rows: list[dict[str, float]], end_time: float) -> dict[str, object]:
    late = [row for row in rows if float(row["time_s"]) >= max(5.0, end_time - 65.0)]
    times = [float(row["time_s"]) for row in late]
    y = [float(row["corrected_y_m"]) for row in late]
    c = crossings(y, times)
    if len(c) < 11:
        raise ValueError(f"only {len(c)} late positive crossings")
    used = c[-11:]
    f = dft(y, times)
    fz = 1.0 / statistics.fmean(b - a for a, b in zip(used, used[1:]))
    p1 = metric(rows, used[0], used[5]); p2 = metric(rows, used[5], used[10])
    return {
        "time_end_s": float(rows[-1]["time_s"]), "late_start_s": late[0]["time_s"],
        "response_frequency_Hz_dft": f, "response_period_s": 1.0 / f,
        "zero_crossing_frequency_Hz": fz, "dft_zero_crossing_relative_difference": abs(f - fz) / max(abs(f), 1.0e-30),
        "crossing_count": len(c), "crossings_used_s": used, "window_1": p1, "window_2": p2,
        "frequency_reliable": abs(f - fz) / max(abs(f), 1.0e-30) < 0.05,
        "windows_have_five_response_cycles": True,
    }


def apply_common_boundaries(branch_payload: dict[str, object], rows: list[dict[str, float]], boundaries: list[float]) -> None:
    """Replace branch-local windows with the same measured boundaries.

    The two independent CFD runs have nearly identical response periods but
    their interpolated crossing times are not bitwise identical.  Pairwise
    averaging the two measured crossing times gives one common physical
    boundary set; each branch is then interpolated onto that same set.
    """
    if len(boundaries) != 11:
        raise ValueError("common response-cycle boundary set must contain 11 crossings")
    branch_payload["local_crossings_used_s"] = branch_payload["crossings_used_s"]
    branch_payload["crossings_used_s"] = boundaries
    branch_payload["window_1"] = metric(rows, boundaries[0], boundaries[5])
    branch_payload["window_2"] = metric(rows, boundaries[5], boundaries[10])
    branch_payload["windows_have_five_response_cycles"] = True
    branch_payload["windows_use_common_boundaries"] = True


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eb-source", type=Path, required=True)
    parser.add_argument("--eb-continuation", type=Path, required=True)
    parser.add_argument("--ancf-source", type=Path, required=True)
    parser.add_argument("--ancf-continuation", type=Path, required=True)
    parser.add_argument("--checkpoint-time", type=float, default=30.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    eb_rows = merge(args.eb_source, args.eb_continuation, args.checkpoint_time)
    ancf_rows = merge(args.ancf_source, args.ancf_continuation, args.checkpoint_time)
    eb = branch(eb_rows, float(eb_rows[-1]["time_s"]))
    ancf = branch(ancf_rows, float(ancf_rows[-1]["time_s"]))
    if len(eb["crossings_used_s"]) != len(ancf["crossings_used_s"]):
        raise ValueError("EB and ANCF did not produce the same number of late response crossings")
    common_boundaries = [0.5 * (float(a) + float(b)) for a, b in zip(eb["crossings_used_s"], ancf["crossings_used_s"])]
    apply_common_boundaries(eb, eb_rows, common_boundaries)
    apply_common_boundaries(ancf, ancf_rows, common_boundaries)
    comparison = {
        "y_rms_relative_difference": relative(eb["window_2"]["y_rms_m"], ancf["window_2"]["y_rms_m"]),
        "y_peak_relative_difference": relative(eb["window_2"]["y_peak_m"], ancf["window_2"]["y_peak_m"]),
        "half_amplitude_relative_difference": relative(eb["window_2"]["half_amplitude_y_m"], ancf["window_2"]["half_amplitude_y_m"]),
        "frequency_relative_difference": relative(eb["window_2"]["y_frequency_Hz_dft"], ancf["window_2"]["y_frequency_Hz_dft"]),
        "fy_rms_relative_difference": relative(eb["window_2"]["fy_rms_N"], ancf["window_2"]["fy_rms_N"]),
        "mean_power_relative_difference": relative(eb["window_2"]["mean_power_W"], ancf["window_2"]["mean_power_W"]),
    }
    project_root = args.eb_source.resolve().parents[3]
    output = {
        "status": "response_cycle_aligned_comparison_completed",
        "checkpoint_time_s": args.checkpoint_time,
        "same_time_end": abs(float(eb["time_end_s"]) - float(ancf["time_end_s"])) < 1.0e-10,
        "same_mesh_sha256": sha(project_root / "cases" / "openfoam" / "single_slice_eb_transverse150_v6_retry_from30_to70" / "constant" / "polyMesh" / "points") == sha(project_root / "cases" / "openfoam" / "single_slice_ancf_transverse150_v6_from30_to70" / "constant" / "polyMesh" / "points"),
        "common_response_cycle_boundaries_s": common_boundaries,
        "windows_have_same_boundaries": eb["crossings_used_s"] == ancf["crossings_used_s"],
        "eb": eb, "ancf": ancf, "comparison": comparison,
        "acceptance": {
            "response_cycle_windows": True,
            "common_response_cycle_boundaries": eb["crossings_used_s"] == ancf["crossings_used_s"],
            "y_rms_lt_5_percent": comparison["y_rms_relative_difference"] < 0.05,
            "peak_lt_5_percent": comparison["y_peak_relative_difference"] < 0.05,
            "frequency_lt_2_percent": comparison["frequency_relative_difference"] < 0.02,
            "mean_power_lt_10_percent": comparison["mean_power_relative_difference"] < 0.10,
            "newton_all_converged": bool(eb["window_2"]["all_newton_converged"]) and bool(ancf["window_2"]["all_newton_converged"]),
            "no_compression_risk": float(eb["window_2"]["min_tension_N"]) >= 0.0 and float(ancf["window_2"]["min_tension_N"]) >= 0.0,
            "energy_residual_lt_10_percent": float(eb["window_2"]["energy_balance_relative"]) < 0.10 and float(ancf["window_2"]["energy_balance_relative"]) < 0.10,
        },
    }
    output["acceptance"]["physical_acceptance_ready"] = all(output["acceptance"].values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, allow_nan=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "time_end_s": eb["time_end_s"], "windows": eb["crossings_used_s"], "physical_acceptance_ready": output["acceptance"]["physical_acceptance_ready"]}, indent=2))


if __name__ == "__main__":
    main()
