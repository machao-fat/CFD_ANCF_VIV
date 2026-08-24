from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from analyze_campaign import read_rows
from analyze_long_sdof import max_cfl, merge_rows, metrics, trap, window


def harmonic_phase(rows: list[dict[str, float]], key: str, frequency: float) -> float:
    values = [row[key] for row in rows]
    times = [row["time_s"] for row in rows]
    mean = statistics.fmean(values)
    real = sum((value - mean) * math.cos(2.0 * math.pi * frequency * time) for value, time in zip(values, times))
    imag = -sum((value - mean) * math.sin(2.0 * math.pi * frequency * time) for value, time in zip(values, times))
    return math.atan2(imag, real)


def enrich_amplitude_phase(rows: list[dict[str, float]], item: dict[str, float], ur: float) -> dict[str, float]:
    selected = window(rows, float(item["start_s"]), float(item["end_s"]))
    y = [row["y_m"] for row in selected]
    frequency = float(item["response_frequency_Hz_dft"])
    phase_y = harmonic_phase(selected, "y_m", frequency)
    phase_f = harmonic_phase(selected, "force_y_N", frequency)
    phase_v = harmonic_phase(selected, "vy_mps", frequency)
    return {
        **item,
        "positive_peak_y_m": max(y), "negative_peak_y_m": min(y),
        "half_amplitude_y_m": 0.5 * (max(y) - min(y)),
        "A_over_D_rms": float(item["y_rms_m"]),
        "A_over_D_half_amplitude": 0.5 * (max(y) - min(y)),
        "f_over_fn_dft": float(item["response_frequency_Hz_dft"]) * ur,
        "force_displacement_phase_deg": math.degrees((phase_f - phase_y + math.pi) % (2.0 * math.pi) - math.pi),
        "force_velocity_phase_deg": math.degrees((phase_f - phase_v + math.pi) % (2.0 * math.pi) - math.pi),
    }


def cycle_audit(rows: list[dict[str, float]], start: float, end: float, ur: float) -> list[dict[str, float]]:
    period = ur
    result = []
    current = start
    while current + period <= end + 1.0e-9:
        selected = window(rows, current, current + period)
        work = trap(selected, "instantaneous_power_W")
        damping = selected[-1]["damping_dissipation_J"] - selected[0]["damping_dissipation_J"]
        mechanical = selected[-1]["mechanical_energy_J"] - selected[0]["mechanical_energy_J"]
        result.append({
            "start_s": current, "end_s": current + period,
            "fluid_work_J": work, "damping_dissipation_J": damping,
            "mechanical_energy_change_J": mechanical,
            "power_balance_relative": abs(work - damping) / max(abs(work), abs(damping), 1.0e-30),
            "energy_residual_relative": abs(work - damping - mechanical) / max(abs(work), abs(damping), abs(mechanical), 1.0e-30),
        })
        current += period
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, nargs="+", required=True)
    parser.add_argument("--log", type=Path, nargs="+", required=True)
    parser.add_argument("--ur", type=float, required=True)
    parser.add_argument("--window-1", type=float, nargs=2, required=True)
    parser.add_argument("--window-2", type=float, nargs=2, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = merge_rows(args.audit)
    w1 = enrich_amplitude_phase(rows, metrics(rows, args.window_1[0], args.window_1[1], args.ur, include_spectrum=True), args.ur)
    w2 = enrich_amplitude_phase(rows, metrics(rows, args.window_2[0], args.window_2[1], args.ur, include_spectrum=True), args.ur)

    def rel(key: str) -> float:
        return abs(float(w2[key]) - float(w1[key])) / max(abs(float(w1[key])), 1.0e-30)

    relative = {key: rel(key) for key in ("y_rms_m", "y_peak_m", "fy_rms_N", "cl_rms", "mean_power_W")}
    relative["response_frequency_Hz_zero_crossing"] = rel("response_frequency_Hz_zero_crossing")
    cycles = cycle_audit(rows, args.window_2[0], args.window_2[1], args.ur)
    last_three = [item["power_balance_relative"] for item in cycles[-3:]]
    pass_flags = {
        "y_rms_m": relative["y_rms_m"] < 0.05,
        "y_peak_m": relative["y_peak_m"] < 0.05,
        "fy_rms_N": relative["fy_rms_N"] < 0.05,
        "cl_rms": relative["cl_rms"] < 0.05,
        "mean_power_W": relative["mean_power_W"] < 0.05,
        "response_frequency_Hz_zero_crossing": relative["response_frequency_Hz_zero_crossing"] < 0.02,
        "last_three_cycle_power_balance_relative": bool(last_three) and all(value < 0.10 for value in last_three),
    }
    cfl_values = [max_cfl(path) for path in args.log]
    payload = {
        "status": "accepted_two_adjacent_five_cycle_windows" if all(pass_flags.values()) else "not_accepted_two_adjacent_five_cycle_windows",
        "ur": args.ur, "fn_Hz": 1.0 / args.ur, "period_s": args.ur,
        "time_start_s": rows[0]["time_s"], "time_end_s": rows[-1]["time_s"],
        "max_abs_y_m": max(abs(row["y_m"]) for row in rows), "max_cfl": max(cfl_values, default=float("nan")),
        "window_1": w1, "window_2": w2, "relative_changes": relative,
        "thresholds": {"amplitude_and_force": 0.05, "frequency": 0.02, "energy": 0.10},
        "final_window_cycle_energy_audit": cycles,
        "last_three_cycle_power_balance_relative": last_three,
        "criteria_pass": pass_flags, "steady_window_pass": all(pass_flags.values()),
        "physical_definition": {
            "mass_ratio": 10.0, "mass_ratio_formula": "m/(rho*pi*D^2/4)",
            "rho_kg_m3": 1000.0, "D_m": 1.0, "U_mps": 1.0,
            "damping_ratio": 0.01, "unit_span_m": 1.0,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "Ur": args.ur, "end_s": payload["time_end_s"], "steady_window_pass": payload["steady_window_pass"]}, indent=2))


if __name__ == "__main__":
    main()
