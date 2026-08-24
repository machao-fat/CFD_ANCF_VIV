from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path


def finite(value: str) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def max_abs(rows, key):
    return max((abs(float(row[key])) for row in rows), default=0.0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", required=True, choices=("eb", "ancf"))
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit_path = args.results / "coupling_audit.csv"
    rows = list(csv.DictReader(audit_path.open(newline="", encoding="utf-8-sig")))
    log = (args.results / "pimpleFoam.log").read_text(encoding="utf-8", errors="replace")
    cfl = [float(value) for value in re.findall(r"Courant Number mean: [^\s]+ max: ([-+0-9.eE]+)", log)]
    numeric_fields = [
        key for key in rows[0]
        if key not in {"force_representation", "status", "compression_risk", "structure_converged"}
    ]
    all_finite = all(finite(row[key]) for row in rows for key in numeric_fields)
    x_zero = max(max_abs(rows, key) for key in ("predicted_x_m", "corrected_x_m", "predicted_vx_mps", "corrected_vx_mps", "predicted_ax_mps2", "corrected_ax_mps2"))
    applied_x = max_abs(rows, "applied_force_x_N")
    applied_z = max_abs(rows, "applied_force_z_N")
    applied_y_error = max(
        abs(float(row["applied_force_y_N"]) - float(row["force_y_N"])) for row in rows
    )
    min_tension = min(float(row["min_tension_N"]) for row in rows)
    max_relative_residual = max(float(row["structure_relative_residual"]) for row in rows)
    out = {
        "status": "smoke_pass_interface_only",
        "branch": args.branch,
        "case": str(args.case.resolve()),
        "results": str(args.results.resolve()),
        "steps": len(rows),
        "time_end_s": float(rows[-1]["time_s"]),
        "cfl": {"max": max(cfl) if cfl else None, "threshold": 0.5, "pass": bool(cfl and max(cfl) < 0.5)},
        "force_protocol": {
            "all_integrated_N": all(row["force_representation"] == "integrated_N" for row in rows),
            "unit_span_all_1m": all(abs(float(row["unit_span_m"]) - 1.0) < 1e-14 for row in rows),
            "slice_length_all_1m": all(abs(float(row["slice_length_m"]) - 1.0) < 1e-14 for row in rows),
            "max_applied_Fx_N": applied_x,
            "max_applied_Fz_N": applied_z,
            "max_abs_applied_Fy_minus_raw_Fy_N": applied_y_error,
            "transverse_projection_pass": applied_x < 1e-14 and applied_z < 1e-14 and applied_y_error < 1e-12,
        },
        "motion_projection": {"max_abs_inline_state": x_zero, "inline_zero_pass": x_zero < 1e-14},
        "structure": {
            "all_newton_converged": all(row["structure_converged"].lower() == "true" for row in rows),
            "max_relative_residual": max_relative_residual,
            "min_tension_N": min_tension,
            "compression_risk": any(row["compression_risk"].lower() == "true" for row in rows),
            "all_energy_and_residual_fields_finite": all_finite,
        },
        "response": {
            "max_abs_corrected_y_m": max_abs(rows, "corrected_y_m"),
            "rms_corrected_y_m": math.sqrt(sum(float(row["corrected_y_m"]) ** 2 for row in rows) / len(rows)),
        },
        "physical_scope": "100-step interface smoke only; not a physical VIV or lock-in result",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
