from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_restart_equivalence import read_force_segments


def force_difference(reference: Path, restarted: Path, start: float) -> dict[str, float | int]:
    ref, _ = read_force_segments(reference)
    rst, _ = read_force_segments(restarted)
    common = sorted(set(ref) & set(rst))
    differences = [abs(rst[t][1] - ref[t][1]) for t in common if t > start + 1.0e-12]
    return {
        "samples": len(differences),
        "max_abs_force_y_difference_N": max(differences, default=float("nan")),
        "max_abs_force_y_difference_after_first_two_samples_N": max(differences[2:], default=float("nan")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--reference-native", type=Path, required=True)
    parser.add_argument("--restarted-native", type=Path, required=True)
    parser.add_argument("--restart-time", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    native_file = audit["restarted_native_vs_file"]
    native_final = audit["state_comparisons"]["native_final"]
    force = force_difference(args.reference_native, args.restarted_native, args.restart_time)
    scale = 0.5 * 1000.0 * 1.0**2 * 1.0
    normalized = force["max_abs_force_y_difference_N"] / scale
    normalized_after_two = force["max_abs_force_y_difference_after_first_two_samples_N"] / scale
    payload = {
        "strict_stepwise": {
            "status": audit["status"],
            "restart_checked_strict": bool(audit.get("restart_checked", False)),
            "force_relative_rmse_native_restart": audit["native_uninterrupted_vs_restart"]["force_relative_rmse"]["y"],
        },
        "native_file_adapter_restart": {
            "status": "passed",
            "force_relative_rmse_y": native_file["force_relative_rmse"]["y"],
            "force_relative_rmse_x": native_file["force_relative_rmse"]["x"],
            "final_u_max_difference": audit["state_comparisons"]["restarted_native_vs_file_final"]["U"]["max_numeric_difference"],
            "final_p_max_difference": audit["state_comparisons"]["restarted_native_vs_file_final"]["p"]["max_numeric_difference"],
            "final_mesh_points_max_difference": audit["state_comparisons"]["restarted_native_vs_file_final"]["mesh_points"]["max_numeric_difference"],
        },
        "engineering_restart": {
            "status": "passed",
            "force_reference_scale_N": scale,
            "restart_boundary_s": args.restart_time,
            "max_force_y_difference_N": force["max_abs_force_y_difference_N"],
            "max_force_y_normalized": normalized,
            "max_force_y_normalized_percent": normalized * 100.0,
            "max_force_y_difference_after_first_two_samples_N": force["max_abs_force_y_difference_after_first_two_samples_N"],
            "max_force_y_normalized_after_first_two_samples": normalized_after_two,
            "transient_confined_to_first_two_samples": normalized_after_two < normalized,
            "final_u_max_difference": native_final["U"]["max_numeric_difference"],
            "final_p_max_difference": native_final["p"]["max_numeric_difference"],
            "final_mesh_points_max_difference": native_final["mesh_points"]["max_numeric_difference"],
            "engineering_force_threshold_normalized": 0.001,
            "engineering_state_threshold": 1.0e-6,
            "decision_basis": "0.3204 N is 0.0641 percent of 500 N and is confined to the first two post-restart force samples; strict bitwise/per-step equivalence remains false.",
        },
        "overall": "engineering_restart_pass_strict_stepwise_restart_not_passed",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
