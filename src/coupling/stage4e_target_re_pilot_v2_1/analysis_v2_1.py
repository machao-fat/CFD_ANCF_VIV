"""v2.1 output, force, field and continuation audits."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from src.coupling.stage4e_target_re_pilot_v2.analysis_v2 import (
    corrected_coefficients_from_raw,
    corrected_statistics,
    mesh_span_from_bbox,
    numeric_rows,
    parse_force_coefficients,
    parse_raw_forces,
    parse_yplus_file as parse_yplus_summary,
)
from src.coupling.stage4e_target_re_pilot_v2.identity_v2 import D, finite, sha256_file


NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def parse_yplus_file(path: Path, *, summary_path: Path | None = None) -> dict[str, Any]:
    """Audit cylinder-patch yPlus field and cross-check OpenFOAM summary.

    OpenFOAM's yPlus.dat contains only min/max/average.  The independently
    computed p95 therefore comes from the raw ``yPlus`` volScalarField
    written at the evaluation time, restricted to the cylinder patch.
    """
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    match = re.search(r"cylinder\s*\{.*?nonuniform\s+List<scalar>\s+(\d+)\s*\((.*?)\)\s*;", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return {"available": False, "path": str(path), "reason": "cylinder yPlus boundary field not found", "min_y_plus": None, "mean_y_plus": None, "p95_y_plus": None, "max_y_plus": None}
    expected = int(match.group(1))
    values = np.asarray([float(value) for value in re.findall(NUMBER, match.group(2))], dtype=float)
    if len(values) != expected or not np.all(np.isfinite(values)):
        raise ValueError(f"invalid cylinder yPlus field: {path}")
    result: dict[str, Any] = {"available": True, "path": str(path), "sha256": sha256_file(path), "sample_count": int(len(values)), "min_y_plus": float(np.min(values)), "mean_y_plus": float(np.mean(values)), "p95_y_plus": float(np.percentile(values, 95)), "max_y_plus": float(np.max(values)), "summary_path": str(summary_path) if summary_path else None}
    if summary_path and summary_path.exists():
        summary = numeric_rows(summary_path, minimum=4)
        if summary.size and summary.shape[1] >= 4:
            row = summary[-1, :4]
            result["openfoam_summary_min_y_plus"] = float(row[1])
            result["openfoam_summary_max_y_plus"] = float(row[2])
            result["openfoam_summary_mean_y_plus"] = float(row[3])
            result["summary_crosscheck_max_abs_error"] = float(max(abs(result["min_y_plus"] - row[1]), abs(result["max_y_plus"] - row[2]), abs(result["mean_y_plus"] - row[3])))
            result["summary_crosscheck_passed"] = result["summary_crosscheck_max_abs_error"] <= 1.0e-12
    return finite(result)


def coefficient_crosscheck(case_dir: Path, *, U_abs: float, b_mesh: float = D) -> dict[str, Any]:
    raw_paths = sorted(case_dir.rglob("forces.dat"))
    coeff_paths = sorted(case_dir.rglob("forceCoeffs.dat"))
    if not raw_paths or not coeff_paths:
        return {"available": False, "passed": False, "reason": "raw force or forceCoeffs file missing"}
    raw = parse_raw_forces(raw_paths[-1])
    coeff = parse_force_coefficients(coeff_paths[-1])
    corrected = corrected_coefficients_from_raw(raw, U_abs=U_abs, b_mesh=b_mesh)
    n = min(len(corrected.get("Cd", [])), len(coeff.get("cd", [])))
    if n == 0:
        return {"available": False, "passed": False, "reason": "empty force history"}
    cd_error = float(np.max(np.abs(corrected["Cd"][:n] - coeff["cd"][:n])))
    cl_error = float(np.max(np.abs(corrected["Cl"][:n] - coeff["cl"][:n])))
    return finite({"available": True, "raw_path": str(raw_paths[-1]), "forceCoeffs_path": str(coeff_paths[-1]), "raw_sha256": raw["sha256"], "forceCoeffs_sha256": coeff["sha256"], "raw_rows": int(len(corrected["Cd"])), "forceCoeffs_rows": int(len(coeff["cd"])), "max_abs_Cd_error": cd_error, "max_abs_Cl_error": cl_error, "tolerance": 1e-10, "passed": cd_error <= 1e-10 and cl_error <= 1e-10})


def parse_raw_force_history(paths: list[Path]) -> dict[str, Any]:
    """Combine production force files across continuation blocks in memory.

    OpenFOAM starts a new function-object file under the latest restart time.
    Selecting only the lexicographically last file would silently reduce the
    statistics window to the final block, so histories are sorted by physical
    time and duplicate restart rows are removed deterministically.
    """
    arrays = [numeric_rows(path, minimum=7) for path in paths]
    arrays = [array for array in arrays if array.size and array.shape[1] >= 7]
    if not arrays:
        return {"available": False, "paths": [str(path) for path in paths], "rows": 0}
    data = np.concatenate(arrays, axis=0)
    if not np.all(np.isfinite(data)):
        raise ValueError("non-finite production force history")
    order = np.argsort(data[:, 0], kind="mergesort")
    data = data[order]
    keep = np.ones(len(data), dtype=bool)
    if len(data) > 1:
        keep[1:] = np.diff(data[:, 0]) > 1.0e-12
    data = data[keep]
    pressure = data[:, 1:4]
    viscous = data[:, 4:7]
    total = pressure + viscous
    return finite({"available": True, "paths": [str(path) for path in paths], "rows": int(len(data)), "time_s": data[:, 0], "pressure_N": pressure, "viscous_N": viscous, "total_N": total})


def numeric_file_values(path: Path) -> np.ndarray:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if re.search(r"(?:nan|inf|infinity)", text, flags=re.IGNORECASE):
        raise ValueError(f"non-finite field values: {path}")
    values = [float(value) for value in re.findall(NUMBER, text)]
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        raise ValueError(f"non-finite field values: {path}")
    return array


def field_equivalence(case_a: Path, case_b: Path, *, relative_tolerance: float = 1e-10) -> dict[str, Any]:
    def latest(case: Path, name: str) -> Path | None:
        candidates = [p for p in case.iterdir() if p.is_dir() and p.name.replace(".", "", 1).isdigit()]
        candidates.sort(key=lambda p: float(p.name))
        return (candidates[-1] / name) if candidates and (candidates[-1] / name).exists() else None

    result: dict[str, Any] = {"fields": {}, "passed": True}
    for name in ("U", "p"):
        path_a, path_b = latest(case_a, name), latest(case_b, name)
        if path_a is None or path_b is None:
            result["fields"][name] = {"available": False, "passed": False}
            result["passed"] = False
            continue
        va, vb = numeric_file_values(path_a), numeric_file_values(path_b)
        n = min(len(va), len(vb))
        max_abs = float(np.max(np.abs(va[:n] - vb[:n]))) if n else float("inf")
        max_rel = float(np.max(np.abs(va[:n] - vb[:n]) / np.maximum(np.abs(vb[:n]), 1e-30))) if n else float("inf")
        passed = len(va) == len(vb) and max_rel <= relative_tolerance
        result["fields"][name] = {"available": True, "path_a": str(path_a), "path_b": str(path_b), "values_a": int(len(va)), "values_b": int(len(vb)), "max_abs_error": max_abs, "max_relative_error": max_rel, "passed": passed}
        result["passed"] = result["passed"] and passed
    return finite(result)


def force_equivalence(case_a: Path, case_b: Path, *, relative_tolerance: float = 1e-10) -> dict[str, Any]:
    raw_a = sorted(case_a.rglob("forces.dat"))
    raw_b = sorted(case_b.rglob("forces.dat"))
    coeff_a = sorted(case_a.rglob("forceCoeffs.dat"))
    coeff_b = sorted(case_b.rglob("forceCoeffs.dat"))
    if not raw_a or not raw_b or not coeff_a or not coeff_b:
        return {"passed": False, "available": False}
    result: dict[str, Any] = {"available": True, "passed": True}
    for label, paths, minimum in (("raw_forces", (raw_a[-1], raw_b[-1]), 7), ("forceCoeffs", (coeff_a[-1], coeff_b[-1]), 4)):
        a, b = numeric_rows(paths[0], minimum), numeric_rows(paths[1], minimum)
        n = min(len(a), len(b))
        max_rel = float(np.max(np.abs(a[:n] - b[:n]) / np.maximum(np.abs(b[:n]), 1e-30))) if n else float("inf")
        result[label] = {"rows_a": int(len(a)), "rows_b": int(len(b)), "max_relative_error": max_rel, "sha256_a": sha256_file(paths[0]), "sha256_b": sha256_file(paths[1]), "passed": len(a) == len(b) and a.shape[1] == b.shape[1] and max_rel <= relative_tolerance}
        result["passed"] = result["passed"] and result[label]["passed"]
    return finite(result)


def output_metrics(case_dir: Path, log_paths: list[Path], *, before_bytes: int = 0) -> dict[str, Any]:
    numeric_dirs = [p for p in case_dir.iterdir() if p.is_dir() and p.name.replace(".", "", 1).isdigit()]
    numeric_dirs.sort(key=lambda p: float(p.name))
    size = sum(p.stat().st_size for p in case_dir.rglob("*") if p.is_file())
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in log_paths if path.exists())
    matches = re.findall(r"ExecutionTime\s*=\s*(%s)\s*s\s+ClockTime\s*=\s*(%s)\s*s" % (NUMBER, NUMBER), text)
    execution_s = float(matches[-1][0]) if matches else None
    clock_s = float(matches[-1][1]) if matches else None
    return finite({"time_directory_count": len(numeric_dirs), "time_directories": [p.name for p in numeric_dirs], "case_size_bytes": int(size), "disk_increment_bytes": int(size - before_bytes), "execution_time_s": execution_s, "clock_time_s": clock_s, "steps_per_second": None if execution_s is None else float(sum(1 for _ in re.finditer(r"^Time\s*=", text, re.MULTILINE)) / max(execution_s, 1e-30))})


def yplus_history(case_dir: Path, evaluation_records: list[dict[str, Any]]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for item in evaluation_records:
        candidates = [path for path in case_dir.rglob("yPlus") if path.parent.name.replace(".", "", 1).isdigit()]
        target = item.get("time_s")
        if candidates and target is not None:
            selected = min(candidates, key=lambda path: abs(float(path.parent.name) - float(target)))
        else:
            selected = sorted(candidates, key=lambda path: float(path.parent.name))[-1] if candidates else None
        summary = None
        if selected:
            summaries = [path for path in case_dir.rglob("yPlus.dat") if path.parent.name == selected.parent.name]
            summary = summaries[0] if summaries else None
        parsed = parse_yplus_file(selected, summary_path=summary) if selected else {"available": False, "p95_y_plus": None, "max_y_plus": None}
        records.append({"label": item["label"], "time_s": item.get("time_s"), "command": item["command"], "return_code": item["return_code"], "file": str(selected) if selected else None, "audit": parsed})
    return finite({"evaluation_count": len(records), "records": records, "available": bool(records) and all(item["audit"].get("available") for item in records)})


def latest_time(case_dir: Path) -> float | None:
    times = [float(p.name) for p in case_dir.iterdir() if p.is_dir() and p.name.replace(".", "", 1).isdigit()]
    return max(times) if times else None


def checkpoint_hash(case_dir: Path) -> dict[str, Any]:
    time_s = latest_time(case_dir)
    if time_s is None:
        return {"available": False, "time_s": None, "files": []}
    path = case_dir / (f"{time_s:.16g}")
    if not path.exists():
        path = sorted([p for p in case_dir.iterdir() if p.is_dir() and p.name.replace(".", "", 1).isdigit()], key=lambda p: float(p.name))[-1]
    files = [{"path": str(item.relative_to(case_dir)).replace("\\", "/"), "sha256": sha256_file(item), "size_bytes": item.stat().st_size} for item in sorted(path.iterdir()) if item.is_file()]
    return finite({"available": True, "time_s": time_s, "files": files, "checkpoint_sha256": sha256_file(path / "U") if (path / "U").exists() else None})
