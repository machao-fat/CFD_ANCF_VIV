"""Offline repair of the fresh t=0 template boundary fluxes.

The source template is immutable.  This stage derives boundary ``phi`` and
``Uf`` values from the same analytic potential velocity used for the internal
seed.  It never starts OpenFOAM, WSL, MATLAB, the C++ worker, or CFD.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix11/cases"
DEST = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix15/cases"
RESULTS = PROJECT / "results/265_cpp_worker_fresh_boundary_consistency_repair_v4"
DOCS = PROJECT / "docs/265_cpp_worker_fresh_boundary_consistency_repair_v4"
RADIUS = 0.5
TARGET_PATCHES = ("inlet", "outlet", "cylinder")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"\n\s*\d+\s*\n\s*\((.*)\)\s*(?:;\s*)?(?:\n\s*//|\Z)", text, re.S)
    if not match:
        raise ValueError(f"OpenFOAM list not found: {path}")
    return match.group(1)


def _points(path: Path) -> list[tuple[float, float, float]]:
    rows = re.findall(r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", _body(path))
    return [(float(x), float(y), float(z)) for x, y, z in rows]


def _faces(path: Path) -> list[list[int]]:
    return [[int(value) for value in row.split()] for row in re.findall(r"\d+\(([^()]*)\)", _body(path))]


def _labels(path: Path) -> list[int]:
    return [int(value) for value in re.findall(r"(?<![0-9])[-+]?\d+(?![0-9])", _body(path))]


def _patches(path: Path) -> dict[str, dict[str, int]]:
    text = path.read_text(encoding="utf-8")
    result: dict[str, dict[str, int]] = {}
    for name, block in re.findall(r"(?ms)^\s*([A-Za-z0-9_]+)\s*\{(.*?)^\s*\}", text):
        nfaces = re.search(r"(?m)^\s*nFaces\s+(\d+)\s*;", block)
        start = re.search(r"(?m)^\s*startFace\s+(\d+)\s*;", block)
        if nfaces and start:
            result[name] = {"nFaces": int(nfaces.group(1)), "startFace": int(start.group(1))}
    if not result:
        raise ValueError("no boundary patches found")
    return result


def _area(pts: list[tuple[float, float, float]], face: list[int]) -> tuple[float, float, float]:
    origin = pts[face[0]]
    result = [0.0, 0.0, 0.0]
    for left, right in zip(face[1:-1], face[2:]):
        a = tuple(pts[left][axis] - origin[axis] for axis in range(3))
        b = tuple(pts[right][axis] - origin[axis] for axis in range(3))
        cross = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
        for axis in range(3):
            result[axis] += 0.5 * cross[axis]
    return tuple(result)


def _centre(pts: list[tuple[float, float, float]], face: list[int]) -> tuple[float, float, float]:
    return tuple(sum(pts[index][axis] for index in face) / len(face) for axis in range(3))


def _potential(x: float, y: float) -> tuple[float, float, float]:
    r2 = max(x * x + y * y, (RADIUS * 1.001) ** 2)
    return (1.0 - RADIUS * RADIUS * (x * x - y * y) / (r2 * r2),
            -2.0 * RADIUS * RADIUS * x * y / (r2 * r2), 0.0)


def _patch_block(path: Path, patch: str) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"(?ms)(^\s*{re.escape(patch)}\s*\{{)([^{{}}]*)(\}})", text)
    if not match:
        raise ValueError(f"patch {patch} not found in {path}")
    return text, match.group(2)


def _replace_patch_value(path: Path, patch: str, value: str) -> None:
    text, _ = _patch_block(path, patch)
    pattern = rf"(?ms)(^\s*{re.escape(patch)}\s*\{{)([^{{}}]*)(\}})"
    def replace(match: re.Match[str]) -> str:
        block = re.sub(r"(?ms)\s*value\s+(?:uniform\s+[^;]+;|nonuniform\s+List<[^>]+>.*?;)", "", match.group(2))
        block = block.rstrip() + "\n        " + value + "\n    "
        return match.group(1) + block + match.group(3)
    updated, count = re.subn(pattern, replace, text, count=1)
    if count != 1:
        raise ValueError(f"cannot rewrite patch {patch} in {path}")
    path.write_text(updated, encoding="utf-8")


def _scalar_list(values: list[float]) -> str:
    return "value nonuniform List<scalar>\n        {}\n        (\n{}\n        );".format(
        len(values), "\n".join(f"            {value:.17g}" for value in values))


def _vector_list(values: list[tuple[float, float, float]]) -> str:
    return "value nonuniform List<vector>\n        {}\n        (\n{}\n        );".format(
        len(values), "\n".join(f"            ({u:.17g} {v:.17g} {w:.17g})" for u, v, w in values))


def _rewrite_slice(root: Path) -> dict[str, object]:
    mesh = root / "constant/polyMesh"
    points = _points(mesh / "points")
    faces = _faces(mesh / "faces")
    patches = _patches(mesh / "boundary")
    boundary_values: dict[str, dict[str, object]] = {}
    total_flux = 0.0
    finite = True
    for patch in TARGET_PATCHES:
        info = patches[patch]
        start = info["startFace"]
        stop = start + info["nFaces"]
        fluxes: list[float] = []
        velocities: list[tuple[float, float, float]] = []
        for face in faces[start:stop]:
            c = _centre(points, face)
            a = _area(points, face)
            velocity = _potential(c[0], c[1])
            flux = sum(velocity[axis] * a[axis] for axis in range(3))
            fluxes.append(flux)
            velocities.append(velocity)
            total_flux += flux
        finite = finite and all(math.isfinite(x) for x in fluxes for _ in (0,))
        finite = finite and all(math.isfinite(x) for row in velocities for x in row)
        _replace_patch_value(root / "0/phi", patch, _scalar_list(fluxes))
        _replace_patch_value(root / "0/Uf", patch, _vector_list(velocities))
        boundary_values[patch] = {
            "nFaces": info["nFaces"], "startFace": start,
            "phi_count": len(fluxes), "Uf_count": len(velocities),
            "phi_sha256": _sha(root / "0/phi"), "Uf_sha256": _sha(root / "0/Uf"),
            "phi_sum": sum(fluxes), "max_abs_phi": max((abs(x) for x in fluxes), default=0.0),
        }
    # meshPhi is stationary at t=0; make zero explicit on every calculated patch.
    for patch in TARGET_PATCHES:
        _replace_patch_value(root / "0/meshPhi", patch, "value uniform 0;")
    # The two symmetry patches are explicitly audited as zero-valued mesh flux.
    boundary_text = (root / "0/meshPhi").read_text(encoding="utf-8")
    meshphi_zero = all(re.search(rf"(?ms)^\s*{patch}\s*\{{.*?value\s+uniform\s+0\s*;.*?\}}", boundary_text)
                       for patch in ("lower", "upper", *TARGET_PATCHES))
    return {"slice_id": int(root.name.split("_")[-1]), "patches": boundary_values,
            "total_target_patch_flux": total_flux, "finite": finite,
            "target_flux_scale": max(1.0, sum(abs(float(boundary_values[p]["phi_sum"])) for p in TARGET_PATCHES)),
            "meshPhi_zero_explicit": bool(meshphi_zero),
            "phi_boundary_sha256": _sha(root / "0/phi"), "Uf_boundary_sha256": _sha(root / "0/Uf")}


def main() -> int:
    if DEST.exists():
        raise RuntimeError(f"refusing to overwrite existing destination: {DEST}")
    if not SOURCE.is_dir():
        raise RuntimeError(f"source template missing: {SOURCE}")
    shutil.copytree(SOURCE, DEST)
    rows = [_rewrite_slice(DEST / f"slice_{sid:04d}") for sid in range(3)]
    checks = {
        "new_destination": True,
        "three_slices": len(rows) == 3,
        "same_boundary_face_counts": len({tuple((p, r["patches"][p]["nFaces"]) for p in TARGET_PATCHES) for r in rows}) == 1,
        "boundary_phi_and_uf_counts_match": all(all(v["phi_count"] == v["Uf_count"] == v["nFaces"] for v in r["patches"].values()) for r in rows),
        "finite_boundary_values": all(r["finite"] for r in rows),
        "meshPhi_zero_explicit": all(r["meshPhi_zero_explicit"] for r in rows),
        # Face-centre quadrature leaves a small, measurable polygonal-mesh
        # imbalance.  Require it to remain below 1e-3 relative to the
        # through-flow scale; this is an audit criterion, not a solver setting.
        "closed_target_flux_relative": all(
            abs(r["total_target_patch_flux"]) / r["target_flux_scale"] < 1e-3 for r in rows),
        "real_process_starts_zero": True,
    }
    evidence = {
        "stage_id": "stage4f_d_cpp_worker_fresh_boundary_consistency_repair_v4",
        "source_template": str(SOURCE), "destination_template": str(DEST),
        "checks": checks, "slices": rows,
        "mapping": "same analytic potential velocity -> internal U/phi and boundary phi/Uf",
        "physical_parameters_modified": False, "thresholds_modified": False,
        "old_runtime_reused": False, "old_evidence_modified": False,
        "real_process_starts": {"CPP_WORKER": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
    }
    evidence["gate"] = ("STAGE4F_D_CPP_WORKER_FRESH_BOUNDARY_CONSISTENCY_REPAIR_V4_GATE: pass"
                         if all(checks.values()) else
                         "STAGE4F_D_CPP_WORKER_FRESH_BOUNDARY_CONSISTENCY_REPAIR_V4_GATE: do_not_pass")
    RESULTS.mkdir(parents=True, exist_ok=True); DOCS.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (RESULTS / "boundary_consistency_repair_audit.json").write_bytes(payload)
    (RESULTS / "stage4f_d_cpp_worker_fresh_boundary_consistency_repair_v4_gate.json").write_bytes(payload)
    (DOCS / "boundary_consistency_repair_report.md").write_text(
        "# Fresh t=0 boundary consistency repair\n\n"
        "Offline template generation only; no external process was started.\n\n"
        f"- Gate: `{evidence['gate']}`\n"
        "- Boundary `phi` and `Uf` are derived from the same analytic velocity as the internal seed.\n"
        "- `meshPhi` is explicitly zero at the stationary seed.\n"
        "- No physical parameter, threshold, solver core, or historical evidence was modified.\n",
        encoding="utf-8")
    print(json.dumps({"gate": evidence["gate"], "checks": checks, "destination": str(DEST)}, ensure_ascii=True, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
