"""Static acceptance audit for the corrected moving-wall SDOF CFD case."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def block(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(name)}\s*\n\s*\{{", text)
    if match is None:
        raise ValueError(f"dictionary block {name!r} is missing")
    start = text.find("{", match.start())
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:index]
    raise ValueError(f"dictionary block {name!r} is unterminated")


def has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, flags=re.MULTILINE) is not None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    case = args.case.resolve()
    u = (case / "0/U").read_text(encoding="utf-8")
    p = (case / "0/p").read_text(encoding="utf-8")
    dynamic = (case / "constant/dynamicMeshDict").read_text(encoding="utf-8")
    boundary = (case / "constant/polyMesh/boundary").read_text(encoding="utf-8")
    control = (case / "system/controlDict").read_text(encoding="utf-8")
    physical = (case / "constant/physicalProperties").read_text(encoding="utf-8")
    motion_scale_path = case / "0/motionScale"
    motion_scale = motion_scale_path.read_text(encoding="utf-8") if motion_scale_path.is_file() else ""

    u_cylinder = block(u, "cylinder")
    p_cylinder = block(p, "cylinder")
    mesh_cylinder = block(boundary, "cylinder")
    checks = {
        "developed_U_internal_field": has(r"internalField\s+nonuniform\s+List<vector>", u),
        "developed_p_internal_field": has(r"internalField\s+nonuniform\s+List<scalar>", p),
        "U_cylinder_movingWallVelocity": has(r"type\s+movingWallVelocity\s*;", u_cylinder),
        "U_cylinder_zero_seed_value": has(r"value\s+uniform\s*\(0\s+0\s+0\)\s*;", u_cylinder),
        "p_cylinder_zeroGradient": has(r"type\s+zeroGradient\s*;", p_cylinder),
        "mesh_cylinder_is_wall": has(r"type\s+wall\s*;", mesh_cylinder),
        "motion_solver_mover": has(r"(?m)^\s*mover\s*\{", dynamic),
        "interpolating_solid_body": has(r"motionSolver\s+interpolatingSolidBody\s*;", dynamic),
        "moving_patch_is_cylinder": has(r"patches\s*\(cylinder\)\s*;", dynamic),
        "file_motion_library": "libancfFileMotion.so" in dynamic,
        "mesh_mover_libraries": "libfvMeshMovers.so" in dynamic and "libfvMotionSolvers.so" in dynamic,
        "motion_scale_present": motion_scale_path.is_file(),
        "motion_scale_point_field": has(r"class\s+pointScalarField\s*;", motion_scale),
        "motion_scale_nonuniform": has(r"internalField\s+nonuniform\s+List<scalar>", motion_scale),
        "force_function_uses_cylinder": len(re.findall(r"patches\s*\(cylinder\)\s*;", control)) >= 2,
        "delta_t_0p0025": has(r"deltaT\s+0\.0025\s*;", control),
        "nu_0p01": has(r"\bnu\s+\[[^\]]+\]\s+0\.01\s*;", physical),
    }
    point_motion_fields = sorted(path.name for path in (case / "0").glob("pointMotionU*"))
    payload = {
        "case": str(case),
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "point_motion_fields": point_motion_fields,
        "point_motion_note": (
            "interpolatingSolidBody uses the generated motionScale point field; "
            "a pointMotionU/pointMotionUx field is not consumed by this mover"
        ),
        "nominal_Re": 100.0,
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if payload["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
