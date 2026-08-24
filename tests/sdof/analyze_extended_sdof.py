from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path

from analyze_campaign import read_rows, relative_frequency_difference, zero_crossing_frequency
from analyze_long_sdof import merge_rows, metrics


def trap(rows: list[dict[str, float]], key: str) -> float:
    return sum(
        0.5 * (rows[i - 1][key] + rows[i][key]) * (rows[i]["time_s"] - rows[i - 1]["time_s"])
        for i in range(1, len(rows))
    )


def select(rows: list[dict[str, float]], start: float, end: float) -> list[dict[str, float]]:
    selected = [row for row in rows if start - 1.0e-12 <= row["time_s"] <= end + 1.0e-12]
    if len(selected) < 2 or abs(selected[0]["time_s"] - start) > 1.0e-9 or abs(selected[-1]["time_s"] - end) > 1.0e-9:
        raise ValueError(f"missing complete block {start} -> {end}")
    return selected


def block(rows: list[dict[str, float]], start: float, end: float, ur: float) -> dict[str, object]:
    selected = select(rows, start, end)
    # A 5.2 s block is approximately one natural period at Ur=5.2, so it
    # may contain too few alternating zero crossings for a zero-crossing
    # estimate.  Keep that estimate when available, but always compute the
    # separately labelled direct-DFT estimate for the block-level record.
    base = metrics(rows, start, end, ur, include_spectrum=True)
    y = [row["y_m"] for row in selected]
    fy = [row["force_y_N"] for row in selected]
    max_cfl = None
    return {
        **base,
        "mean_y_m": statistics.fmean(y),
        "positive_peak_y_m": max(y),
        "negative_peak_y_m": min(y),
        "half_amplitude_y_m": 0.5 * (max(y) - min(y)),
        "response_frequency_method": "dft_primary",
        "lift_frequency_method": "dft_primary",
        "response_frequency_Hz": base["response_frequency_Hz_dft"],
        "lift_frequency_Hz": base["lift_frequency_Hz_dft"],
        "response_dft_zero_crossing_relative_difference": relative_frequency_difference(base["response_frequency_Hz_dft"], base["response_frequency_Hz_zero_crossing"]),
        "lift_dft_zero_crossing_relative_difference": relative_frequency_difference(base["lift_frequency_Hz_dft"], base["lift_frequency_Hz_zero_crossing"]),
        "structure_work_J": trap(selected, "instantaneous_power_W"),
        "cfd_predicted_velocity_work_J": trap(selected, "power_cfd_predicted_W"),
        "coupling_defect_work_J": trap(selected, "power_coupling_defect_W"),
        "mechanical_energy_change_J": selected[-1]["mechanical_energy_J"] - selected[0]["mechanical_energy_J"],
        "damping_dissipation_J": selected[-1]["damping_dissipation_J"] - selected[0]["damping_dissipation_J"],
        "energy_residual_structure_minus_damping_minus_mechanical_J": trap(selected, "instantaneous_power_W") - (selected[-1]["mechanical_energy_J"] - selected[0]["mechanical_energy_J"]) - (selected[-1]["damping_dissipation_J"] - selected[0]["damping_dissipation_J"]),
        "all_finite": all(math.isfinite(value) for row in selected for value in row.values()),
        "fy_rms_N": math.sqrt(statistics.fmean(value * value for value in fy)),
    }


def parse_cfl(log: Path) -> list[tuple[float, float]]:
    cfl_re = re.compile(r"Courant Number mean:\s*[-+0-9.eE]+\s+max:\s*([-+0-9.eE]+)")
    time_re = re.compile(r"Time =\s*([-+0-9.eE]+)s")
    latest = None
    result = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        match = cfl_re.search(line)
        if match:
            latest = float(match.group(1))
        match = time_re.search(line)
        if match and latest is not None:
            result.append((float(match.group(1)), latest))
    return result


