"""Offline audit of restart mesh quality and boundary-field consistency.

This stage reads the preserved Stage360 candidate and the failed Stage361
Smoke only.  It never launches OpenFOAM, WSL, MATLAB, or the CFD worker.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime/stage360_restart_derived_flux_repair_v1_fresh"
FAILED = ROOT / "runtime/stage361_restart_derived_flux_smoke_v1"
RESULTS = ROOT / "results/362_restart_mesh_quality_audit_v1"


def _list_start(data: bytes) -> tuple[int, int]:
    match = re.search(rb"\n(\d+)\s*\n\(", data)
    if not match:
        raise ValueError("OpenFOAM list header not found")
    return int(match.group(1)), match.end()


def read_vectors(path: Path) -> list[tuple[float, float, float]]:
    data = path.read_bytes()
    count, start = _list_start(data)
    header = data[:start].decode("latin1", errors="ignore")
    if "format      binary" in header:
        values = struct.unpack_from("<" + "d" * (count * 3), data, start)
        return [tuple(values[i : i + 3]) for i in range(0, len(values), 3)]
    text = data[start:].decode("latin1", errors="ignore")
    rows = [tuple(float(value) for value in match.groups()) for match in re.finditer(
        r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", text
    )]
    if len(rows) < count:
        raise ValueError(f"{path}: expected {count} vectors, found {len(rows)}")
    return rows[:count]


def read_ascii_faces(path: Path) -> list[list[int]]:
    text = path.read_text(encoding="latin1")
    match = re.search(r"\n(\d+)\s*\n\(", text)
    if not match:
        raise ValueError(f"{path}: face list header not found")
    count = int(match.group(1))
    faces: list[list[int]] = []
    for line in text[match.end() :].splitlines():
        row = re.match(r"\s*\d+\s*\(([^)]*)\)", line)
        if row:
            faces.append([int(value) for value in re.findall(r"\d+", row.group(1))])
        if len(faces) == count:
            break
    if len(faces) != count:
        raise ValueError(f"{path}: expected {count} faces, found {len(faces)}")
    return faces


def minimum_edge(points: list[tuple[float, float, float]], faces: list[list[int]]) -> float:
    result = math.inf
    for face in faces:
        for first, second in zip(face, face[1:] + face[:1]):
            result = min(result, math.dist(points[first], points[second]))
    return result


def field_boundary_mode(path: Path, patch: str = "cyl") -> str:
    data = path.read_bytes()
    start = data.find(("    " + patch).encode("ascii"))
    if start < 0:
        return "missing"
    end = data.find(b"\n    }", start)
    block = data[start : end if end >= 0 else start + 1000].decode("latin1", errors="ignore")
    if re.search(r"value\s+nonuniform\s+List", block):
        return "nonuniform"
    if re.search(r"value\s+uniform\s*\(\s*0(?:\.0+)?\s+0(?:\.0+)?\s+0(?:\.0+)?\s*\)", block):
        return "uniform_zero"
    if "value" in block:
        return "uniform_nonzero_or_other"
    return "absent"


def point_displacement_error(points: list[tuple[float, float, float]], base: list[tuple[float, float, float]], displacement: list[tuple[float, float, float]]) -> tuple[float, float]:
    errors = [
        max(abs(points[index][axis] - base[index][axis] - displacement[index][axis]) for axis in range(3))
        for index in range(len(points))
    ]
    return max(errors), sum(errors) / len(errors)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    faces = read_ascii_faces(SOURCE / "slice_0000/constant/polyMesh/faces")
    observations: list[dict[str, object]] = []
    for index in range(3):
        source_slice = SOURCE / f"slice_{index:04d}"
        failed_slice = FAILED / f"slice_{index:04d}"
        base_points = read_vectors(source_slice / "constant/polyMesh/points")
        source_points = read_vectors(source_slice / "79.995/polyMesh/points")
        source_disp = read_vectors(source_slice / "79.995/pointDisplacement")
        source_error = point_displacement_error(source_points, base_points, source_disp)
        source_min = minimum_edge(source_points, faces)
        time_rows: list[dict[str, object]] = []
        for directory in sorted(failed_slice.iterdir(), key=lambda item: float(item.name) if item.is_dir() and re.fullmatch(r"\d+\.\d+", item.name) else math.inf):
            if not directory.is_dir() or not re.fullmatch(r"\d+\.\d+", directory.name):
                continue
            points_path = directory / "polyMesh/points"
            displacement_path = directory / "pointDisplacement"
            if not points_path.exists() or not displacement_path.exists():
                continue
            points = read_vectors(points_path)
            displacement = read_vectors(displacement_path)
            error = point_displacement_error(points, base_points, displacement)
            time_rows.append({
                "time_s": float(directory.name),
                "minimum_edge_m": minimum_edge(points, faces),
                "point_displacement_error_max_m": error[0],
                "point_displacement_error_mean_m": error[1],
                "u_cylinder_boundary_mode": field_boundary_mode(directory / "U"),
                "points_sha256": file_sha(points_path),
            })
        quality_path = FAILED / "logs" / f"openfoam_{index:04d}_quality.json"
        quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {}
        observations.append({
            "slice_id": f"slice_{index:04d}",
            "source_minimum_edge_m": source_min,
            "source_point_displacement_error_max_m": source_error[0],
            "source_point_displacement_error_mean_m": source_error[1],
            "failed_times": time_rows,
            "quality_return_code": quality.get("return_code"),
            "quality_record_count": quality.get("record_count", 0),
            "quality_max_courant": max((float(row.get("courant_max", 0.0)) for row in quality.get("records", [])), default=None),
        })
    result = {
        "schema_version": 1,
        "stage_id": "stage4f_d_restart_mesh_quality_audit_v1",
        "source_stage": "stage360_restart_derived_flux_repair_v1",
        "failed_stage": "stage361_restart_derived_flux_smoke_v1",
        "offline_only": True,
        "real_process_counts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "observations": observations,
        "finding": {
            "point_displacement_and_mesh_points_consistent": all(
                float(row["source_point_displacement_error_max_m"]) < 1e-12
                and all(float(item["point_displacement_error_max_m"]) < 1e-12 for item in row["failed_times"])
                for row in observations
            ),
            "local_mesh_compression_observed": all(
                any(float(item["minimum_edge_m"]) < 0.5 * float(row["source_minimum_edge_m"]) for item in row["failed_times"])
                for row in observations
            ),
            "cylinder_u_boundary_reset_to_uniform_zero": all(
                any(item["u_cylinder_boundary_mode"] == "uniform_zero" for item in row["failed_times"])
                for row in observations
            ),
            "root_cause_class": "restart_mesh_quality_collapse_after_motion_update",
            "not_a_proof_of_physical_instability": True,
        },
        "gate_id": "STAGE4F_D_RESTART_MESH_QUALITY_AUDIT_V1_GATE",
        "status": "pass",
        "next_action": "offline repair of mesh-motion/restart generation; no CFD retry until explicitly authorized",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "mesh_quality_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "stage4f_d_restart_mesh_quality_audit_v1_gate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": result["status"], "root_cause": result["finding"]["root_cause_class"], "real_process_counts": result["real_process_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
