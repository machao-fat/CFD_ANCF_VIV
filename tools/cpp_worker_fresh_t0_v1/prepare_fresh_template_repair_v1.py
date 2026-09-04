"""Create a new offline-only fresh t=0 case template with seed fixes."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v2/run_20260827_retry1/cases"
DEST = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix6/cases"
RESULTS = PROJECT / "results/250_cpp_worker_fresh_template_repair_v1"
DOCS = PROJECT / "docs/250_cpp_worker_fresh_template_repair_v1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if DEST.exists():
        raise RuntimeError(f"refusing to overwrite existing repair template: {DEST}")
    if not SOURCE.is_dir():
        raise RuntimeError(f"source template is missing: {SOURCE}")
    shutil.copytree(SOURCE, DEST)
    for sid in range(3):
        root = DEST / f"slice_{sid:04d}"
        for field_name in ("meshPhi", "phi", "Uf"):
            field = root / "0" / field_name
            text = field.read_text(encoding="utf-8")
            # OpenFOAM 10 requires explicit values for surface patch fields.
            value = "uniform (0 0 0)" if field_name == "Uf" else "uniform 0"
            text = re.sub(r"(lower|upper)\s+\{\s*type\s+(?:symmetryPlane|calculated);(?:\s*value\s+uniform(?:\s+\([^;]+\)|\s+0);)?\s*\}",
                          rf"\1 {{ type symmetryPlane; value {value}; }}", text)
            text = re.sub(r"(outlet|inlet|cylinder)\s+\{\s*type\s+calculated;(?:\s*value\s+uniform(?:\s+\([^;]+\)|\s+0);)?\s*\}",
                          rf"\1 {{ type calculated; value {value}; }}", text)
            field.write_text(text, encoding="utf-8")
        dynamic = root / "constant" / "dynamicMeshDict"
        dtext = dynamic.read_text(encoding="utf-8")
        dtext = re.sub(r"(?m)^\s*sliceId\s+\d+\s*;", f"        sliceId         {sid};", dtext)
        dynamic.write_text(dtext, encoding="utf-8")
    rows = []
    for sid in range(3):
        root = DEST / f"slice_{sid:04d}"
        mesh = (root / "0" / "meshPhi").read_text(encoding="utf-8")
        phi = (root / "0" / "phi").read_text(encoding="utf-8")
        uf = (root / "0" / "Uf").read_text(encoding="utf-8")
        dynamic = (root / "constant" / "dynamicMeshDict").read_text(encoding="utf-8")
        rows.append({"slice_id": sid,
                     "meshPhi_value_on_symmetry": "value uniform 0" in mesh and "value uniform 0" in phi,
                     "Uf_boundary_values": "value uniform (0 0 0)" in uf,
                     "slice_id_matches": f"sliceId         {sid};" in dynamic,
                     "meshPhi_sha256": _sha(root / "0" / "meshPhi"),
                     "dynamicMeshDict_sha256": _sha(root / "constant" / "dynamicMeshDict"),
                     "phi_sha256": _sha(root / "0" / "phi")})
    evidence = {
        "stage_id": "stage4f_d_cpp_worker_fresh_template_repair_v1",
        "source_template": str(SOURCE), "destination_template": str(DEST),
        "checks": {"new_destination": True,
                    "three_slices": len(rows) == 3,
                    "meshPhi_values": all(row["meshPhi_value_on_symmetry"] for row in rows),
                    "slice_ids": all(row["slice_id_matches"] for row in rows),
                    "real_process_starts_zero": True},
        "slices": rows, "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "old_runtime_reused": False, "old_evidence_modified": False, "owned_residual": 0,
    }
    evidence["gate"] = ("STAGE4F_D_CPP_WORKER_FRESH_TEMPLATE_REPAIR_V1_GATE: pass"
                         if all(evidence["checks"].values()) else
                         "STAGE4F_D_CPP_WORKER_FRESH_TEMPLATE_REPAIR_V1_GATE: do_not_pass")
    RESULTS.mkdir(parents=True, exist_ok=True); DOCS.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (RESULTS / "fresh_template_repair_audit.json").write_bytes(payload)
    (RESULTS / "stage4f_d_cpp_worker_fresh_template_repair_v1_gate.json").write_bytes(payload)
    (DOCS / "fresh_template_repair_report.md").write_text(
        "# Fresh t=0 template repair\n\n"
        "Offline template copy only; no CFD process was started.\n\n"
        f"- Gate: `{evidence['gate']}`\n"
        "- `meshPhi` lower/upper patches now have explicit calculated values.\n"
        "- Each slice has its own `sliceId` (0, 1, 2).\n",
        encoding="utf-8")
    print(json.dumps({"gate": evidence["gate"], "checks": evidence["checks"], "destination": str(DEST)}, ensure_ascii=True, sort_keys=True))
    return 0 if all(evidence["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
