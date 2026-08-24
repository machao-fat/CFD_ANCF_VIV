"""Stage-three v5 SDOF window audit and two-level lock-in classification."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from analyze_campaign import frequency_reliable, read_rows, relative_frequency_difference
from analyze_long_sdof import max_cfl, merge_rows, metrics, trap, window


def harmonic_phase(rows: list[dict[str, float]], key: str, frequency: float) -> float:
    values = [row[key] for row in rows]
    times = [row["time_s"] for row in rows]
    mean = statistics.fmean(values)
    real = sum((value - mean) * math.cos(2.0 * math.pi * frequency * time) for value, time in zip(values, times))
    imag = -sum((value - mean) * math.sin(2.0 * math.pi * frequency * time) for value, time in zip(values, times))
    return math.atan2(imag, real)


def enrich(rows: list[dict[str, float]], item: dict[str, float], ur: float) -> dict[str, object]:
    selected = window(rows, float(item["start_s"]), float(item["end_s"]))
    y = [row["y_m"] for row in selected]
    frequency = float(item["response_frequency_Hz_dft"])
    return {
        **item,
        "positive_peak_y_m": max(y),
        "negative_peak_y_m": min(y),
        "half_amplitude_y_m": 0.5 * (max(y) - min(y)),
        "A_over_D_rms": float(item["y_rms_m"]),
        "A_over_D_half_amplitude": 0.5 * (max(y) - min(y)),
        "f_over_fn_dft": frequency * ur,
        "force_displacement_phase_deg": math.degrees((harmonic_phase(selected, "force_y_N", frequency) - harmonic_phase(selected, "y_m", frequency) + math.pi) % (2.0 * math.pi) - math.pi),
        "force_velocity_phase_deg": math.degrees((harmonic_phase(selected, "force_y_N", frequency) - harmonic_phase(selected, "vy_mps", frequency) + math.pi) % (2.0 * math.pi) - math.pi),
    }


def cycle_audit(rows: list[dict[str, float]], start: float, end: float, ur: float) -> list[dict[str, float]]:
    result = []
    current = start
    while current + ur <= end + 1.0e-9:
        selected = window(rows, current, current + ur)
        work = trap(selected, "instantaneous_power_W")
        damping = selected[-1]["damping_dissipation_J"] - selected[0]["damping_dissipation_J"]
        mechanical = selected[-1]["mechanical_energy_J"] - selected[0]["mechanical_energy_J"]
        result.append({
            "start_s": current,
            "end_s": current + ur,
            "fluid_work_J": work,
            "damping_dissipation_J": damping,
            "mechanical_energy_change_J": mechanical,
            "power_balance_relative": abs(work - damping) / max(abs(work), abs(damping), 1.0e-30),
            "energy_residual_relative": abs(work - damping - mechanical) / max(abs(work), abs(damping), abs(mechanical), 1.0e-30),
        })
        current += ur
    return result


def audit(rows: list[dict[str, float]], logs: list[Path], ur: float, start1: float, end1: float, start2: float, end2: float) -> dict[str, object]:
    w1 = enrich(rows, metrics(rows, start1, end1, ur, include_spectrum=True), ur)
    w2 = enrich(rows, metrics(rows, start2, end2, ur, include_spectrum=True), ur)

    def rel(key: str) -> float:
        return abs(float(w2[key]) - float(w1[key])) / max(abs(float(w1[key])), 1.0e-30)

    relative = {
        "y_rms_m": rel("y_rms_m"),
        "y_peak_m": rel("y_peak_m"),
        "half_amplitude_y_m": rel("half_amplitude_y_m"),
        "fy_rms_N": rel("fy_rms_N"),
        "cl_rms": rel("cl_rms"),
        "mean_power_W": rel("mean_power_W"),
        "response_frequency_Hz_dft": rel("response_frequency_Hz_dft"),
    }
    cycles = cycle_audit(rows, start2, end2, ur)
    last_three = cycles[-3:]
    power1 = abs(float(w1["mean_power_W"]))
    power2 = abs(float(w2["mean_power_W"]))
    relative_power_criterion_applicable = power1 >= 0.5 and power2 >= 0.5
    amplitude_stationarity_pass = relative["y_rms_m"] < 0.05 and relative["y_peak_m"] < 0.05 and relative["half_amplitude_y_m"] < 0.05
    force_stationarity_pass = relative["fy_rms_N"] < 0.05 and relative["cl_rms"] < 0.05
    frequency_stationarity_pass = (
        relative["response_frequency_Hz_dft"] < 0.02
        and bool(w1["response_frequency_reliable"])
        and bool(w2["response_frequency_reliable"])
    )
    energy_stationarity_pass = bool(last_three) and all(float(item["power_balance_relative"]) < 0.10 for item in last_three)
    mechanical_changes = [float(item["mechanical_energy_change_J"]) for item in last_three]
    no_persistent_mechanical_growth = not (
        len(mechanical_changes) >= 3
        and all(value > 0.0 for value in mechanical_changes)
        and mechanical_changes[-1] >= mechanical_changes[0]
    )
    absolute_low_power_criterion_pass = (
        not relative_power_criterion_applicable
        and power1 < 0.5
        and power2 < 0.5
        and no_persistent_mechanical_growth
        and amplitude_stationarity_pass
        and force_stationarity_pass
        and frequency_stationarity_pass
        and bool(last_three)
        and abs(statistics.fmean(mechanical_changes)) < 0.5
    )
    if relative_power_criterion_applicable:
        energy_gate = energy_stationarity_pass and relative["mean_power_W"] < 0.05
    else:
        energy_gate = absolute_low_power_criterion_pass
    final_pass = amplitude_stationarity_pass and force_stationarity_pass and frequency_stationarity_pass and energy_gate

    f_over_fn = float(w2["response_frequency_Hz_dft"]) * ur
    frequency_state = (
        "frequency_synchronized" if 0.95 <= f_over_fn <= 1.05 and frequency_stationarity_pass
        else "outside_frequency_sync" if frequency_stationarity_pass
        else "frequency_unresolved"
    )
    power_noise_floor = 0.5
    phase_value = float(w2["force_velocity_phase_deg"])
    phase_cosine = math.cos(math.radians(phase_value)) if math.isfinite(phase_value) else float("nan")
    if not final_pass:
        physical_class = "transitional_or_unsteady"
    elif frequency_state == "frequency_synchronized" and float(w2["mean_power_W"]) > power_noise_floor and math.isfinite(phase_cosine) and phase_cosine > 0.0:
        physical_class = "locked_or_near_lockin"
    else:
        physical_class = "outside_lockin"
    return {
        "window_1": w1,
        "window_2": w2,
        "relative_changes": relative,
        "relative_power_criterion_applicable": relative_power_criterion_applicable,
        "absolute_low_power_criterion_pass": absolute_low_power_criterion_pass,
        "amplitude_stationarity_pass": amplitude_stationarity_pass,
        "force_stationarity_pass": force_stationarity_pass,
        "frequency_stationarity_pass": frequency_stationarity_pass,
        "energy_stationarity_pass": energy_stationarity_pass,
        "final_steady_window_pass": final_pass,
        "frequency_state": frequency_state,
        "physical_lockin_classification": physical_class,
        "f_over_fn_dft": f_over_fn,
        "power_noise_floor_W": power_noise_floor,
        "force_velocity_phase_cosine": phase_cosine,
        "last_three_cycle_energy_audit": last_three,
        "last_three_cycle_mechanical_energy_change_J": mechanical_changes,
        "max_cfl": max((max_cfl(path) for path in logs), default=float("nan")),
    }


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
    payload = audit(rows, args.log, args.ur, *args.window_1, *args.window_2)
    payload.update({
        "status": "accepted_two_adjacent_five_cycle_windows" if payload["final_steady_window_pass"] else "completed_but_not_steady",
        "ur": args.ur,
        "fn_Hz": 1.0 / args.ur,
        "period_s": args.ur,
        "time_start_s": rows[0]["time_s"],
        "time_end_s": rows[-1]["time_s"],
        "max_abs_y_m": max(abs(row["y_m"]) for row in rows),
        "safety": {"max_abs_y_m": max(abs(row["y_m"]) for row in rows), "max_cfl": payload["max_cfl"], "limits": {"max_abs_y_m": 1.5, "max_cfl": 0.5}},
        "frequency_methods": {"response_primary": "detrended direct DFT", "response_diagnostic": "corrected alternating zero crossings", "lift_primary": "detrended direct DFT", "lift_diagnostic": "zero crossing only; never used as lift main frequency"},
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "ur": args.ur, "end_s": payload["time_end_s"], "steady": payload["final_steady_window_pass"], "classification": payload["physical_lockin_classification"]}, indent=2))


if __name__ == "__main__":
    main()
