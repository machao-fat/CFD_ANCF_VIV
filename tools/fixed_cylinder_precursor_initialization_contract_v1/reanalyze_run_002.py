"""Read-only recovery of force rows from precursor run_002.

run_002's solver executions completed, but its initial evidence wrapper looked
only under `postProcessing/cylinderForces/0`.  A physical-time continuation
legitimately writes below `.../0.1`; this tool only re-reads raw artifacts and
writes a separate analysis result.  It never launches OpenFOAM.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log, evaluate_quality


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime" / "fixed_cylinder_precursor_initialization_v1_run_002"
SOURCE_RESULTS = ROOT / "results" / "fixed_cylinder_precursor_initialization_contract_v1_run_002" / "precursor_preflight.json"
OUT = ROOT / "results" / "fixed_cylinder_precursor_initialization_contract_v1_run_002_reanalysis"
QUALITY = ROOT / "tools" / "numerical_quality_evidence_closure_v1" / "openfoam_numerical_quality_contract_v2.json"
VECTOR = re.compile(r"\(([^()]+)\)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def force_rows(case: Path) -> list[dict[str, object]]:
    matches = list(case.glob("postProcessing/cylinderForces/*/forces.dat"))
    if len(matches) != 1:
        raise RuntimeError(f"force file cardinality failure for {case}: {matches}")
    result = []
    for line in matches[0].read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        vectors = VECTOR.findall(line)
        pressure = [float(value) for value in vectors[0].split()]
        viscous = [float(value) for value in vectors[1].split()]
        result.append({"time_s": float(line.split()[0]), "pressure_N": pressure, "viscous_N": viscous,
                       "total_N": [pressure[i] + viscous[i] for i in range(3)]})
    return result


def main() -> None:
    if OUT.exists():
        raise RuntimeError(f"refusing to overwrite {OUT}")
    original = json.loads(SOURCE_RESULTS.read_text(encoding="utf-8"))
    contract = original["contract"]
    accepted = float(contract["restart_continuity_acceptance"]["max_abs_first_step_jump_N"])
    branch_data: dict[str, object] = {}
    for name in ("fixed_restart", "zero_motion_dynamic_restart"):
        case = RUNTIME / name
        rows = force_rows(case)
        quality = evaluate_quality(audit_log(case / "restart.stdout", case / "system" / "fvSolution"), json.loads(QUALITY.read_text(encoding="utf-8")))
        branch_data[name] = {"case": str(case), "force_file": str(next(case.glob("postProcessing/cylinderForces/*/forces.dat"))),
                             "force_rows": rows, "quality_literal_v2": quality,
                             "start_hashes": {field: sha256(case / "0.1" / field) for field in ("U", "p", "phi")}}
    manifest = json.loads((ROOT / "results" / "fixed_cylinder_precursor_initialization_contract_v1_run_002" / "PRECURSOR_STATE_V1" / "manifest.json").read_text(encoding="utf-8"))
    terminal = float(original["precursor"]["forces"][-1]["total_N"][0])
    fixed = branch_data["fixed_restart"]["force_rows"]
    dynamic = branch_data["zero_motion_dynamic_restart"]["force_rows"]
    fixed_advanced = float(fixed[1]["total_N"][0]); dynamic_advanced = float(dynamic[1]["total_N"][0])
    fixed_jump = abs(fixed_advanced - terminal); dynamic_jump = abs(dynamic_advanced - terminal)
    fixed_hash_ok = branch_data["fixed_restart"]["start_hashes"] == manifest["field_hashes"]
    dynamic_hash_ok = branch_data["zero_motion_dynamic_restart"]["start_hashes"] == manifest["field_hashes"]
    fixed_ok = fixed_hash_ok and branch_data["fixed_restart"]["quality_literal_v2"]["status"] == "pass" and fixed_jump <= accepted
    dynamic_ok = dynamic_hash_ok and branch_data["zero_motion_dynamic_restart"]["quality_literal_v2"]["status"] == "pass" and dynamic_jump <= accepted
    result = {
        "schema_version": "fixed-cylinder-precursor-reanalysis-v1", "source_runtime_mode": "read_only",
        "reason": "correct physical-time force output directory discovery; no CFD rerun", "terminal_Fx_N": terminal,
        "fixed_first_advanced": fixed[1], "dynamic_first_advanced": dynamic[1],
        "fixed_restart_jump_N": fixed_jump, "dynamic_restart_jump_N": dynamic_jump,
        "fixed_dynamic_first_advanced_difference_N": abs(fixed_advanced - dynamic_advanced),
        "frozen_jump_limit_N": accepted, "fixed_initial_state_hash_match": fixed_hash_ok,
        "dynamic_initial_state_hash_match": dynamic_hash_ok, "branches": branch_data,
        "FIXED_RESTART_CONTINUITY": "pass" if fixed_ok else "fail",
        "ZERO_MOTION_DYNAMIC_RESTART_CONTINUITY": "pass" if dynamic_ok else "fail",
        "FIELD_TRANSFER_CONSISTENCY": "pass" if fixed_ok and dynamic_ok else "fail",
        "NEXT_COUPLED_0P1S": "AUTHORIZED" if fixed_ok and dynamic_ok else "NOT_AUTHORIZED",
        "dynamic_quality_parser_finding": "literal V2 evaluator fails on zero-iteration cellDisplacement solves and uncontracted pcorr despite contracted Ux/Uy/p terminal, Courant and continuity subgates passing; this is recorded, not reclassified."}
    OUT.mkdir(parents=True)
    (OUT / "precursor_preflight_reanalysis.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("FIXED_RESTART_CONTINUITY", "ZERO_MOTION_DYNAMIC_RESTART_CONTINUITY", "FIELD_TRANSFER_CONSISTENCY", "NEXT_COUPLED_0P1S")}, indent=2))


if __name__ == "__main__":
    main()
