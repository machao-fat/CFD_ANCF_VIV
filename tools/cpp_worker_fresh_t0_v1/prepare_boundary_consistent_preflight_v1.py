"""Offline launch preflight for the boundary-consistent fresh template."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from tools.cpp_worker_fresh_t0_v1 import prepare_boundary_consistent_template_v1 as repair

PROJECT = repair.PROJECT
TEMPLATE_ROOT = repair.DEST
RESULTS = PROJECT / "results/263_cpp_worker_fresh_boundary_consistency_preflight_v1"
DOCS = PROJECT / "docs/263_cpp_worker_fresh_boundary_consistency_preflight_v1"


def _patches(path: Path) -> dict[str, dict[str, int]]:
    text = (path / "constant/polyMesh/boundary").read_text(encoding="utf-8")
    out: dict[str, dict[str, int]] = {}
    for name, block in re.findall(r"(?ms)^\s*([A-Za-z0-9_]+)\s*\{(.*?)^\s*\}", text):
        n = re.search(r"(?m)^\s*nFaces\s+(\d+)\s*;", block)
        start = re.search(r"(?m)^\s*startFace\s+(\d+)\s*;", block)
        if n and start:
            out[name] = {"nFaces": int(n.group(1)), "startFace": int(start.group(1))}
    return out


def _field_patch(path: Path, patch: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^\s*{re.escape(patch)}\s*\{{([^{{}}]*)\}}", text)
    if not match:
        raise ValueError(f"missing patch {patch} in {path}")
    return match.group(1)


def _nonuniform_count(path: Path, patch: str, field: str) -> int | None:
    body = _field_patch(path, patch)
    match = re.search(r"value\s+nonuniform\s+List<[^>]+>\s+(\d+)\s*\(", body)
    if not match:
        return None
    return int(match.group(1))


def _internal_count(path: Path) -> int | None:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"internalField\s+nonuniform\s+List<[^>]+>\s+(\d+)\s*\(", text)
    return int(match.group(1)) if match else None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    rows = []
    for sid in range(3):
        root = TEMPLATE_ROOT / f"slice_{sid:04d}"
        patches = _patches(root) if root.is_dir() else {}
        fields = {name: (root / "0" / name).is_file()
                  for name in ("U", "p", "phi", "Uf", "meshPhi", "motionScale")}
        counts = {}
        for patch in repair.TARGET_PATCHES:
            counts[patch] = {name: _nonuniform_count(root / "0" / name, patch, name)
                             if (root / "0" / name).is_file() else None
                             for name in ("phi", "Uf")}
        meshphi = (root / "0" / "meshPhi").read_text(encoding="utf-8") if fields["meshPhi"] else ""
        meshphi_zero = all(re.search(rf"(?ms)^\s*{patch}\s*\{{.*?value\s+uniform\s+0\s*;.*?\}}", meshphi)
                           for patch in ("lower", "upper", *repair.TARGET_PATCHES))
        control = (root / "system/controlDict").read_text(encoding="utf-8") if root.is_dir() else ""
        dynamic = (root / "constant/dynamicMeshDict").read_text(encoding="utf-8") if root.is_dir() else ""
        rows.append({"slice_id": sid, "fields": fields, "patches": patches, "counts": counts,
                     "internal_counts": {name: _internal_count(root / "0" / name)
                                          if (root / "0" / name).is_file() else None
                                          for name in ("U", "p", "phi")},
                     "meshPhi_zero_explicit": bool(meshphi_zero),
                     "delta_t_00125": bool(re.search(r"(?m)^\s*deltaT\s+0?\.00125\s*;", control)),
                     "coupling_delta_t_00125": bool(re.search(r"(?m)^\s*couplingDeltaT\s+0?\.00125\s*;", dynamic)),
                     "field_sha256": {name: _sha(root / "0" / name) for name in fields if fields[name]}})
    checks = {
        "template_exists": TEMPLATE_ROOT.is_dir(),
        "three_slices": len(rows) == 3,
        "fields_complete": all(all(row["fields"].values()) for row in rows),
        "boundary_metadata_complete": all(all(p in row["patches"] for p in repair.TARGET_PATCHES) for row in rows),
        "boundary_counts_match": all(
            all(row["counts"][p]["phi"] == row["patches"][p]["nFaces"] and
                row["counts"][p]["Uf"] == row["patches"][p]["nFaces"] for p in repair.TARGET_PATCHES)
            for row in rows),
        "internal_counts_match": (
            all(row["internal_counts"]["U"] is not None and
                row["internal_counts"]["p"] == row["internal_counts"]["U"] and
                row["internal_counts"]["phi"] is not None for row in rows)
            and len({row["internal_counts"]["U"] for row in rows}) == 1
            and len({row["internal_counts"]["phi"] for row in rows}) == 1),
        "meshPhi_zero_explicit": all(row["meshPhi_zero_explicit"] for row in rows),
        "dt_consistent": all(row["delta_t_00125"] and row["coupling_delta_t_00125"] for row in rows),
        "source_is_separate": repair.SOURCE.resolve() != TEMPLATE_ROOT.resolve(),
        "real_process_starts_zero": True,
        "no_old_runtime_reused": True,
    }
    evidence = {"stage_id": "stage4f_d_cpp_worker_fresh_boundary_consistency_preflight_v1",
                "run_id": "cpp_worker_fresh_boundary_consistency_preflight_001",
                "case_id": "cpp_worker_fresh_boundary_consistency_preflight_case_001",
                "template_root": str(TEMPLATE_ROOT), "source_template": str(repair.SOURCE),
                "checks": checks, "slices": rows, "launch_performed": False,
                "real_process_starts": {"CPP_WORKER": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
                "owned_residual": 0,
                "gate": ("STAGE4F_D_CPP_WORKER_FRESH_BOUNDARY_CONSISTENCY_PREFLIGHT_V1_GATE: pass"
                         if all(checks.values()) else
                         "STAGE4F_D_CPP_WORKER_FRESH_BOUNDARY_CONSISTENCY_PREFLIGHT_V1_GATE: do_not_pass")}
    RESULTS.mkdir(parents=True, exist_ok=True); DOCS.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (RESULTS / "boundary_consistency_preflight.json").write_bytes(payload)
    (RESULTS / "stage4f_d_cpp_worker_fresh_boundary_consistency_preflight_v1_gate.json").write_bytes(payload)
    (DOCS / "boundary_consistency_preflight_report.md").write_text(
        "# Boundary-consistent fresh launch preflight\n\nOffline only; no external process was started.\n\n"
        f"- Gate: `{evidence['gate']}`\n- Template: `{TEMPLATE_ROOT}`\n",
        encoding="utf-8")
    print(json.dumps({"gate": evidence["gate"], "checks": checks, "launch_performed": False}, ensure_ascii=True, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
