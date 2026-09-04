"""Prepare a fresh t=0 template with a consistent inviscid startup seed.

The seed uses the analytic potential-flow velocity field around the cylinder
and the corresponding Bernoulli kinematic pressure (p = 0.5*(1-|u|^2)).  The
consistent pressure prevents a spurious impulsive-pressure force at the first
solver step.  This is an offline template transform only; it does not invoke
OpenFOAM or any other external process and does not alter solver parameters
or thresholds.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix8/cases"
DEST = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix9/cases"
RESULTS = PROJECT / "results/252_cpp_worker_fresh_potential_template_v1"
DOCS = PROJECT / "docs/252_cpp_worker_fresh_potential_template_v1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _list_body(text: str) -> str:
    match = re.search(r"\n\s*\d+\s*\n\s*\((.*)\)\s*(?:;\s*)?(?:\n\s*//|\Z)", text, re.S)
    if not match:
        raise ValueError("OpenFOAM list body not found")
    return match.group(1)


def _points(path: Path) -> list[tuple[float, float, float]]:
    body = _list_body(path.read_text(encoding="utf-8"))
    rows = re.findall(r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", body)
    return [(float(x), float(y), float(z)) for x, y, z in rows]


def _labels(path: Path) -> list[int]:
    body = _list_body(path.read_text(encoding="utf-8"))
    return [int(item) for item in re.findall(r"(?<![0-9])[-+]?\d+(?![0-9])", body)]


def _cell_centres(root: Path) -> list[tuple[float, float, float]]:
    points = _points(root / "constant/polyMesh/points")
    face_text = _list_body((root / "constant/polyMesh/faces").read_text(encoding="utf-8"))
    faces = [[int(v) for v in values.split()] for values in
             re.findall(r"\d+\(([^()]*)\)", face_text)]
    owners = _labels(root / "constant/polyMesh/owner")
    neighbours = _labels(root / "constant/polyMesh/neighbour")
    n_cells = max(owners) + 1
    vertices: list[set[int]] = [set() for _ in range(n_cells)]
    for face_index, owner in enumerate(owners):
        vertices[owner].update(faces[face_index])
        if face_index < len(neighbours):
            vertices[neighbours[face_index]].update(faces[face_index])
    centres = []
    for cell in vertices:
        if not cell:
            raise ValueError("cell has no vertices")
        centres.append(tuple(sum(points[i][axis] for i in cell) / len(cell) for axis in range(3)))
    return centres


def _rewrite_u(root: Path) -> dict[str, object]:
    path = root / "0/U"
    text = path.read_text(encoding="utf-8")
    centres = _cell_centres(root)
    values: list[tuple[float, float, float]] = []
    radius = 0.5
    for x, y, _z in centres:
        r2 = max(x * x + y * y, (radius * 1.001) ** 2)
        u = 1.0 - radius * radius * (x * x - y * y) / (r2 * r2)
        v = -2.0 * radius * radius * x * y / (r2 * r2)
        values.append((u, v, 0.0))
    block = "internalField   nonuniform List<vector>\n{}\n(\n{}\n);".format(
        len(values), "\n".join(f"({u:.17g} {v:.17g} 0)" for u, v, _ in values))
    updated, count = re.subn(
        r"internalField\s+(?:uniform\s+\([^;]+\)|nonuniform\s+List<vector>\s*\d+\s*\(.*?\))\s*;",
        block, text, count=1, flags=re.S)
    if count != 1:
        raise ValueError("U internalField not found")
    path.write_text(updated, encoding="utf-8")
    return {"cells": len(values), "sha256": _sha(path), "potential_flow": True,
            "finite": all(math.isfinite(v) for row in values for v in row)}


def _rewrite_p(root: Path, centres: list[tuple[float, float, float]]) -> dict[str, object]:
    """Bernoulli kinematic pressure consistent with the potential velocity."""
    path = root / "0" / "p"
    text = path.read_text(encoding="utf-8")
    radius = 0.5
    values = []
    for x, y, _z in centres:
        r2 = max(x * x + y * y, (radius * 1.001) ** 2)
        u = 1.0 - radius * radius * (x * x - y * y) / (r2 * r2)
        v = -2.0 * radius * radius * x * y / (r2 * r2)
        values.append(0.5 * (1.0 - (u * u + v * v)))
    block = ("internalField   nonuniform List<scalar>\n{}\n(\n{}\n);".format(
        len(values), "\n".join(f"{value:.17g}" for value in values)))
    updated, count = re.subn(
        r"internalField\s+(?:uniform\s+[^;]+|nonuniform\s+List<scalar>\s*\d+\s*\(.*?\))\s*;",
        block, text, count=1, flags=re.S)
    if count != 1:
        raise ValueError("p internalField not found")
    path.write_text(updated, encoding="utf-8")
    return {"cells": len(values), "sha256": _sha(path), "bernoulli_pressure": True,
            "finite": all(math.isfinite(value) for value in values)}


def main() -> int:
    if DEST.exists():
        raise RuntimeError(f"refusing to overwrite existing destination: {DEST}")
    shutil.copytree(SOURCE, DEST)
    rows = []
    for sid in range(3):
        root = DEST / f"slice_{sid:04d}"
        result = _rewrite_u(root)
        centres = _cell_centres(root)
        pressure = _rewrite_p(root, centres)
        rows.append({"slice_id": sid, **result, "pressure": pressure})
    checks = {"new_destination": True, "three_slices": len(rows) == 3,
              "finite_potential_seed": all(row["finite"] for row in rows),
              "finite_bernoulli_pressure": all(row["pressure"]["finite"] for row in rows),
              "same_cell_count": len({row["cells"] for row in rows}) == 1,
              "real_process_starts_zero": True}
    evidence = {"stage_id": "stage4f_d_cpp_worker_fresh_potential_template_v1",
                "source_template": str(SOURCE), "destination_template": str(DEST),
                "checks": checks, "slices": rows,
                "physical_parameters_modified": False, "thresholds_modified": False,
                "old_runtime_reused": False, "old_evidence_modified": False,
                "real_process_starts": {"CPP_WORKER": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
                "owned_residual": 0}
    evidence["gate"] = ("STAGE4F_D_CPP_WORKER_FRESH_POTENTIAL_TEMPLATE_V1_GATE: pass"
                         if all(checks.values()) else
                         "STAGE4F_D_CPP_WORKER_FRESH_POTENTIAL_TEMPLATE_V1_GATE: do_not_pass")
    RESULTS.mkdir(parents=True, exist_ok=True); DOCS.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (RESULTS / "potential_template_audit.json").write_bytes(payload)
    (RESULTS / "stage4f_d_cpp_worker_fresh_potential_template_v1_gate.json").write_bytes(payload)
    (DOCS / "potential_template_report.md").write_text(
        "# Fresh t=0 potential-flow seed\n\nOffline template transform only; no real process was started.\n\n"
        f"- Gate: `{evidence['gate']}`\n"
        "- Internal `U` uses the analytic cylinder potential-flow seed.\n"
        "- Internal `p` uses the matching Bernoulli kinematic pressure.\n",
        encoding="utf-8")
    print(json.dumps({"gate": evidence["gate"], "checks": checks, "destination": str(DEST)}, ensure_ascii=True, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
