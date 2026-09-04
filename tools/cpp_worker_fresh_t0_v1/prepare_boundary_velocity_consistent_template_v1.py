"""Offline repair of initial U/Uf boundary values for the fresh case.

The repair makes the inlet/outlet volume velocity use the same analytic
potential velocity as the internal field.  The cylinder face velocity is
explicitly zero in ``Uf`` to match the existing no-slip moving-wall contract.
No solver, physical parameter, or threshold is changed.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from pathlib import Path

from tools.cpp_worker_fresh_t0_v1 import prepare_boundary_consistent_template_v1 as base

PROJECT = base.PROJECT
SOURCE = base.DEST
DEST = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix16/cases"
RESULTS = PROJECT / "results/268_cpp_worker_fresh_boundary_velocity_repair_v1"
DOCS = PROJECT / "docs/268_cpp_worker_fresh_boundary_velocity_repair_v1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _patch_body(path: Path, patch: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^\s*{re.escape(patch)}\s*\{{([^{{}}]*)\}}", text)
    if not match:
        raise ValueError(f"patch {patch} missing from {path}")
    return match.group(1)


def _replace_patch_value(path: Path, patch: str, value: str) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = rf"(?ms)(^\s*{re.escape(patch)}\s*\{{)([^{{}}]*)(\}})"
    def replace(match: re.Match[str]) -> str:
        block = re.sub(r"(?ms)\s*value\s+(?:uniform\s+[^;]+;|nonuniform\s+List<[^>]+>.*?;)", "", match.group(2))
        return match.group(1) + block.rstrip() + "\n        " + value + "\n    " + match.group(3)
    updated, count = re.subn(pattern, replace, text, count=1)
    if count != 1:
        raise ValueError(f"could not rewrite {patch} in {path}")
    path.write_text(updated, encoding="utf-8")


def _vector_list(values: list[tuple[float, float, float]]) -> str:
    return "value nonuniform List<vector>\n        {}\n        (\n{}\n        );".format(
        len(values), "\n".join(f"            ({u:.17g} {v:.17g} {w:.17g})" for u, v, w in values))


def _boundary_vectors(root: Path, patch: str) -> list[tuple[float, float, float]]:
    points = base._points(root / "constant/polyMesh/points")
    faces = base._faces(root / "constant/polyMesh/faces")
    patches = base._patches(root / "constant/polyMesh/boundary")
    info = patches[patch]
    start, stop = info["startFace"], info["startFace"] + info["nFaces"]
    return [base._potential(*base._centre(points, face)[:2]) for face in faces[start:stop]]


def _rewrite_slice(root: Path) -> dict[str, object]:
    inlet = _boundary_vectors(root, "inlet")
    outlet = _boundary_vectors(root, "outlet")
    cylinder_count = base._patches(root / "constant/polyMesh/boundary")["cylinder"]["nFaces"]
    zero = [(0.0, 0.0, 0.0)] * cylinder_count
    _replace_patch_value(root / "0/U", "inlet", _vector_list(inlet))
    _replace_patch_value(root / "0/U", "outlet", _vector_list(outlet))
    _replace_patch_value(root / "0/Uf", "inlet", _vector_list(inlet))
    _replace_patch_value(root / "0/Uf", "outlet", _vector_list(outlet))
    _replace_patch_value(root / "0/Uf", "cylinder", _vector_list(zero))
    finite = all(math.isfinite(x) for row in inlet + outlet for x in row)
    return {"slice_id": int(root.name.split("_")[-1]), "inlet_count": len(inlet),
            "outlet_count": len(outlet), "cylinder_uf_zero_count": len(zero),
            "finite": finite, "U_sha256": _sha(root / "0/U"), "Uf_sha256": _sha(root / "0/Uf")}


def main() -> int:
    if DEST.exists():
        raise RuntimeError(f"refusing to overwrite existing destination: {DEST}")
    if not SOURCE.is_dir():
        raise RuntimeError(f"source template missing: {SOURCE}")
    shutil.copytree(SOURCE, DEST)
    rows = [_rewrite_slice(DEST / f"slice_{sid:04d}") for sid in range(3)]
    checks = {
        "new_destination": True, "three_slices": len(rows) == 3,
        "inlet_outlet_face_counts": all(r["inlet_count"] == 60 and r["outlet_count"] == 60 for r in rows),
        "cylinder_uf_zero_count": all(r["cylinder_uf_zero_count"] == 40 for r in rows),
        "finite_boundary_velocities": all(r["finite"] for r in rows),
        "same_hashes_across_slices": len({(r["U_sha256"], r["Uf_sha256"]) for r in rows}) == 1,
        "source_separate": SOURCE.resolve() != DEST.resolve(), "real_process_starts_zero": True,
    }
    evidence = {"stage_id": "stage4f_d_cpp_worker_fresh_boundary_velocity_repair_v1",
                "source_template": str(SOURCE), "destination_template": str(DEST),
                "checks": checks, "slices": rows,
                "physical_parameters_modified": False, "thresholds_modified": False,
                "no_slip_cylinder_preserved": True, "old_runtime_reused": False,
                "real_process_starts": {"CPP_WORKER": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
                "owned_residual": 0,
                "gate": ("STAGE4F_D_CPP_WORKER_FRESH_BOUNDARY_VELOCITY_REPAIR_V1_GATE: pass"
                         if all(checks.values()) else
                         "STAGE4F_D_CPP_WORKER_FRESH_BOUNDARY_VELOCITY_REPAIR_V1_GATE: do_not_pass")}
    RESULTS.mkdir(parents=True, exist_ok=True); DOCS.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (RESULTS / "boundary_velocity_repair_audit.json").write_bytes(payload)
    (RESULTS / "stage4f_d_cpp_worker_fresh_boundary_velocity_repair_v1_gate.json").write_bytes(payload)
    (DOCS / "boundary_velocity_repair_report.md").write_text(
        "# Boundary velocity repair\n\nOffline template generation only; no external process was started.\n\n"
        f"- Gate: `{evidence['gate']}`\n"
        "- Inlet/outlet U and Uf use the same analytic potential velocity as the internal seed.\n"
        "- Cylinder Uf remains zero, preserving the no-slip wall contract.\n",
        encoding="utf-8")
    print(json.dumps({"gate": evidence["gate"], "checks": checks, "destination": str(DEST)}, ensure_ascii=True, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
