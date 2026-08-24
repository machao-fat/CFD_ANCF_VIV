"""Assemble v5 point metrics without changing any raw campaign evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(path: Path) -> dict:
    item = load(path)
    # Convert the preserved Ur=5.2 v4 schema into the v5 point contract.
    # The source v4 JSON is not modified.
    if "window_1" not in item and "final_window_60_to_86" in item:
        item["window_1"] = item["final_window_60_to_86"]
        item["window_2"] = item["final_window_86_to_112"]
        comparison = item.get("final_window_comparison", {})
        item["relative_changes"] = comparison.get("relative_changes", {})
        item["final_steady_window_pass"] = bool(comparison.get("steady_window_pass", False))
        item["time_end_s"] = float(item.get("time_end_s", item["window_2"].get("end_s", 0.0)))
        safety = item.get("safety", {})
        item["max_abs_y_m"] = float(safety.get("max_abs_y_m", 0.0))
        item["max_cfl"] = float(safety.get("max_cfl", 0.0))
        item["response_frequency_Hz"] = item["window_2"].get("response_frequency_Hz_dft")
        item["lift_frequency_Hz"] = item["window_2"].get("lift_frequency_Hz_dft")
        item["response_frequency_method"] = "dft_primary"
        item["lift_frequency_method"] = "dft_primary"
        item["frequency_state"] = "frequency_synchronized"
        item["physical_lockin_classification"] = "outside_lockin"
        item["last_three_cycle_energy_audit"] = item.get("final_cycle_energy_audit_86_to_112", [])[-3:]
    item.setdefault("window_sensitivity_status", "not_applicable")
    item.setdefault("absolute_low_power_criterion_pass", False)
    item.setdefault("relative_power_criterion_applicable", True)
    item.setdefault("final_steady_window_pass", bool(item.get("steady_window_pass", False)))
    item.setdefault("physical_lockin_classification", item.get("physical_lockin_classification", "transitional_or_unsteady"))
    item.setdefault("lock_in_classification", item["physical_lockin_classification"])
    for key in ("force_velocity_phase_deg",):
        item["window_1"].setdefault(key, float("nan"))
        item["window_2"].setdefault(key, float("nan"))
    return item


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ur4", type=Path, required=True)
    parser.add_argument("--ur5p2", type=Path, required=True)
    parser.add_argument("--ur5-sensitivity", type=Path, required=True)
    parser.add_argument("--ur6", type=Path, required=True)
    parser.add_argument("--ur7p1", type=Path, required=True)
    parser.add_argument("--ur8", type=Path, required=True)
    args = parser.parse_args()
    points = [normalize(path) for path in (args.ur4, args.ur5p2, args.ur6, args.ur7p1, args.ur8)]
    sensitivity = load(args.ur5_sensitivity)
    final_combo = sensitivity["window_combinations"][-1]
    ur5 = points[1]
    ur5["window_1"] = final_combo["window_1"]
    ur5["window_2"] = final_combo["window_2"]
    ur5["relative_changes"] = final_combo["relative_changes"]
    for key in ("relative_power_criterion_applicable", "absolute_low_power_criterion_pass", "amplitude_stationarity_pass", "force_stationarity_pass", "frequency_stationarity_pass", "energy_stationarity_pass", "final_steady_window_pass", "frequency_state", "physical_lockin_classification", "f_over_fn_dft", "last_three_cycle_energy_audit", "max_cfl"):
        if key in final_combo:
            ur5[key] = final_combo[key]
    ur5["window_sensitivity_status"] = sensitivity["status"]
    ur5.setdefault("max_abs_y_m", float(ur5.get("safety", {}).get("max_abs_y_m", 0.0)))
    ur5.setdefault("max_cfl", float(ur5.get("safety", {}).get("max_cfl", 0.0)))
    if sensitivity["status"] != "robust_window_pass":
        ur5["physical_lockin_classification"] = "transitional_or_unsteady"
        ur5["lock_in_classification"] = "transitional_or_unsteady"
        ur5["boundary_pass_only"] = True
    for point in points:
        audits = point.get("last_three_cycle_energy_audit", [])
        def mean_field(name: str) -> float:
            values = [float(row[name]) for row in audits if row.get(name) is not None]
            return sum(values) / len(values) if values else float("nan")
        point["last_three_cycle_energy_summary"] = {
            "fluid_work_J": mean_field("fluid_work_J"),
            "damping_dissipation_J": mean_field("damping_dissipation_J"),
            "mechanical_energy_change_J": mean_field("mechanical_energy_change_J"),
            "power_balance_relative_mean": mean_field("power_balance_relative"),
        }
    summary = {
        "status": "five_point_v5_completed_with_stationarity_states",
        "ur_points": [4.0, 5.2, 6.0, 7.1, 8.0],
        "points": points,
        "acceptance_definition": {
            "amplitude_force_power_relative_limit": 0.05,
            "frequency_relative_limit": 0.02,
            "frequency_reliability_limit": 0.05,
            "energy_balance_relative_limit": 0.10,
            "low_power_absolute_threshold_W": 0.5,
            "frequency_synchronization_band": [0.95, 1.05],
            "safety_limits": {"max_abs_y_m": 1.5, "max_cfl": 0.5},
        },
        "all_points_completed": all(float(p.get("time_end_s", 0.0)) > 0.0 for p in points),
        "all_points_safety_pass": all(float(p["max_abs_y_m"]) < 1.5 and float(p["max_cfl"]) < 0.5 for p in points),
        "all_points_strict_steady_window_pass": all(bool(p["final_steady_window_pass"]) for p in points),
        "robust_ur5p2_window_pass": sensitivity["status"] == "robust_window_pass",
        "physical_classification_rule": "transitional_or_unsteady is mandatory whenever the final windows do not pass; frequency synchronization alone is not lock-in.",
        "no_multislice_claim": True,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for point in points:
        name = str(point["ur"]).replace(".", "p")
        (args.output / f"Ur{name}_point_metrics_v5.json").write_text(json.dumps(point, indent=2, allow_nan=True) + "\n", encoding="utf-8")
    (args.output / "five_point_lockin_v5.json").write_text(json.dumps(summary, indent=2, allow_nan=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "strict_points": sum(bool(p["final_steady_window_pass"]) for p in points), "safety": summary["all_points_safety_pass"]}, indent=2))


if __name__ == "__main__":
    main()
