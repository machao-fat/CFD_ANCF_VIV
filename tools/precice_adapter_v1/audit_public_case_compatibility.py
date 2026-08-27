"""Read-only audit of the public OF10 case against the preCICE FSI template."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "cases/openfoam/stage268_validated_viv_of10"
TEMPLATE = ROOT / "tools/precice_adapter_v1/templates/single_slice_smoke/preciceDict"
OUT = ROOT / "results/273_precice_public_case_compatibility_v1"


def field_block(text: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*\{{(.*?)\n\s*\}}", text, re.S)
    return match.group(1) if match else ""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    boundary = (CASE / "constant/polyMesh/boundary").read_text(encoding="utf-8", errors="replace")
    point = (CASE / "0/pointDisplacement").read_text(encoding="utf-8", errors="replace")
    dyn = (CASE / "constant/dynamicMeshDict").read_text(encoding="utf-8", errors="replace")
    foam = TEMPLATE.read_text(encoding="utf-8", errors="replace")
    cyl = field_block(point, "cyl")
    checks = {
        "patch_cyl_exists": re.search(r"\bcyl\s*\{", boundary) is not None,
        "template_uses_cyl": "patches     (cyl);" in foam,
        "point_displacement_fixed_value": re.search(r"\btype\s+fixedValue\s*;", cyl) is not None,
        "dynamic_mesh_displacement_laplacian": "displacementLaplacian" in dyn,
        "current_case_uses_rigid_body_motion": "rigidBodyMotion" in dyn,
    }
    findings = []
    if not checks["point_displacement_fixed_value"]:
        findings.append("pointDisplacement/cyl is not fixedValue; adapter FSI displacement input cannot be applied as-is")
    if not checks["dynamic_mesh_displacement_laplacian"]:
        findings.append("dynamicMeshDict lacks displacementLaplacian; current rigidBodyMotion must be replaced in an isolated coupling copy")
    gate = {
        "gate_id": "STAGE4F_D_PRECICE_PUBLIC_CASE_COMPATIBILITY_V1_GATE",
        "status": "pass" if not findings else "do_not_pass",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scope": "read-only compatibility audit; public case was not modified or started",
        "case": str(CASE),
        "checks": checks,
        "findings": findings,
        "required_isolated_changes": ["copy case to a new runtime", "set pointDisplacement/cyl to fixedValue", "replace rigidBodyMotion with adapter-compatible mesh motion", "revalidate U and pointDisplacement boundary conditions"],
        "real_process_counts": {"matlab": 0, "openfoam": 0, "wsl_cfd": 0, "cfd": 0, "precice_participant": 0},
        "protected": {"public_case_modified": False, "historical_evidence_modified": False, "ancf_core_modified": False, "physical_parameters_modified": False},
        "next_authorization": "isolated case adaptation and offline dictionary validation before any real smoke",
    }
    (OUT / "stage4f_d_precice_public_case_compatibility_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "checks": checks, "findings": findings}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
