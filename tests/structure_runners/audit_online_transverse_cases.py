from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.coupling.file_exchange.csv_contract import validate_motion_csv
from src.coupling.online_file_coupling.protocol import read_ready_snapshot


CASES = {
    "eb": ROOT / "cases" / "openfoam" / "single_slice_eb_transverse150_prepared",
    "ancf": ROOT / "cases" / "openfoam" / "single_slice_ancf_transverse150_prepared",
}
SOURCE = (
    ROOT
    / "cases"
    / "openfoam"
    / "fixed_cylinder_study_full30b"
    / "medium_dt0p0025"
)
SOURCE_TIME = "30"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted((p for p in path.rglob("*") if p.is_file()), key=lambda p: p.as_posix()):
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        payload = item.read_bytes()
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def internal_field_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.find("internalField")
    end = text.find("boundaryField")
    if start < 0 or end <= start:
        raise ValueError(f"cannot isolate internalField in {path}")
    return hashlib.sha256(text[start:end].encode("utf-8")).hexdigest()


def field_location(path: Path) -> str:
    match = re.search(r'(?m)^\s*location\s+"?([^";]+)"?\s*;', path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"no field location in {path}")
    return match.group(1).strip()


def cylinder_summary(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^\s*cylinder\s*\{(.*?)^\s*\}", text)
    if not match:
        raise ValueError(f"no cylinder patch in {path}")
    body = match.group(1)
    type_match = re.search(r"(?m)^\s*type\s+([^;]+);", body)
    value_match = re.search(r"(?m)^\s*value\s+([^;]+);", body)
    return {
        "type": type_match.group(1).strip() if type_match else None,
        "value": value_match.group(1).strip() if value_match else None,
        "contains_noSlip": "noSlip" in body,
    }


def scalar_entry(path: Path, name: str) -> float:
    match = re.search(
        rf"(?m)^\s*{re.escape(name)}\s+([-+0-9.eE]+)\s*;",
        path.read_text(encoding="utf-8"),
    )
    if not match:
        raise ValueError(f"no scalar {name} in {path}")
    return float(match.group(1))


def audit_case(branch: str, case: Path) -> dict[str, object]:
    if not case.is_dir():
        raise FileNotFoundError(case)
    motion = case / "coupling" / "motion.csv"
    marker = case / "coupling" / "motion_ready"
    motion_rows = validate_motion_csv(motion, expected_s_ref_m=[75.0])
    read_ready_snapshot(
        motion,
        marker,
        kind="motion",
        expected_step=0,
        expected_time_s=0.0,
        expected_s_ref_m=[75.0],
    )
    return {
        "branch": branch,
        "path": str(case),
        "mesh_sha256": tree_sha256(case / "constant" / "polyMesh"),
        "mesh_points_sha256": sha256(case / "constant" / "polyMesh" / "points"),
        "U_sha256": sha256(case / "0" / "U"),
        "p_sha256": sha256(case / "0" / "p"),
        "U_internal_field_sha256": internal_field_sha256(case / "0" / "U"),
        "p_internal_field_sha256": internal_field_sha256(case / "0" / "p"),
        "U_location": field_location(case / "0" / "U"),
        "p_location": field_location(case / "0" / "p"),
        "cylinder_U_boundary": cylinder_summary(case / "0" / "U"),
        "dynamicMeshDict_sha256": sha256(case / "constant" / "dynamicMeshDict"),
        "system_sha256": tree_sha256(case / "system"),
        "motion_s_ref_m": float(motion_rows[0]["s_ref_m"]),
        "motion_ready_validated": True,
        "application": "pimpleFoam",
        "start_time_s": scalar_entry(case / "system" / "controlDict", "startTime"),
        "end_time_s": scalar_entry(case / "system" / "controlDict", "endTime"),
        "cfd_dt_s": scalar_entry(case / "system" / "controlDict", "deltaT"),
        "coupling_dt_s": scalar_entry(case / "constant" / "dynamicMeshDict", "couplingDeltaT"),
    }


def main() -> None:
    source_u = SOURCE / SOURCE_TIME / "U"
    source_p = SOURCE / SOURCE_TIME / "p"
    cases = [audit_case(branch, path) for branch, path in CASES.items()]
    equal_keys = (
        "mesh_sha256",
        "U_sha256",
        "p_sha256",
        "dynamicMeshDict_sha256",
        "system_sha256",
    )
    equality = {key: cases[0][key] == cases[1][key] for key in equal_keys}
    source_internal = {
        "U": internal_field_sha256(source_u),
        "p": internal_field_sha256(source_p),
    }
    source_preserved = {
        "U": all(case["U_internal_field_sha256"] == source_internal["U"] for case in cases),
        "p": all(case["p_internal_field_sha256"] == source_internal["p"] for case in cases),
    }
    boundary_ok = all(
        case["cylinder_U_boundary"]["type"] == "movingWallVelocity"
        and case["cylinder_U_boundary"]["value"] == "uniform (0 0 0)"
        and not case["cylinder_U_boundary"]["contains_noSlip"]
        for case in cases
    )
    time_and_sref_ok = all(
        case["U_location"] == "0"
        and case["p_location"] == "0"
        and case["motion_s_ref_m"] == 75.0
        and case["cfd_dt_s"] == case["coupling_dt_s"] == 0.0025
        for case in cases
    )
    audit = {
        "status": "prepared_ready_not_run",
        "source_field": {
            "case": str(SOURCE),
            "time": SOURCE_TIME,
            "U_location": field_location(source_u),
            "p_location": field_location(source_p),
            "U_sha256": sha256(source_u),
            "p_sha256": sha256(source_p),
            "U_internal_field_sha256": source_internal["U"],
            "p_internal_field_sha256": source_internal["p"],
        },
        "cases": cases,
        "eb_ancf_exact_equality": equality,
        "source_internal_field_preserved": source_preserved,
        "moving_wall_boundary_pass": boundary_ok,
        "time_step_and_s_ref_pass": time_and_sref_ok,
        "all_preparation_checks_pass": (
            all(equality.values())
            and all(source_preserved.values())
            and boundary_ok
            and time_and_sref_ok
        ),
        "not_executed": True,
        "blocking_issue": "none; protocol patch is applied. CFD execution remains a separate smoke-test gate.",
    }
    output = (
        ROOT
        / "results"
        / "04_eb_ancf_physical_comparison"
        / "online_transverse_case_audit.json"
    )
    output.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))
    if not audit["all_preparation_checks_pass"]:
        raise SystemExit("prepared online transverse cases failed audit")


if __name__ == "__main__":
    main()
