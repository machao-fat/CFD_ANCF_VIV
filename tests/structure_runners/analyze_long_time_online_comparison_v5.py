"""Analyze independent long EB/ANCF online audits without conflating errors."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path

try:
    from tests.sdof.analyze_campaign import dominant_frequency
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdof"))
    from analyze_campaign import dominant_frequency


def read(path: Path) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = []
        for row in csv.DictReader(stream):
            converted: dict[str, object] = {}
            for key, value in row.items():
                if key in {"force_representation", "status"}:
                    converted[key] = value
                elif key in {"compression_risk", "structure_converged"}:
                    converted[key] = value.strip().lower() == "true"
                else:
                    converted[key] = float(value)
            rows.append(converted)
    return rows


def select(rows: list[dict[str, object]], start: float, end: float) -> list[dict[str, object]]:
    result = [row for row in rows if start - 1e-12 <= float(row["time_s"]) <= end + 1e-12]
    if not result or abs(float(result[0]["time_s"]) - start) > 1e-9 or abs(float(result[-1]["time_s"]) - end) > 1e-9:
        raise ValueError(f"incomplete online window {start}->{end}")
    return result


def trap(rows: list[dict[str, object]], key: str) -> float:
    return sum(0.5 * (float(rows[i - 1][key]) + float(rows[i][key])) * (float(rows[i]["time_s"]) - float(rows[i - 1]["time_s"])) for i in range(1, len(rows)))


def max_cfl(path: Path) -> float:
    pattern = re.compile(r"Courant Number mean:\s*[-+0-9.eE]+\s+max:\s*([-+0-9.eE]+)")
    return max((float(match.group(1)) for match in (pattern.search(line) for line in path.read_text(encoding="utf-8", errors="replace").splitlines()) if match), default=float("nan"))


def branch_metrics(rows: list[dict[str, object]], start: float, end: float, cfl_log: Path) -> dict[str, object]:
    selected = select(rows, start, end)
    dt = statistics.fmean(float(selected[i]["time_s"]) - float(selected[i - 1]["time_s"]) for i in range(1, len(selected)))
    y = [float(row["corrected_y_m"]) for row in selected]
    fy = [float(row["force_y_N"]) for row in selected]
    frequency = dominant_frequency(y, dt, fmin=0.01)
    return {
        "window_start_s": start, "window_end_s": end, "samples": len(selected), "dt_s": dt,
        "y_rms_m": math.sqrt(statistics.fmean(value * value for value in y)),
        "y_peak_m": max(abs(value) for value in y),
        "force_y_rms_N": math.sqrt(statistics.fmean(value * value for value in fy)),
        "response_frequency_Hz_dft": frequency,
        "mean_power_W": statistics.fmean(float(row["power_structure_corrected_W"]) for row in selected),
        "fluid_work_J": trap(selected, "power_structure_corrected_W"),
        "damping_dissipation_J": float(selected[-1]["damping_dissipation_J"]) - float(selected[0]["damping_dissipation_J"]),
        "mechanical_energy_change_J": float(selected[-1]["mechanical_energy_J"]) - float(selected[0]["mechanical_energy_J"]),
        "energy_balance_residual_J": trap(selected, "power_structure_corrected_W") - (float(selected[-1]["mechanical_energy_J"]) - float(selected[0]["mechanical_energy_J"])) - (float(selected[-1]["damping_dissipation_J"]) - float(selected[0]["damping_dissipation_J"])),
        "max_relative_residual": max(float(row["structure_relative_residual"]) for row in selected),
        "min_tension_N": min(float(row["min_tension_N"]) for row in selected),
        "max_slope": max(float(row["max_slope"]) for row in selected),
        "all_newton_converged": all(bool(row["structure_converged"]) for row in selected),
        "compression_risk": any(bool(row["compression_risk"]) for row in selected),
        "max_cfl": max_cfl(cfl_log),
    }


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eb-audit", type=Path, required=True)
    parser.add_argument("--ancf-audit", type=Path, required=True)
    parser.add_argument("--eb-log", type=Path, required=True)
    parser.add_argument("--ancf-log", type=Path, required=True)
    parser.add_argument("--eb-mesh", type=Path, required=True)
    parser.add_argument("--ancf-mesh", type=Path, required=True)
    parser.add_argument("--window-1", type=float, nargs=2, required=True)
    parser.add_argument("--window-2", type=float, nargs=2, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    eb_rows, ancf_rows = read(args.eb_audit), read(args.ancf_audit)
    common_end = min(float(eb_rows[-1]["time_s"]), float(ancf_rows[-1]["time_s"]))
    eb = branch_metrics(eb_rows, *args.window_1, args.eb_log)
    ancf = branch_metrics(ancf_rows, *args.window_1, args.ancf_log)
    eb2 = branch_metrics(eb_rows, *args.window_2, args.eb_log)
    ancf2 = branch_metrics(ancf_rows, *args.window_2, args.ancf_log)

    def rel(a: float, b: float) -> float:
        return abs(a - b) / max(abs(a), 1e-30)

    comparison = {
        "window_1": {"eb": eb, "ancf": ancf},
        "window_2": {"eb": eb2, "ancf": ancf2},
        "structure_model_difference": {
            "y_rms_relative": rel(float(eb2["y_rms_m"]), float(ancf2["y_rms_m"])),
            "peak_relative": rel(float(eb2["y_peak_m"]), float(ancf2["y_peak_m"])),
            "frequency_relative": rel(float(eb2["response_frequency_Hz_dft"]), float(ancf2["response_frequency_Hz_dft"])),
            "mean_power_relative": rel(float(eb2["mean_power_W"]), float(ancf2["mean_power_W"])),
        },
        "independent_cfd_feedback_difference": {
            "force_y_rms_relative": rel(float(eb2["force_y_rms_N"]), float(ancf2["force_y_rms_N"])),
            "eb_force_y_rms_N": eb2["force_y_rms_N"], "ancf_force_y_rms_N": ancf2["force_y_rms_N"],
        },
    }
    observed_frequency = min(float(eb2["response_frequency_Hz_dft"]), float(ancf2["response_frequency_Hz_dft"]))
    window_1_cycles = (args.window_1[1] - args.window_1[0]) * observed_frequency
    window_2_cycles = (args.window_2[1] - args.window_2[0]) * observed_frequency
    two_windows = common_end >= max(args.window_2) and float(eb_rows[-1]["time_s"]) >= max(args.window_2) and float(ancf_rows[-1]["time_s"]) >= max(args.window_2)
    physical_amplitude = min(float(eb2["y_rms_m"]), float(ancf2["y_rms_m"])) > 1e-5
    comparison["acceptance"] = {
        "two_adjacent_late_windows_available": two_windows,
        "five_effective_structural_cycles_per_window": window_1_cycles >= 5.0 and window_2_cycles >= 5.0,
        "physical_amplitude_identifiable": physical_amplitude,
        "rms_difference_lt_5_percent": comparison["structure_model_difference"]["y_rms_relative"] < 0.05,
        "peak_difference_lt_5_percent": comparison["structure_model_difference"]["peak_relative"] < 0.05,
        "frequency_difference_lt_2_percent": comparison["structure_model_difference"]["frequency_relative"] < 0.02,
        "mean_power_difference_lt_10_percent": comparison["structure_model_difference"]["mean_power_relative"] < 0.10,
        "newton_and_safety_pass": all(not bool(branch["compression_risk"]) and bool(branch["all_newton_converged"]) and float(branch["max_cfl"]) < 0.5 for branch in (eb, ancf, eb2, ancf2)),
    }
    comparison["acceptance"]["physical_acceptance_ready"] = all(comparison["acceptance"].values())
    payload = {
        "status": "accepted_long_time_online_comparison" if comparison["acceptance"]["physical_acceptance_ready"] else "long_time_online_comparison_completed_but_acceptance_incomplete",
        "parameters": {"L_m": 150.0, "D_m": 1.0, "topTension_N": 1.0e6, "youngs_modulus_Pa": 2.07e11, "dt_s": 0.0025, "nElem": 10, "s_ref_m": 75.0, "load_mode": "transverse_only"},
        "time_end_s": common_end,
        "eb": {"audit": str(args.eb_audit), "mesh_sha256": sha(args.eb_mesh), "metrics_window_1": eb, "metrics_window_2": eb2},
        "ancf": {"audit": str(args.ancf_audit), "mesh_sha256": sha(args.ancf_mesh), "metrics_window_1": ancf, "metrics_window_2": ancf2},
        "same_mesh": sha(args.eb_mesh) == sha(args.ancf_mesh),
        "comparison": comparison,
        "interpretation": "Independent CFD feedback force differences are reported separately from structural-model differences; this is not a multi-slice or full-riser claim.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, allow_nan=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "time_end_s": common_end, "physical_acceptance_ready": comparison["acceptance"]["physical_acceptance_ready"]}, indent=2))


if __name__ == "__main__":
    main()
