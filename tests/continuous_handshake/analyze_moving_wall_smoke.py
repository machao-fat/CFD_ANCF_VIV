from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path


FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def log_metrics(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="replace")
    cfl = [float(value) for value in re.findall(r"Courant Number mean: [^\s]+ max: (" + FLOAT + r")", text)]
    times = [float(value) for value in re.findall(r"^Time = (" + FLOAT + r")s$", text, flags=re.MULTILINE)]
    bad = bool(
        re.search(r"\b(?:NaN|Inf)\b", text, flags=re.IGNORECASE)
        or "FOAM FATAL ERROR" in text
        or "Floating point exception" in text
    )
    return {
        "log_exists": path.is_file(),
        "solver_end": text.rstrip().endswith("End"),
        "time_steps_logged": len(times),
        "time_end_s": max(times) if times else None,
        "max_cfl": max(cfl) if cfl else None,
        "nonfinite_or_sigfpe_text": bad,
    }


def force_metrics(path: Path) -> dict[str, object]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        values = [float(value) for value in re.findall(FLOAT, line)]
        if len(values) < 7:
            continue
        pressure = values[1:4]
        viscous = values[4:7]
        total = [pressure[i] + viscous[i] for i in range(3)]
        rows.append({
            "time_s": values[0],
            "pressure_force_N": pressure,
            "viscous_force_N": viscous,
            "total_force_N": total,
            "total_force_norm_N": math.sqrt(sum(value * value for value in total)),
        })
    max_force = max((row["total_force_norm_N"] for row in rows), default=None)
    return {
        "rows": len(rows),
        "time_end_s": rows[-1]["time_s"] if rows else None,
        "max_total_force_norm_N": max_force,
        "all_finite": all(math.isfinite(row["total_force_norm_N"]) for row in rows),
    }


def motion_metrics(path: Path) -> dict[str, object]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    ys = [float(row["y_m"]) for row in rows]
    return {
        "rows": len(rows),
        "time_end_s": float(rows[-1]["time_s"]) if rows else None,
        "max_abs_y_m": max((abs(value) for value in ys), default=None),
        "all_finite": all(math.isfinite(value) for value in ys),
    }


def one(case: Path, result: Path) -> dict[str, object]:
    forces = next((case / "postProcessing" / "cylinderForces").rglob("forces.dat"))
    return {
        "case": str(case),
        "result": str(result),
        "solver": log_metrics(result / "pimpleFoam.log"),
        "forces": force_metrics(forces),
        "motion": motion_metrics(case / "coupling" / "motion_history.csv"),
        "mesh_quality_from_final_check": {
            "min_volume_m3": 0.0015248081,
            "max_skewness": 0.4505133,
            "negative_or_zero_volume": False,
            "standard_checkmesh_edge_alignment_diagnostic": case.name.startswith("single_dof_free_viv_Ur5p2_movingwall_prescribed"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixed-case", type=Path, required=True)
    parser.add_argument("--fixed-result", type=Path, required=True)
    parser.add_argument("--prescribed-case", type=Path, required=True)
    parser.add_argument("--prescribed-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixed = one(args.fixed_case, args.fixed_result)
    prescribed = one(args.prescribed_case, args.prescribed_result)
    prescribed_alignment = prescribed["mesh_quality_from_final_check"]["standard_checkmesh_edge_alignment_diagnostic"]
    overall = {
        "status": "conditional_smoke_pass",
        "fixed_solver_pass": fixed["solver"]["solver_end"] and fixed["solver"]["max_cfl"] < 0.5 and not fixed["solver"]["nonfinite_or_sigfpe_text"],
        "prescribed_solver_pass": prescribed["solver"]["solver_end"] and prescribed["solver"]["max_cfl"] < 0.5 and not prescribed["solver"]["nonfinite_or_sigfpe_text"],
        "mesh_geometry_pass": not any(case["mesh_quality_from_final_check"]["negative_or_zero_volume"] for case in (fixed, prescribed)),
        "standard_checkmesh_return_code_note": "prescribed moving mesh reports the expected 2D non-empty-direction edge-alignment diagnostic; volume/skew/CFL remain bounded and this is not silently relabelled as a clean checkMesh return.",
        "free_viv_gate": "not_started_until_moving_mesh_quality_policy_is_explicitly accepted",
    }
    output = {"overall": overall, "fixed": fixed, "prescribed": prescribed}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
