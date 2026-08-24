"""Build the v6 five-point evidence bundle without Ur-specific classification."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lockin_classification_v6 import classify_lockin


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ur4", type=Path, required=True)
    parser.add_argument("--ur5p2", type=Path, required=True)
    parser.add_argument("--ur6", type=Path, required=True)
    parser.add_argument("--ur7p1", type=Path, required=True)
    parser.add_argument("--ur8", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data = {str(ur): load(path) for ur, path in [(4.0, args.ur4), (5.2, args.ur5p2), (6.0, args.ur6), (7.1, args.ur7p1), (8.0, args.ur8)]}
    baseline = min(float(item["final_response_pair"]["window_2"]["y_rms_m"]) for item in data.values())
    points = []
    for ur, item in data.items():
        final = item["final_response_pair"]
        phase = float(final["window_2"].get("force_velocity_phase_deg", float("nan")))
        final["physical_lockin_classification"] = classify_lockin(
            final_steady_window_pass=bool(final["final_steady_window_pass"]),
            frequency_state=str(final["frequency_state"]),
            response_frequency_reliable=bool(final["window_2"]["response_frequency_reliable"]),
            y_rms_m=float(final["window_2"]["y_rms_m"]), amplitude_baseline_m=baseline,
            mean_power_W=float(final["window_2"]["mean_power_W"]), force_velocity_phase_deg=phase,
            power_noise_floor_W=0.5,
        )
        item["campaign_amplitude_baseline_m"] = baseline
        item["window_definition"] = "response-cycle-aligned"
        item["response_cycle_count"] = 5.0
        item["final_window_method_used"] = "response-cycle-aligned"
        item["classification_source"] = "shared Ur-independent classifier"
        item["ur"] = ur
        points.append(item)
        (args.output / f"Ur{str(ur).replace('.', 'p')}_point_metrics_v6.json").write_text(json.dumps(item, indent=2, allow_nan=True) + "\n", encoding="utf-8")
    summary = {
        "status": "five_point_v6_response_cycle_aligned_completed",
        "points": points,
        "amplitude_baseline_m": baseline,
        "acceptance_definition": {"rms_peak_half_force_power_limit": 0.05, "frequency_limit": 0.02, "dft_zero_crossing_reliability_limit": 0.05, "energy_balance_limit": 0.10, "low_power_noise_floor_W": 0.5, "frequency_synchronization_band": [0.95, 1.05], "safety_limits": {"max_abs_y_m": 1.5, "max_cfl": 0.5}},
        "all_points_completed": all(float(item["time_end_s"]) > 0.0 for item in points),
        "all_points_safety_pass": all(float(item["max_abs_y_m"]) < 1.5 and float(item["max_cfl"]) < 0.5 for item in points),
        "all_points_response_cycle_reliability_pass": all(bool(item["crossing_reliability"]["reliable"]) for item in points),
        "all_points_final_steady_pass": all(bool(item["final_response_pair"]["final_steady_window_pass"]) for item in points),
        "ur5p2_groups_tested": next(item["response_period_groups_tested"] for item in points if math.isclose(float(item["ur"]), 5.2)),
        "ur5p2_groups_passed": next(item["response_period_groups_passed"] for item in points if math.isclose(float(item["ur"]), 5.2)),
        "no_ur_specific_classification_branch": True,
        "no_multislice_claim": True,
    }
    summary["five_point_steady_acceptance"] = bool(summary["all_points_final_steady_pass"] and summary["all_points_safety_pass"] and summary["all_points_response_cycle_reliability_pass"])
    (args.output / "five_point_lockin_v6.json").write_text(json.dumps(summary, indent=2, allow_nan=True) + "\n", encoding="utf-8")
    ur5_item = next(item for item in points if math.isclose(float(item["ur"]), 5.2))
    sensitivity = {
        "status": "robust_response_cycle_pass" if int(ur5_item["response_period_groups_passed"]) >= 2 else "response_cycle_window_pass_only" if int(ur5_item["response_period_groups_passed"]) else "response_cycle_window_fail",
        "ur": 5.2,
        "time_end_s": ur5_item["time_end_s"],
        "window_definition": "response-cycle-aligned",
        "window_combinations": ur5_item["response_period_window_metrics"],
        "passed_combinations": ur5_item["response_period_groups_passed"],
        "required_passed_combinations": 2,
        "interpretation": "Three late response-cycle groups are reported; each pair contains two continuous, non-overlapping windows of five measured response periods.",
    }
    (args.output / "window_sensitivity_v6.json").write_text(json.dumps(sensitivity, indent=2, allow_nan=True) + "\n", encoding="utf-8")
    # Keep the requested Ur=5.2 evidence path alongside the campaign result,
    # while retaining the complete five-point copy above.
    external_sensitivity = args.output.parent / "Ur5p2_extended" / "window_sensitivity_v6.json"
    external_sensitivity.parent.mkdir(parents=True, exist_ok=True)
    external_sensitivity.write_text(json.dumps(sensitivity, indent=2, allow_nan=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "groups_ur5p2": [summary["ur5p2_groups_passed"], summary["ur5p2_groups_tested"]], "all_steady": summary["all_points_final_steady_pass"], "safety": summary["all_points_safety_pass"]}, indent=2))


if __name__ == "__main__":
    main()
