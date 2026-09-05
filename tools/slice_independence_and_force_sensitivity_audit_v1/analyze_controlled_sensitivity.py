#!/usr/bin/env python3
"""Read-only geometry and field-difference evidence for controlled test v6."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime" / "slice_force_sensitivity_controlled_v6"
RESULTS = ROOT / "results" / "slice_force_sensitivity_controlled_v6"
NUMBER = r"[-+0-9.eE]+"


def cylinder_centroid(case: Path) -> dict[str, object]:
    mesh = case / "0.1" / "polyMesh"
    boundary = (case / "constant" / "polyMesh" / "boundary").read_text(encoding="utf-8")
    block = re.search(r"\bcylinder\s*\{(.*?)\}", boundary, re.S)
    if block is None:
        raise RuntimeError("cylinder patch missing")
    start = int(re.search(r"startFace\s+(\d+)\s*;", block.group(1)).group(1))
    count = int(re.search(r"nFaces\s+(\d+)\s*;", block.group(1)).group(1))
    points = np.array([[float(item) for item in row] for row in re.findall(r"\(\s*(%s)\s+(%s)\s+(%s)\s*\)" % (NUMBER, NUMBER, NUMBER), (mesh / "points").read_text(encoding="utf-8"))])
    faces = []
    for line in (case / "constant" / "polyMesh" / "faces").read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*\d+\(([^)]*)\)", line)
        if match:
            faces.append([int(item) for item in match.group(1).split()])
    selected = faces[start:start + count]
    centres = [points[face].mean(axis=0) for face in selected]
    unique = sorted({index for face in selected for index in face})
    surface = points[unique]
    return {"face_count": count, "point_count": len(unique), "face_centroid_m": np.mean(centres, axis=0).tolist(),
            "point_centroid_m": surface.mean(axis=0).tolist(), "point_min_m": surface.min(axis=0).tolist(), "point_max_m": surface.max(axis=0).tolist()}


def field_values(path: Path, vector: bool) -> np.ndarray:
    text = path.read_text(encoding="utf-8")
    marker = "internalField   nonuniform List<vector>" if vector else "internalField   nonuniform List<scalar>"
    rest = text[text.index(marker) + len(marker):]
    count = int(re.search(r"\s*(\d+)\s*\(", rest).group(1)); rest = rest[rest.index("(") + 1:]
    if vector:
        rows = re.findall(r"\(\s*(%s)\s+(%s)\s+(%s)\s*\)" % (NUMBER, NUMBER, NUMBER), rest)[:count]
        return np.asarray(rows, dtype=float)
    return np.asarray([float(item) for item in rest.split(")", 1)[0].split()[:count]])


def main() -> int:
    cases = [RUNTIME / "cases" / f"offset_{index:04d}" for index in range(3)]
    if not all(case.is_dir() for case in cases):
        raise RuntimeError("controlled runtime missing")
    geometry = [cylinder_centroid(case) for case in cases]
    fields: dict[str, object] = {}
    for name, vector in (("U", True), ("p", False)):
        values = [field_values(case / "0.1" / name, vector) for case in cases]
        fields[name] = {"l2_pair_differences": {"0-1": float(np.linalg.norm(values[0] - values[1])), "0-2": float(np.linalg.norm(values[0] - values[2])), "1-2": float(np.linalg.norm(values[1] - values[2]))},
                        "max_abs_pair_differences": {"0-1": float(np.max(np.abs(values[0] - values[1]))), "0-2": float(np.max(np.abs(values[0] - values[2]))), "1-2": float(np.max(np.abs(values[1] - values[2])))}}
    result = {"runtime": str(RUNTIME), "time_s": 0.1, "cylinder_actual_mesh_geometry": geometry, "field_differences": fields}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "controlled_sensitivity_mesh_and_field_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
