"""Stage 368 restart-continuation diagnostic; never launches a solver."""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime/stage341_dt005_long_convergence_v1"
FAILED = ROOT / "runtime/stage367_restart_lag1_coherent_smoke_v1"
RESULTS = ROOT / "results/368_restart_continuation_diagnostic_v1"
DT = 0.005
SLICES = 3


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def list_header(data: bytes) -> tuple[int, int, bool]:
    match = re.search(rb"\n(\d+)\s*\n\(", data)
    if not match:
        raise ValueError("OpenFOAM list header not found")
    start = match.end()
    header = data[:start].decode("latin1", errors="ignore")
    return int(match.group(1)), start, "format      binary" in header


def read_vectors(path: Path) -> list[tuple[float, float, float]]:
    data = path.read_bytes()
    count, start, binary = list_header(data)
    if binary:
        values = struct.unpack_from("<" + "d" * (count * 3), data, start)
        return [tuple(values[i : i + 3]) for i in range(0, len(values), 3)]
    text = data[start:].decode("latin1", errors="ignore")
    rows = [tuple(float(v) for v in m.groups()) for m in re.finditer(
        r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", text
    )]
    if len(rows) < count:
        raise ValueError(f"{path}: expected {count} vectors, found {len(rows)}")
    return rows[:count]


def read_faces(path: Path) -> list[list[int]]:
    text = path.read_text(encoding="latin1")
    match = re.search(r"\n(\d+)\s*\n\(", text)
    if not match:
        raise ValueError(f"{path}: face list header not found")
    faces: list[list[int]] = []
    for line in text[match.end() :].splitlines():
        row = re.match(r"\s*\d+\s*\(([^)]*)\)", line)
        if row:
            faces.append([int(v) for v in re.findall(r"\d+", row.group(1))])
        if len(faces) == int(match.group(1)):
            break
    if len(faces) != int(match.group(1)):
        raise ValueError(f"{path}: incomplete face list")
    return faces


def min_edge(points: list[tuple[float, float, float]], faces: list[list[int]]) -> float:
    result = math.inf
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            result = min(result, math.dist(points[a], points[b]))
    return result


def finite_vectors(rows: list[tuple[float, float, float]]) -> bool:
    return all(math.isfinite(v) for row in rows for v in row)


def field_time(path: Path) -> str | None:
    if not path.is_file():
        return None
    header = path.read_bytes()[:1200].decode("latin1", errors="ignore")
    match = re.search(r"location\s+\"([^\"]+)\"", header)
    return match.group(1) if match else None


def boundary_mode(path: Path, patch: str = "cyl") -> str:
    if not path.is_file():
        return "missing"
    data = path.read_bytes()
    start = data.find(("    " + patch).encode())
    if start < 0:
        return "missing_patch"
    end = data.find(b"\n    }", start)
    block = data[start : end if end >= 0 else start + 2000].decode("latin1", errors="ignore")
    if re.search(r"value\s+nonuniform\s+List", block):
        return "nonuniform"
    if re.search(r"value\s+uniform\s*\(\s*0(?:\.0+)?\s+0(?:\.0+)?\s+0(?:\.0+)?\s*\)", block):
        return "uniform_zero"
    return "uniform_or_other" if "value" in block else "absent"


