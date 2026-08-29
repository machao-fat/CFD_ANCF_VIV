from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Mapping, Sequence


class RepairError(ValueError):
    """Raised when a moving-mesh contract cannot be proven offline."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _field_block(text: str, field_name: str) -> str:
    match = re.search(rf"(?ms)^\s*{re.escape(field_name)}\s*\{{(.*?)^\s*\}}", text)
    if match is None:
        raise RepairError(f"boundary patch is missing: {field_name}")
    return match.group(1)


def _patch_entry(text: str, patch: str) -> str:
    match = re.search(rf"\b{re.escape(patch)}\s*\{{", text)
    if match is None:
        raise RepairError(f"boundary patch is missing: {patch}")
    # A patch block has nested entries; use a balanced scan so a later patch
    # cannot be accidentally selected, regardless of line formatting.
    brace = text.find("{", match.start())
    depth = 0
    for index in range(brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1:index]
    raise RepairError(f"unterminated patch block: {patch}")


def _require(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise RepairError(f"{label} is missing")
    return match.group(1) if match.groups() else match.group(0)


def corrected_precice_dict(index: int) -> str:
    return f'''FoamFile
{{
    version 2.0;
    format ascii;
    class dictionary;
    location "system";
    object preciceDict;
}}

preciceConfig "precice-config.xml";
participant Fluid_{index:04d};
modules (FSI);

FSI
{{
    solverType incompressible;
    rho rho [1 -3 0 0 0 0 0] 1;
    nu nu [0 2 -1 0 0 0 0] 0.01;
    namePointDisplacement pointDisplacement;
    nameCellDisplacement cellDisplacement;
    nameForce Force;
}}

interfaces
{{
    Interface1
    {{
        mesh Fluid-Mesh;
        patches (cyl);
        locations faceCenters;
        readData (Displacement);
        writeData (Force);
    }}
}}
'''


def corrected_point_displacement() -> str:
    return '''FoamFile
{
    version 2.0;
    format ascii;
    class pointVectorField;
    location "0";
    object pointDisplacement;
}

dimensions      [0 1 0 0 0 0 0];

internalField   uniform (0 0 0);

boundaryField
{
    in { type fixedValue; value uniform (0 0 0); }
    out { type fixedValue; value uniform (0 0 0); }
    top { type fixedValue; value uniform (0 0 0); }
    bottom { type fixedValue; value uniform (0 0 0); }
    cyl { type fixedValue; value uniform (0 0 0); }
    back { type empty; }
    front { type empty; }
}
'''


def audit_case_configuration(
    *,
    precice_dict: str,
    point_displacement: str,
    velocity: str,
    dynamic_mesh: str,
    expected_participant: str,
    allow_calculated_point: bool = False,
    expected_motion_solver: str = "displacementLaplacian",
) -> dict[str, object]:
    checks: dict[str, bool] = {}
    checks["point_displacement_is_bound"] = bool(re.search(r"\bnamePointDisplacement\s+pointDisplacement\s*;", precice_dict))
    checks["old_unused_binding_absent"] = not bool(re.search(r"\bnamePointDisplacement\s+unused\s*;", precice_dict))
    checks["cell_displacement_is_bound"] = bool(re.search(r"\bnameCellDisplacement\s+cellDisplacement\s*;", precice_dict))
    checks["participant_identity_present"] = expected_participant in precice_dict
    checks["fluid_mesh_present"] = bool(re.search(r"\bmesh\s+Fluid-Mesh\s*;", precice_dict))
    checks["cyl_face_center_interface"] = bool(re.search(r"\bpatches\s*\(\s*cyl\s*\)\s*;", precice_dict)) and bool(re.search(r"\blocations\s+faceCenters\s*;", precice_dict))
    checks["displacement_read_data"] = bool(re.search(r"\breadData\s*\(\s*Displacement\s*\)\s*;", precice_dict))
    checks["force_write_data"] = bool(re.search(r"\bwriteData\s*\(\s*Force\s*\)\s*;", precice_dict))
    point_cyl = _patch_entry(point_displacement, "cyl")
    velocity_cyl = _patch_entry(velocity, "cyl")
    point_fixed = bool(re.search(r"\btype\s+fixedValue\s*;", point_cyl))
    point_calculated = bool(re.search(r"\btype\s+calculated\s*;", point_cyl))
    checks["point_cyl_fixed_value"] = point_fixed or (allow_calculated_point and point_calculated)
    checks["velocity_cyl_moving_wall"] = bool(re.search(r"\btype\s+movingWallVelocity\s*;", velocity_cyl))
    # OpenFOAM Foundation 10 uses the `mover` syntax, while the older
    # dynamicFvMesh form is retained for compatibility with protected cases.
    foundation_mover = bool(re.search(rf"(?s)\bmover\s*\{{.*?\btype\s+motionSolver\s*;.*?\bmotionSolver\s+{re.escape(expected_motion_solver)}\s*;", dynamic_mesh))
    classic_mover = bool(re.search(r"\bdynamicFvMesh\s+dynamicMotionSolverFvMesh\s*;", dynamic_mesh))
    checks["dynamic_motion_solver"] = classic_mover or foundation_mover
    checks["displacement_laplacian"] = bool(re.search(rf"\bsolver\s+{re.escape(expected_motion_solver)}\s*;", dynamic_mesh)) or foundation_mover
    checks["field_name_matches_solver"] = checks["point_displacement_is_bound"] and checks["point_cyl_fixed_value"] and checks["displacement_laplacian"]
    return {
        "checks": checks,
        "status": "pass" if all(checks.values()) else "do_not_pass",
        "adapter_path": f"faceCenters -> cellDisplacement -> pointDisplacement via primitivePatchInterpolation -> {expected_motion_solver}",
        "required_postrun_evidence": [
            "per-step received Displacement hash and finite-value audit for every slice",
            "per-step nonzero pointDisplacement/cylinder motion hash when structure motion is nonzero",
            "per-step moved mesh-point hash or equivalent mesh-motion diagnostic",
            "per-slice Force hash and value identity; accidental broadcast fails closed",
        ],
    }


def audit_motion_observations(
    observations: Sequence[Mapping[str, object]],
    *,
    slice_ids: Sequence[str] = ("slice_0000", "slice_0001", "slice_0002"),
    require_distinct_motion: bool = True,
) -> dict[str, object]:
    if not observations:
        raise RepairError("motion observations are empty")
    expected = tuple(slice_ids)
    records = 0
    distinct_motion = 0
    duplicate_force = 0
    for row in observations:
        records += 1
        motion = row.get("slice_motion")
        forces = row.get("slice_force_hashes")
        if not isinstance(motion, Mapping) or set(motion) != set(expected):
            raise RepairError("slice motion identity mismatch")
        if not isinstance(forces, Mapping) or set(forces) != set(expected):
            raise RepairError("slice force identity mismatch")
        motion_values: list[tuple[float, float]] = []
        for sid in expected:
            value = motion[sid]
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise RepairError(f"motion vector shape mismatch: {sid}")
            x, y = float(value[0]), float(value[1])
            if not math.isfinite(x) or not math.isfinite(y):
                raise RepairError(f"non-finite motion: {sid}")
            motion_values.append((x, y))
            force_hash = forces[sid]
            if not isinstance(force_hash, str) or len(force_hash) != 64:
                raise RepairError(f"force hash mismatch: {sid}")
        if len(set(motion_values)) > 1:
            distinct_motion += 1
        if len(set(forces.values())) == 1:
            duplicate_force += 1
    checks = {
        "records_nonzero": records > 0,
        "slice_motion_is_distinct": distinct_motion == records if require_distinct_motion else True,
        "force_broadcast_absent": duplicate_force == 0,
    }
    return {
        "status": "pass" if all(checks.values()) else "do_not_pass",
        "records": records,
        "distinct_motion_records": distinct_motion,
        "duplicate_force_records": duplicate_force,
        "checks": checks,
    }


def canonical_config_hashes(configs: Mapping[str, str]) -> dict[str, str]:
    return {name: _sha(text) for name, text in sorted(configs.items())}