def segment_continuity(rows: list[dict[str, float]], boundaries: list[float], dt: float) -> list[dict[str, object]]:
    records = []
    for boundary in boundaries:
        before = min((row for row in rows if row["time_s"] < boundary), key=lambda row: abs(row["time_s"] - (boundary - dt)), default=None)
        after = min((row for row in rows if row["time_s"] > boundary), key=lambda row: abs(row["time_s"] - (boundary + dt)), default=None)
        if before is None or after is None:
            records.append({"boundary_s": boundary, "available": False})
            continue
        records.append({
            "boundary_s": boundary, "available": True,
            "step_before": int(before["step"]), "step_after": int(after["step"]),
            "time_gap_s": after["time_s"] - before["time_s"],
            "y_jump_over_one_dt_m": after["y_m"] - before["y_m"],
            "vy_jump_over_one_dt_mps": after["vy_mps"] - before["vy_mps"],
            "ay_jump_over_one_dt_mps2": after["ay_mps2"] - before["ay_mps2"],
            "force_jump_over_one_dt_N": after["force_y_N"] - before["force_y_N"],
            "fluid_work_jump_J": after["fluid_work_J"] - before["fluid_work_J"],
            "damping_jump_J": after["damping_dissipation_J"] - before["damping_dissipation_J"],
            "mechanical_energy_jump_J": after["mechanical_energy_J"] - before["mechanical_energy_J"],
        })
    return records


def final_cycle_audit(rows: list[dict[str, float]], start: float, end: float, ur: float, cfl_series: list[tuple[float, float]]) -> list[dict[str, object]]:
    result = []
    cycle_length = 1.0 / (1.0 / (ur * 1.0))
    current = start
    index = 1
    while current + cycle_length <= end + 1.0e-9:
        item = metrics(rows, current, current + cycle_length, ur, include_spectrum=False)
        selected = select(rows, current, current + cycle_length)
        work = trap(selected, "instantaneous_power_W")
        damping = selected[-1]["damping_dissipation_J"] - selected[0]["damping_dissipation_J"]
        mechanical = selected[-1]["mechanical_energy_J"] - selected[0]["mechanical_energy_J"]
        cfl_values = [value for time_s, value in cfl_series if current - 1.0e-9 <= time_s <= current + cycle_length + 1.0e-9]
        result.append({
            "cycle_index": index, "start_s": current, "end_s": current + cycle_length,
            "y_rms_m": item["y_rms_m"], "y_peak_m": item["y_peak_m"],
            "fy_rms_N": item["fy_rms_N"], "cl_rms": item["cl_rms"],
            "response_frequency_Hz_zero_crossing": item["response_frequency_Hz_zero_crossing"],
            "response_frequency_Hz_dft": item["response_frequency_Hz_dft"],
            "mean_power_W": item["mean_power_W"], "structure_work_J": work,
            "damping_dissipation_J": damping, "mechanical_energy_change_J": mechanical,
            "power_balance_structure_minus_damping_J": work - damping,
            "energy_residual_structure_minus_damping_minus_mechanical_J": work - damping - mechanical,
            "power_balance_relative": abs(work - damping) / max(abs(work), abs(damping), 1.0e-30),
            "energy_residual_relative": abs(work - damping - mechanical) / max(abs(work), abs(damping), abs(mechanical), 1.0e-30),
            "max_cfl": max(cfl_values, default=float("nan")),
        })
        current += cycle_length
        index += 1
    return result


