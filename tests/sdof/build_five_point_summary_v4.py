from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(raw: dict, ur: float) -> dict:
    """Use one schema for point metrics without changing the raw evidence."""
    if "final_window_60_to_86" in raw:
        w1 = raw["final_window_60_to_86"]
        w2 = raw["final_window_86_to_112"]
        comparison = raw["final_window_comparison"]
        steady = bool(comparison["steady_window_pass"])
        max_cfl = float(raw["safety"]["max_cfl"])
        max_abs_y = float(raw["safety"]["max_abs_y_m"])
        status = raw["status"]
    else:
        w1 = raw["window_1"]
        w2 = raw["window_2"]
        steady = bool(raw["steady_window_pass"])
        max_cfl = float(raw["max_cfl"])
        max_abs_y = float(raw["max_abs_y_m"])
        status = raw["status"]
        comparison = {
            "relative_changes": raw["relative_changes"],
            "last_three_cycle_power_balance_relative": raw["last_three_cycle_power_balance_relative"],
            "steady_window_pass": steady,
        }
    fn = float(raw.get("fn_Hz", raw.get("natural_frequency_Hz", 1.0 / ur)))
    f_over_fn = float(w2["response_frequency_Hz_zero_crossing"]) / fn if fn else 0.0
    if 0.95 <= f_over_fn <= 1.05:
        lockin = "near_lock_in_frequency"
    else:
        lockin = "outside_lock_in_frequency_window"
    return {
        "ur": ur,
        "fn_Hz": fn,
        "status": status,
        "steady_window_pass": steady,
        "lock_in_classification": lockin,
        "time_end_s": float(raw.get("time_end_s", 0.0)),
        "max_abs_y_m": max_abs_y,
        "max_cfl": max_cfl,
        "window_1": w1,
        "window_2": w2,
        "relative_changes": comparison["relative_changes"],
        "last_three_cycle_power_balance_relative": comparison["last_three_cycle_power_balance_relative"],
        "source_status": status,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ur4", type=Path, required=True)
    parser.add_argument("--ur5p2", type=Path, required=True)
    parser.add_argument("--ur6", type=Path, required=True)
    parser.add_argument("--ur7p1", type=Path, required=True)
    parser.add_argument("--ur8", type=Path, required=True)
    args = parser.parse_args()
    sources = [(4.0, args.ur4), (5.2, args.ur5p2), (6.0, args.ur6), (7.1, args.ur7p1), (8.0, args.ur8)]
    missing = [str(path) for _, path in sources if not path.exists()]
    if missing:
        raise FileNotFoundError("missing point metrics: " + ", ".join(missing))
    points = [normalize(load(path), ur) for ur, path in sources]
    args.output.mkdir(parents=True, exist_ok=True)
    for point in points:
        (args.output / f"Ur{str(point['ur']).replace('.', 'p')}_point_metrics_v4.json").write_text(
            json.dumps(point, indent=2) + "\n", encoding="utf-8"
        )
    summary = {
        "status": "five_point_campaign_complete",
        "ur_points": [point["ur"] for point in points],
        "points": points,
        "acceptance_definition": {
            "two_adjacent_windows": "five natural periods per window",
            "relative_amplitude_force_power_limit": 0.05,
            "relative_frequency_limit": 0.02,
            "last_three_cycle_energy_balance_limit": 0.10,
            "safety_limits": {"max_abs_y_m": 1.5, "max_cfl": 0.5},
        },
        "all_points_completed": all(point["time_end_s"] > 0 for point in points),
        "all_points_safety_pass": all(point["max_abs_y_m"] < 1.5 and point["max_cfl"] < 0.5 for point in points),
        "all_points_strict_steady_window_pass": all(point["steady_window_pass"] for point in points),
        "interpretation": (
            "The frequency and amplitude curves distinguish the near-lock-in point from the outside-lock-in points. "
            "A point with very small near-zero input power is not promoted to a strict steady pass by changing the denominator."
        ),
    }
    (args.output / "five_point_lockin_v4.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "points": len(points), "all_safety_pass": summary["all_points_safety_pass"]}, indent=2))


if __name__ == "__main__":
    main()
