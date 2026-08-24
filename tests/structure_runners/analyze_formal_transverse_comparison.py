from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path


def read(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def rms(values):
    return math.sqrt(statistics.fmean(value * value for value in values))


def dominant_frequency(values, times, fmin=0.01, fmax=1.0):
    if len(values) < 8:
        return 0.0
    dt = statistics.fmean(times[i] - times[i - 1] for i in range(1, len(times)))
    span = times[-1] - times[0]
    values = [value - statistics.fmean(values) for value in values]
    best_f, best_a = 0.0, -1.0
    steps = 4000
    for index in range(steps + 1):
        f = fmin + (fmax - fmin) * index / steps
        c = sum(value * math.cos(2 * math.pi * f * i * dt) for i, value in enumerate(values))
        s = sum(value * math.sin(2 * math.pi * f * i * dt) for i, value in enumerate(values))
        amplitude = c * c + s * s
        if amplitude > best_a:
            best_a, best_f = amplitude, f
    return best_f


def phase_at(values, forces, times, frequency):
    if frequency <= 0:
        return None
    dt = statistics.fmean(times[i] - times[i - 1] for i in range(1, len(times)))
    def phase(signal):
        signal = [value - statistics.fmean(signal) for value in signal]
        c = sum(value * math.cos(2 * math.pi * frequency * i * dt) for i, value in enumerate(signal))
        s = sum(value * math.sin(2 * math.pi * frequency * i * dt) for i, value in enumerate(signal))
        return math.atan2(-s, c)
    return math.degrees((phase(forces) - phase(values) + math.pi) % (2 * math.pi) - math.pi)


def sha(path: Path):
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def branch(case, result, window_start):
    rows = read(result / "coupling_audit.csv")
    selected = [row for row in rows if float(row["time_s"]) >= window_start]
    times = [float(row["time_s"]) for row in selected]
    y = [float(row["corrected_y_m"]) for row in selected]
    fy = [float(row["force_y_N"]) for row in selected]
    f_y = dominant_frequency(y, times)
    f_f = dominant_frequency(fy, times)
    return {
        "case": str(case.resolve()),
        "result": str(result.resolve()),
        "steps": len(rows),
        "time_end_s": float(rows[-1]["time_s"]),
        "window_start_s": window_start,
        "window_end_s": float(rows[-1]["time_s"]),
        "window_cycles_at_0p155Hz": (float(rows[-1]["time_s"]) - window_start) * 0.155,
        "y_rms_m": rms(y),
        "y_peak_m": max(abs(value) for value in y),
        "fy_rms_N": rms(fy),
        "fy_mean_N": statistics.fmean(fy),
        "y_frequency_Hz": f_y,
        "fy_frequency_Hz": f_f,
        "phase_Fy_minus_y_deg": phase_at(y, fy, times, f_y),
        "mean_power_W": statistics.fmean(float(row["power_structure_corrected_W"]) for row in selected),
        "coupling_defect_work_J_window": float(selected[-1]["coupling_defect_work_J"]) - float(selected[0]["coupling_defect_work_J"]),
        "max_relative_residual": max(float(row["structure_relative_residual"]) for row in selected),
        "min_tension_N": min(float(row["min_tension_N"]) for row in rows),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eb-case", type=Path, required=True)
    parser.add_argument("--eb-result", type=Path, required=True)
    parser.add_argument("--ancf-case", type=Path, required=True)
    parser.add_argument("--ancf-result", type=Path, required=True)
    parser.add_argument("--window-start", type=float, default=5.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    eb = branch(args.eb_case, args.eb_result, args.window_start)
    ancf = branch(args.ancf_case, args.ancf_result, args.window_start)
    output = {
        "status": "formal_online_trend_not_steady_acceptance",
        "same_time_grid": eb["steps"] == ancf["steps"] and eb["time_end_s"] == ancf["time_end_s"],
        "same_mesh_sha256": sha(args.eb_case / "constant" / "polyMesh" / "points") == sha(args.ancf_case / "constant" / "polyMesh" / "points"),
        "independent_cfd_force_note": "EB and ANCF were run as separate CFD processes; Fy values are not assumed identical.",
        "comparison": {
            "y_rms_relative_difference": abs(eb["y_rms_m"] - ancf["y_rms_m"]) / max(eb["y_rms_m"], 1e-30),
            "y_peak_relative_difference": abs(eb["y_peak_m"] - ancf["y_peak_m"]) / max(eb["y_peak_m"], 1e-30),
            "frequency_relative_difference": abs(eb["y_frequency_Hz"] - ancf["y_frequency_Hz"]) / max(eb["y_frequency_Hz"], 1e-30),
            "mean_power_relative_difference": abs(eb["mean_power_W"] - ancf["mean_power_W"]) / max(abs(eb["mean_power_W"]), 1e-30),
        },
        "eb": eb,
        "ancf": ancf,
        "acceptance": {
            "visible_response_above_1e_minus_5_m": eb["y_peak_m"] > 1e-5 and ancf["y_peak_m"] > 1e-5,
            "at_least_two_first_mode_cycles": eb["window_cycles_at_0p155Hz"] >= 2.0 and ancf["window_cycles_at_0p155Hz"] >= 2.0,
            "rms_and_frequency_below_5_percent": (
                abs(eb["y_rms_m"] - ancf["y_rms_m"]) / max(eb["y_rms_m"], 1e-30) < 0.05
                and abs(eb["y_frequency_Hz"] - ancf["y_frequency_Hz"]) / max(eb["y_frequency_Hz"], 1e-30) < 0.05
            ),
            "physical_acceptance_ready": False,
        },
        "limitation": "The 5-10 s window contains about 0.775 first-mode cycles; the 0-10 s run contains about 1.55 cycles. Extend to at least 2-3 cycles before physical acceptance.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