def field_record(path: Path) -> dict[str, object]:
    record: dict[str, object] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        return record
    stat = path.stat()
    record.update({"sha256": sha(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "field_time": field_time(path)})
    try:
        rows = read_vectors(path)
        record.update({"vector_count": len(rows), "finite": finite_vectors(rows)})
    except (ValueError, struct.error, UnicodeError):
        record["parseable_vector_field"] = False
    return record


def time_dirs(slice_path: Path) -> list[Path]:
    return sorted((p for p in slice_path.iterdir() if p.is_dir() and re.fullmatch(r"\d+(?:\.\d+)?", p.name)), key=lambda p: float(p.name))


def slice_audit(index: int, faces: list[list[int]]) -> dict[str, object]:
    source = SOURCE / f"slice_{index:04d}"
    failed = FAILED / f"slice_{index:04d}"
    result: dict[str, object] = {"slice_id": f"slice_{index:04d}", "source": {}, "failed": {}, "algorithm": {}}
    for label, root, wanted in (("source", source, ("79.995", "80")), ("failed", failed, ("80", "80.005", "80.01", "80.015", "80.02", "80.025", "80.03", "80.035"))):
        times: dict[str, object] = {}
        for name in wanted:
            directory = root / name
            if not directory.is_dir():
                times[name] = {"exists": False}
                continue
            row: dict[str, object] = {"exists": True}
            for field in ("U", "p", "pointDisplacement", "cellDisplacement", "phi", "meshPhi", "Uf"):
                row[field] = field_record(directory / field)
            row["u_cylinder_boundary_mode"] = boundary_mode(directory / "U")
            points = directory / "polyMesh/points"
            if points.is_file():
                try:
                    values = read_vectors(points)
                    row["points_finite"] = finite_vectors(values)
                    row["minimum_edge_m"] = min_edge(values, faces)
                except (ValueError, struct.error):
                    row["points_finite"] = False
            times[name] = row
        result[label] = times

    dynamic = failed / "constant/dynamicMeshDict"
    control = failed / "system/controlDict"
    fv_solution = failed / "system/fvSolution"
    dynamic_text = dynamic.read_text(encoding="latin1", errors="replace") if dynamic.is_file() else ""
    control_text = control.read_text(encoding="latin1", errors="replace") if control.is_file() else ""
    fv_text = fv_solution.read_text(encoding="latin1", errors="replace") if fv_solution.is_file() else ""
    result["algorithm"] = {
        "dynamic_mesh_sha256": sha(dynamic) if dynamic.is_file() else None,
        "motion_solver": re.search(r"motionSolver\s+([^;]+);", dynamic_text).group(1).strip() if re.search(r"motionSolver\s+([^;]+);", dynamic_text) else None,
        "diffusivity": re.search(r"diffusivity\s+([^;]+);", dynamic_text).group(1).strip() if re.search(r"diffusivity\s+([^;]+);", dynamic_text) else None,
        "start_from_latest": "startFrom       latestTime;" in control_text,
        "delta_t": re.search(r"deltaT\s+([^;]+);", control_text).group(1).strip() if re.search(r"deltaT\s+([^;]+);", control_text) else None,
        "move_mesh_outer_correctors": re.search(r"moveMeshOuterCorrectors\s+([^;]+);", fv_text).group(1).strip() if re.search(r"moveMeshOuterCorrectors\s+([^;]+);", fv_text) else None,
        "correct_phi": re.search(r"correctPhi\s+([^;]+);", fv_text).group(1).strip() if re.search(r"correctPhi\s+([^;]+);", fv_text) else None,
    }
    return result


def main() -> int:
    faces_path = SOURCE / "slice_0000/constant/polyMesh/faces"
    faces = read_faces(faces_path)
    slices = [slice_audit(i, faces) for i in range(SLICES)]
    quality: list[dict[str, object]] = []
    for i in range(SLICES):
        path = FAILED / "logs" / f"openfoam_{i:04d}_quality.json"
        quality.append(json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"missing": True})
    source_80_min = [float(s["source"]["80"]["minimum_edge_m"]) for s in slices if s["source"].get("80", {}).get("minimum_edge_m") is not None]
    failed_min = [[row.get("minimum_edge_m") for row in s["failed"].values() if isinstance(row, dict) and row.get("minimum_edge_m") is not None] for s in slices]
    dynamic = slices[0]["algorithm"]
    checks = {
        "source_80_fields_complete": all(all(s["source"].get("80", {}).get(f, {}).get("exists") for f in ("U", "p", "pointDisplacement", "cellDisplacement", "phi", "meshPhi", "Uf")) for s in slices),
        "source_80_geometry_finite": all(s["source"].get("80", {}).get("points_finite") is True for s in slices),
        "failed_first_step_fields_complete": all(all(s["failed"].get("80.005", {}).get(f, {}).get("exists") for f in ("U", "p", "pointDisplacement", "cellDisplacement", "phi", "meshPhi", "Uf")) for s in slices),
        "source_u_boundary_nonuniform": all(s["source"].get("80", {}).get("u_cylinder_boundary_mode") == "nonuniform" for s in slices),
        "failed_u_boundary_nonuniform": all(s["failed"].get("80.03", {}).get("u_cylinder_boundary_mode") == "nonuniform" for s in slices),
        "same_source_and_failed_geometry_clock": all(s["source"].get("80", {}).get("U", {}).get("field_time") == "80" and s["failed"].get("80", {}).get("U", {}).get("field_time") == "80" for s in slices),
        "three_slice_quality_records_present": all(int(q.get("record_count", 0)) > 0 for q in quality),
        "three_slice_quality_no_fpe": all(int(q.get("return_code", 0)) == 0 for q in quality),
        "dynamic_mesh_configuration_known": bool(dynamic.get("motion_solver") and dynamic.get("diffusivity")),
    }
    min_edge_drop = []
    for source_min, failed_rows in zip(source_80_min, failed_min):
        min_edge_drop.append({"source_minimum_edge_m": source_min, "failed_minimum_edge_m": min(failed_rows) if failed_rows else None, "ratio": (min(failed_rows) / source_min) if failed_rows and source_min else None})
    result = {
        "schema_version": 1,
        "stage_id": "stage4f_d_restart_continuation_diagnostic_repair_v1",
        "offline_only": True,
        "source_stage": "stage341_dt005_long_convergence_v1",
        "failed_stage": "stage367_restart_lag1_coherent_smoke_v1",
        "scope": {"source_time_s": 80.0, "failed_window_s": [80.0, 80.2], "dt_s": DT, "slice_count": SLICES},
        "slices": slices,
        "quality": quality,
        "mesh_compression": min_edge_drop,
        "checks": checks,
        "findings": {
            "geometry_or_field_binding_issue": not (checks["source_80_fields_complete"] and checks["failed_first_step_fields_complete"] and checks["same_source_and_failed_geometry_clock"]),
            "mesh_motion_quality_issue_observed": any(item["ratio"] is not None and item["ratio"] < 0.5 for item in min_edge_drop),
            "pressure_solver_failure_is_downstream_signal": any(int(q.get("return_code", 0)) == -8 for q in quality),
            "inverse_distance_is_sole_root_cause": False,
            "restart_timing_fully_proven": False,
            "root_cause_class": "restart_motion_update_causes_local_mesh_quality_collapse_before_GAMG_SIGFPE",
        },
        "algorithm_candidates": [
            {"name": "inverseDistance", "role": "current baseline", "status": "observed_failure_associated"},
            {"name": "quadratic_inverseDistance", "role": "offline candidate only", "status": "not_claimed_supported_until_openfoam10_dictionary_check"},
            {"name": "exponential", "role": "offline candidate only", "status": "not_claimed_supported_until_openfoam10_dictionary_check"},
            {"name": "RBF", "role": "separate implementation candidate", "status": "not_compared_in_this_stage"},
        ],
        "real_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "owned_residual": 0,
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
        "gate_id": "STAGE4F_D_RESTART_CONTINUATION_DIAGNOSTIC_REPAIR_V1_GATE",
        "status": "do_not_pass",
        "next_action": "repair/preflight field and motion-update consistency offline; no new CFD until a fresh smoke candidate passes preflight",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "diagnostic_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "stage4f_d_restart_continuation_diagnostic_repair_v1_gate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": result["status"], "checks": checks, "mesh_compression": min_edge_drop, "real_process_starts": result["real_process_starts"]}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
