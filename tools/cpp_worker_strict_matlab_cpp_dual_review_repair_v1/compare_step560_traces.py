"""Build a source-state C++ forensic fixture and compare it with MATLAB trace.

This tool is offline-only. It does not start MATLAB, OpenFOAM, WSL, or CFD.
The model metadata and mass matrix come from the protected forensic fixture;
all source state vectors come from the newly authorized MATLAB trace.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from typing import Any


FIELDS = (
    ("xi", 1),
    ("x", 1),
    ("a", 3),
    ("b", 3),
    ("v", 3),
    ("a_squared", 1),
    ("v_squared", 1),
    ("eps", 1),
    ("ga_b", 3),
    ("gb_b", 3),
    ("ga", 3),
    ("gb", 3),
    ("B_t_ga", 12),
    ("C_t_gb", 12),
    ("internal_force_contribution", 12),
)


def _flatten(values: Any) -> list[float]:
    return [float(value) for value in values]


def write_fixture(matlab: dict[str, Any], template: dict[str, Any], path: Path) -> None:
    keys = (
        "length_m", "diameter_m", "inner_diameter_m", "elements", "slices",
        "youngs_modulus_Pa", "material_density", "fluid_density", "gravity",
        "beta", "gamma", "newton_tolerance", "gauss_order", "max_newton", "dt_s",
    )
    header = [template[key] for key in keys]
    values: list[float] = [float(value) for value in header]
    values.extend(float(value) for value in template["slice_positions_m"])
    values.extend(_flatten(matlab["q_source"]))
    values.extend(_flatten(matlab["qdot_source"]))
    values.extend(_flatten(matlab["qddot_source"]))
    values.extend(_flatten(template["base_load"]))
    values.extend(_flatten(template["mass_matrix"]))
    values.extend(_flatten(template["slice_force"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(" ".join(format(value, ".17g") for value in values) + "\n", encoding="utf-8")


def parse_cpp_trace(path: Path) -> tuple[list[list[float]], list[float], list[float]]:
    points: list[list[float]] = []
    force: list[float] | None = None
    tangent: list[float] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        tokens = line.split()
        if tokens and tokens[0] == "point":
            points.append([float(value) for value in tokens[3:]])
        elif tokens and tokens[0] == "force":
            force = [float(value) for value in tokens[2:]]
        elif tokens and tokens[0] == "tangent":
            tangent = [float(value) for value in tokens[3:]]
    if force is None or tangent is None:
        raise ValueError("C++ trace has no force or tangent record")
    return points, force, tangent


def compare_point(matlab_point: dict[str, Any], cpp_values: list[float]) -> dict[str, Any]:
    offset = 0
    best = {"field": None, "max_abs": 0.0, "index": None}
    fields: dict[str, dict[str, Any]] = {}
    for name, width in FIELDS:
        expected = _flatten(matlab_point[name]) if width > 1 else [float(matlab_point[name])]
        actual = cpp_values[offset:offset + width]
        offset += width
        if len(actual) != width:
            raise ValueError(f"truncated C++ point field {name}")
        errors = [abs(left - right) for left, right in zip(expected, actual)]
        index = max(range(width), key=errors.__getitem__)
        max_abs = errors[index]
        fields[name] = {"max_abs": max_abs, "index": index}
        if max_abs > best["max_abs"]:
            best = {"field": name, "max_abs": max_abs, "index": index}
    return {"fields": fields, "first_nonzero": best}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matlab-trace", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("source", "target"), default="source")
    args = parser.parse_args()
    matlab = json.loads(args.matlab_trace.read_text(encoding="utf-8"))
    template = json.loads(args.template.read_text(encoding="utf-8"))
    args.runtime.mkdir(parents=True, exist_ok=True)
    fixture = args.runtime / "source_step559_fixture.txt"
    cpp_trace = args.runtime / "cpp_source_step560_trace.txt"
    if args.phase == "target":
        matlab = dict(matlab)
        matlab["q_source"] = matlab["q_target"]
    write_fixture(matlab, template, fixture)
    completed = subprocess.run(
        [str(args.worker), str(fixture), str(cpp_trace)],
        capture_output=True, text=True, check=False,
    )
    points, cpp_force, cpp_tangent = parse_cpp_trace(cpp_trace) if cpp_trace.is_file() else ([], [], [])
    trace_points = matlab["points_target" if args.phase == "target" else "points_source"]
    trace_force = matlab["internal_force_target" if args.phase == "target" else "internal_force_source"]
    point_audits = [compare_point(trace_points[i], points[i])
                    for i in range(min(len(points), len(trace_points))) ]
    max_point = max(
        (audit["first_nonzero"] for audit in point_audits),
        key=lambda item: item["max_abs"], default={"field": None, "max_abs": None, "index": None},
    )
    force_errors = [abs(float(expected) - actual)
                    for expected, actual in zip(trace_force, cpp_force)]
    matlab_tangent = [float(value) for row in matlab["internal_force_tangent_target" if args.phase == "target" else "internal_force_tangent_source"] for value in row]
    tangent_errors = [abs(expected - actual) for expected, actual in zip(matlab_tangent, cpp_tangent)]
    audit = {
        "matlab_trace": str(args.matlab_trace),
        "cpp_fixture": str(fixture),
        "cpp_trace": str(cpp_trace),
        "worker_return_code": completed.returncode,
        "worker_stdout": completed.stdout,
        "worker_stderr": completed.stderr,
        "phase": args.phase,
        "point_count_matlab": len(trace_points),
        "point_count_cpp": len(points),
        "first_point_difference": point_audits[0]["first_nonzero"] if point_audits else None,
        "largest_point_difference": max_point,
        "point_audits": point_audits,
        "internal_force_max_abs": max(force_errors, default=None),
        "internal_force_max_index": force_errors.index(max(force_errors)) if force_errors else None,
        "tangent_max_abs": max(tangent_errors, default=None),
        "tangent_max_index": tangent_errors.index(max(tangent_errors)) if tangent_errors else None,
        "finite_audit": all(math.isfinite(value) for value in cpp_force),
        "input_identity": {
            "source_global_step": matlab["source_global_step"],
            "target_global_step": matlab["target_global_step"],
            "source_time_s": matlab["source_time_s"],
            "target_time_s": matlab["target_time_s"],
            "global_dt": matlab["global_dt"],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return 0 if completed.returncode == 0 and len(points) == len(matlab["points_source"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
