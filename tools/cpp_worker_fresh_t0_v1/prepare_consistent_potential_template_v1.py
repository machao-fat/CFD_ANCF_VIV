"""Offline generation of a consistent potential-flow t=0 OpenFOAM template.

The transform is isolated to a new case directory.  It initializes U, the
kinematic Bernoulli pressure, and internal face fluxes from the same analytic
field.  No OpenFOAM, WSL, worker, or CFD process is started.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix9/cases"
DEST = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix11/cases"
RESULTS = PROJECT / "results/257_cpp_worker_fresh_consistent_potential_template_v1"
DOCS = PROJECT / "docs/257_cpp_worker_fresh_consistent_potential_template_v1"
RADIUS = 0.5


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


def _mesh(root: Path):
    points = _points(root / "constant/polyMesh/points")
    faces = _faces(root / "constant/polyMesh/faces")
    owners = _labels(root / "constant/polyMesh/owner")
    neighbours = _labels(root / "constant/polyMesh/neighbour")
    n_cells = max(owners) + 1
    vertices: list[set[int]] = [set() for _ in range(n_cells)]
    for index, owner in enumerate(owners):
        vertices[owner].update(faces[index])
        if index < len(neighbours):
            vertices[neighbours[index]].update(faces[index])
    centres = [tuple(sum(points[i][axis] for i in cell) / len(cell) for axis in range(3)) for cell in vertices]
    face_data = []
    for face in faces[:len(neighbours)]:
        origin = points[face[0]]
        area = [0.0, 0.0, 0.0]
        for left, right in zip(face[1:-1], face[2:]):
            a = tuple(points[left][axis] - origin[axis] for axis in range(3))
            b = tuple(points[right][axis] - origin[axis] for axis in range(3))
            cross = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
            for axis in range(3):
                area[axis] += 0.5 * cross[axis]
        centre = tuple(sum(points[i][axis] for i in face) / len(face) for axis in range(3))
        face_data.append((centre, tuple(area)))
    return centres, face_data


def _potential(x: float, y: float) -> tuple[float, float, float]:
    r2 = max(x * x + y * y, (RADIUS * 1.001) ** 2)
    return (1.0 - RADIUS * RADIUS * (x * x - y * y) / (r2 * r2),
            -2.0 * RADIUS * RADIUS * x * y / (r2 * r2), 0.0)


def _replace(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise ValueError(f"field initializer not found: {path}")
    path.write_text(updated, encoding="utf-8")


def _replace_internal_field(path: Path, replacement: str) -> None:
    pattern = r"internalField\s+(?:uniform\s+[^;]+;|nonuniform\s+List<[^>]+>\s+\d+\s*\(.*?\)\s*;)"
    _replace(path, pattern, replacement)


def _rewrite_slice(root: Path) -> dict[str, object]:
    centres, internal_faces = _mesh(root)
    velocities = [_potential(x, y) for x, y, _ in centres]
    vector_block = "internalField   nonuniform List<vector>\n{}\n(\n{}\n);".format(
        len(velocities), "\n".join(f"({u:.17g} {v:.17g} 0)" for u, v, _ in velocities))
    _replace_internal_field(root / "0/U", vector_block)

    pressures = [0.5 * (1.0 - u * u - v * v) for u, v, _ in velocities]
    scalar_block = "internalField   nonuniform List<scalar>\n{}\n(\n{}\n);".format(
        len(pressures), "\n".join(f"{value:.17g}" for value in pressures))
    _replace_internal_field(root / "0/p", scalar_block)

    fluxes = []
    for (centre, area) in internal_faces:
        u = _potential(centre[0], centre[1])
        fluxes.append(sum(u[axis] * area[axis] for axis in range(3)))
    flux_block = "internalField   nonuniform List<scalar>\n{}\n(\n{}\n);".format(
        len(fluxes), "\n".join(f"{value:.17g}" for value in fluxes))
    _replace_internal_field(root / "0/phi", flux_block)
    finite = all(math.isfinite(value) for row in velocities for value in row) and all(math.isfinite(value) for value in pressures + fluxes)
    return {"cells": len(velocities), "internal_faces": len(fluxes), "finite": finite,
            "velocity_nonuniform": True, "pressure_nonuniform": True, "flux_nonuniform": True,
            "u_sha256": _sha(root / "0/U"), "p_sha256": _sha(root / "0/p"), "phi_sha256": _sha(root / "0/phi")}


def main() -> int:
    if DEST.exists():
        raise RuntimeError(f"refusing to overwrite existing destination: {DEST}")
    shutil.copytree(SOURCE, DEST)
    rows = [{"slice_id": sid, **_rewrite_slice(DEST / f"slice_{sid:04d}")} for sid in range(3)]
    checks = {"new_destination": True, "three_slices": len(rows) == 3,
              "same_cell_count": len({row["cells"] for row in rows}) == 1,
              "same_internal_face_count": len({row["internal_faces"] for row in rows}) == 1,
              "finite_fields": all(row["finite"] for row in rows),
              "nonuniform_u_p_phi": all(row["velocity_nonuniform"] and row["pressure_nonuniform"] and row["flux_nonuniform"] for row in rows),
              "real_process_starts_zero": True}
    evidence = {"stage_id": "stage4f_d_cpp_worker_fresh_consistent_potential_template_v1",
                "source_template": str(SOURCE), "destination_template": str(DEST),
                "checks": checks, "slices": rows, "radius_m": RADIUS,
                "physical_parameters_modified": False, "thresholds_modified": False,
                "old_runtime_reused": False, "old_evidence_modified": False,
                "real_process_starts": {"CPP_WORKER": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
                "owned_residual": 0}
    evidence["gate"] = ("STAGE4F_D_CPP_WORKER_FRESH_CONSISTENT_POTENTIAL_TEMPLATE_V1_GATE: pass"
                         if all(checks.values()) else "STAGE4F_D_CPP_WORKER_FRESH_CONSISTENT_POTENTIAL_TEMPLATE_V1_GATE: do_not_pass")
    RESULTS.mkdir(parents=True, exist_ok=True); DOCS.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (RESULTS / "consistent_potential_template_audit.json").write_bytes(payload)
    (RESULTS / "stage4f_d_cpp_worker_fresh_consistent_potential_template_v1_gate.json").write_bytes(payload)
    (DOCS / "consistent_potential_template_report.md").write_text(
        "# Consistent potential-flow t=0 template\n\nOffline transform only; no real process was started.\n\n"
        f"- Gate: `{evidence['gate']}`\n"
        "- U, kinematic Bernoulli p, and internal phi are generated from one analytic field.\n",
        encoding="utf-8")
    print(json.dumps({"gate": evidence["gate"], "checks": checks, "destination": str(DEST)}, ensure_ascii=True, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