def enrich_window_amplitude(rows: list[dict[str, float]], item: dict[str, float] | None) -> dict[str, float] | None:
    if item is None:
        return None
    selected = select(rows, float(item["start_s"]), float(item["end_s"]))
    y = [row["y_m"] for row in selected]
    return {
        **item, "positive_peak_y_m": max(y), "negative_peak_y_m": min(y),
        "half_amplitude_y_m": 0.5 * (max(y) - min(y)),
        "A_over_D_rms": float(item["y_rms_m"]), "A_over_D_half_amplitude": 0.5 * (max(y) - min(y)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segments", type=Path, nargs="+", required=True)
    parser.add_argument("--log", type=Path, nargs="+", required=True)
    parser.add_argument("--ur", type=float, default=5.2)
    parser.add_argument("--final-time", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = merge_rows(args.segments)
    dt = statistics.fmean(rows[i]["time_s"] - rows[i - 1]["time_s"] for i in range(1, len(rows)))
    blocks = []
    start = 2.0
    while start + 5.2 <= args.final_time + 1.0e-9:
        blocks.append(block(rows, start, start + 5.2, args.ur))
        start += 5.2
    final_window_1 = enrich_window_amplitude(rows, metrics(rows, 60.0, 86.0, args.ur, include_spectrum=True)) if args.final_time >= 86.0 else None
    final_window_2 = enrich_window_amplitude(rows, metrics(rows, 86.0, 112.0, args.ur, include_spectrum=True)) if args.final_time >= 112.0 else None
    cfl_series = []
    for log in args.log:
        cfl_series.extend(parse_cfl(log))
    cfl_series.sort(key=lambda item: item[0])
    for item in blocks:
        values = [value for time_s, value in cfl_series if item["start_s"] - 1.0e-9 <= time_s <= item["end_s"] + 1.0e-9]
        item["max_cfl_observed"] = max(values, default=max((value for _, value in cfl_series), default=float("nan")))
        item["mesh_safety_status"] = "requires_checkMesh_at_block_boundary"
    final_cycle_1 = final_cycle_audit(rows, 60.0, 86.0, args.ur, cfl_series) if args.final_time >= 86.0 else []
    final_cycle_2 = final_cycle_audit(rows, 86.0, 112.0, args.ur, cfl_series) if args.final_time >= 112.0 else []
    comparison = None
    if final_window_1 is not None and final_window_2 is not None:
        def relative(key: str) -> float:
            return abs(float(final_window_2[key]) - float(final_window_1[key])) / max(abs(float(final_window_1[key])), 1.0e-30)
        comparison = {
            "window_1": "60-86 s", "window_2": "86-112 s",
            "relative_changes": {
                key: relative(key) for key in ("y_rms_m", "y_peak_m", "fy_rms_N", "cl_rms", "mean_power_W")
            } | {"response_frequency_Hz_zero_crossing": relative("response_frequency_Hz_zero_crossing")},
            "thresholds": {"y_rms_m": 0.05, "y_peak_m": 0.05, "fy_rms_N": 0.05, "cl_rms": 0.05, "mean_power_W": 0.05, "response_frequency_Hz_zero_crossing": 0.02, "last_three_cycle_power_balance_relative": 0.10},
            "last_three_cycle_power_balance_relative": [item["power_balance_relative"] for item in final_cycle_2[-3:]],
        }
        comparison["criteria_pass"] = {key: value < comparison["thresholds"][key] for key, value in comparison["relative_changes"].items()}
        comparison["criteria_pass"]["last_three_cycle_power_balance_relative"] = all(value < 0.10 for value in comparison["last_three_cycle_power_balance_relative"])
        comparison["steady_window_pass"] = all(comparison["criteria_pass"].values())
    payload = {
        "status": "pending_extended_final_windows" if final_window_2 is None else "extended_windows_analyzed",
        "ur": args.ur, "fn_Hz": 1.0 / (args.ur * 1.0), "dt_s": dt,
        "time_start_s": rows[0]["time_s"], "time_end_s": rows[-1]["time_s"],
        "blocks_5p2s": blocks,
        "final_window_60_to_86": final_window_1,
        "final_window_86_to_112": final_window_2,
        "final_cycle_energy_audit_60_to_86": final_cycle_1,
        "final_cycle_energy_audit_86_to_112": final_cycle_2,
        "final_window_comparison": comparison,
        "segment_continuity": segment_continuity(rows, [10.0, 32.5, 60.0, 90.0], dt),
        "physical_parameter_audit": {
            "rho_kg_m3": 1000.0, "D_m": 1.0, "span_m": 1.0,
            "mass_kg": 7853.981633974482, "mass_ratio_definition": "m/(rho*pi*D^2/4)",
            "mass_ratio": 10.0, "Ur": args.ur,
            "fn_Hz": 1.0 / (args.ur * 1.0),
            "stiffness_N_m": 11466.818298927445,
            "damping_N_s_m": 189.80008463633376,
            "force_reference_scale_N": 0.5 * 1000.0 * 1.0**2 * 1.0,
            "two_dimensional_unit_span": True,
        },
        "frequency_methods": {
            "zero_crossing": "corrected 1/mean(full-period intervals)",
            "dft": "direct-DFT spectral scan in final windows",
            "legacy_v3_frequency": "0.36-0.38 Hz values are invalid doubled zero-crossing results",
        },
        "safety": {"max_abs_y_m": max(abs(row["y_m"]) for row in rows), "max_cfl": max((value for _, value in cfl_series), default=float("nan")), "limits": {"max_abs_y_m": 1.5, "max_cfl": 0.5}},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "blocks": len(blocks), "time_end_s": payload["time_end_s"]}, indent=2))


if __name__ == "__main__":
    main()
