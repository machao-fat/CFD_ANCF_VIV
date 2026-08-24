"""Offline force, statistics, continuation and convergence audits for v2.2."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from src.coupling.stage4e_target_re_pilot_v2.analysis_v2 import (
    corrected_coefficients_from_raw,
    corrected_statistics,
    numeric_rows,
    parse_force_coefficients,
    parse_raw_forces,
)
from .identity_v2_2 import D, HARD_CFL, PRODUCTION_CFL_TARGET, finite, sha256_file, sha256_tree

NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def numeric_time_directories(case_dir: Path) -> list[Path]:
    items = [p for p in case_dir.iterdir() if p.is_dir() and p.name.replace(".", "", 1).isdigit()]
    return sorted(items, key=lambda p: float(p.name))


def latest_time(case_dir: Path) -> float | None:
    dirs = numeric_time_directories(case_dir)
    return float(dirs[-1].name) if dirs else None


def parse_cfl(log_path: Path) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    rows = [(float(a), float(b)) for a, b in re.findall(r"Courant Number mean:\s*(%s)\s*max:\s*(%s)" % (NUMBER, NUMBER), text, flags=re.IGNORECASE)]
    bad = bool(re.search(r"\b(?:nan|inf|infinity)\b", text, flags=re.IGNORECASE))
    return finite({
        "samples": len(rows),
        "mean_cfl_max": max((row[0] for row in rows), default=None),
        "max_cfl": max((row[1] for row in rows), default=None),
        "hard_stop_threshold": HARD_CFL,
        "formal_target": PRODUCTION_CFL_TARGET,
        "nonfinite_token": bad,
        "passed": bool(rows) and not bad and max(row[1] for row in rows) < HARD_CFL,
    })


def log_health(paths: Iterable[Path]) -> dict[str, Any]:
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths if path.exists())
    upper = text.upper()
    bad = []
    if "FOAM FATAL" in upper or "FATAL ERROR" in upper:
        bad.append("FATAL")
    if re.search(r"\b(?:NAN|INF|INFINITY)\b", upper):
        bad.append("NAN_OR_INF")
    # OpenFOAM normally prints ``sigFpe : Enabling floating point exception
    # trapping`` at startup.  That is configuration, not a solver failure.
    # Only classify an actual signal/abort/error as a fatal token.
    if re.search(r"(?:SIGFPE|FLOATING POINT EXCEPTION).*(?:RECEIVED|CAUGHT|ABORT|ERROR|SIGNAL)", upper):
        bad.append("SIGFPE")
    return {"contains_End": "End" in text, "fatal_tokens": sorted(set(bad)), "finite_log_text": not bad}


def _force_paths(case_dir: Path) -> list[Path]:
    paths = [p for p in case_dir.rglob("forces.dat") if p.parent.name.replace(".", "", 1).isdigit()]
    return sorted(paths, key=lambda p: float(p.parent.name))


def _match_rows(a: np.ndarray, b: np.ndarray, time_tolerance: float) -> tuple[np.ndarray, np.ndarray]:
    left: list[int] = []
    right: list[int] = []
    for i, value in enumerate(a[:, 0]):
        indices = np.where(np.abs(b[:, 0] - value) <= time_tolerance)[0]
        if len(indices):
            j = int(indices[np.argmin(np.abs(b[indices, 0] - value))])
            left.append(i)
            right.append(j)
    return np.asarray(left, dtype=int), np.asarray(right, dtype=int)


def overlap_force_audit(paths: list[Path], *, time_tolerance: float = 1.0e-10, force_absolute_tolerance: float = 1.0e-10, l2_tolerance: float = 1.0e-10, component_floor_N: float = 1.0e-10) -> dict[str, Any]:
    def sort_key(path: Path) -> tuple[int, float | str]:
        try:
            return (0, float(path.parent.name))
        except ValueError:
            return (1, str(path))
    ordered = sorted(paths, key=sort_key)
    records: list[dict[str, Any]] = []
    for first, second in zip(ordered, ordered[1:]):
        a = numeric_rows(first, minimum=7)
        b = numeric_rows(second, minimum=7)
        if not a.size or not b.size:
            records.append({"first": str(first), "second": str(second), "passed": False, "reason": "empty force history"})
            continue
        ia, ib = _match_rows(a, b, time_tolerance)
        if not len(ia):
            records.append({"first": str(first), "second": str(second), "overlap_sample_count": 0, "passed": True, "reason": "no common physical-time rows"})
            continue
        diff = a[ia] - b[ib]
        force_diff = diff[:, 1:7]
        ref = a[ia, 1:7]
        l2 = float(np.linalg.norm(force_diff) / max(np.linalg.norm(ref), 1.0e-30))
        component_rel = float(np.max(np.abs(force_diff) / np.maximum(np.abs(ref), component_floor_N)))
        item = {
            "first": str(first),
            "second": str(second),
            "overlap_start_s": float(max(a[ia[0], 0], b[ib[0], 0])),
            "overlap_end_s": float(min(a[ia[-1], 0], b[ib[-1], 0])),
            "overlap_sample_count": int(len(ia)),
            "maximum_time_error_s": float(np.max(np.abs(diff[:, 0]))),
            "maximum_absolute_force_error_N": float(np.max(np.abs(force_diff))),
            "normalized_l2_relative_error": l2,
            "maximum_component_relative_error": component_rel,
            "component_absolute_floor_N": component_floor_N,
            "passed": bool(np.max(np.abs(diff[:, 0])) <= time_tolerance and np.max(np.abs(force_diff)) <= force_absolute_tolerance and l2 <= l2_tolerance),
        }
        records.append(finite(item))
    return finite({"schema_version": "stage4e-b2-a-v2.2-overlap-force-audit-0.1.0", "thresholds": {"time_s": time_tolerance, "absolute_force_N": force_absolute_tolerance, "normalized_l2": l2_tolerance}, "records": records, "passed": bool(records) and all(item.get("passed", False) for item in records)})


def merge_force_history(paths: list[Path], *, time_tolerance: float = 1.0e-12, force_absolute_tolerance: float = 1.0e-10) -> dict[str, Any]:
    arrays = [numeric_rows(path, minimum=7) for path in paths]
    arrays = [array for array in arrays if array.size and array.shape[1] >= 7]
    if not arrays:
        return {"available": False, "rows": 0, "removed_duplicate_rows": 0, "duplicate_groups": []}
    data = np.concatenate(arrays, axis=0)
    if not np.all(np.isfinite(data)):
        raise ValueError("non-finite force history")
    data = data[np.argsort(data[:, 0], kind="mergesort")]
    kept: list[np.ndarray] = []
    duplicate_groups: list[dict[str, Any]] = []
    removed = 0
    index = 0
    while index < len(data):
        end = index + 1
        while end < len(data) and abs(data[end, 0] - data[index, 0]) <= time_tolerance:
            end += 1
        group = data[index:end]
        if len(group) > 1:
            force_diff = group[1:, 1:7] - group[0:1, 1:7]
            max_diff = float(np.max(np.abs(force_diff)))
            if max_diff > force_absolute_tolerance:
                raise ValueError(f"inconsistent duplicate force time at {group[0,0]}")
            duplicate_groups.append({"time_s": float(group[0, 0]), "rows": int(len(group)), "maximum_absolute_force_difference_N": max_diff, "retained": "first"})
            removed += len(group) - 1
        kept.append(group[0])
        index = end
    merged = np.asarray(kept, dtype=float)
    total = merged[:, 1:4] + merged[:, 4:7]
    return finite({"available": True, "rows": int(len(merged)), "removed_duplicate_rows": int(removed), "duplicate_groups": duplicate_groups, "time_s": merged[:, 0], "pressure_N": merged[:, 1:4], "viscous_N": merged[:, 4:7], "total_N": total, "paths": [str(path) for path in paths]})


def coefficient_crosscheck_all(case_dir: Path, *, U_abs: float, b_mesh: float = D) -> dict[str, Any]:
    raw_paths = _force_paths(case_dir)
    coeff_paths = [p for p in case_dir.rglob("forceCoeffs.dat") if p.parent.name.replace(".", "", 1).isdigit()]
    coeff_by_time = {p.parent.name: p for p in coeff_paths}
    records: list[dict[str, Any]] = []
    for raw_path in raw_paths:
        coeff_path = coeff_by_time.get(raw_path.parent.name)
        if coeff_path is None:
            records.append({"raw_path": str(raw_path), "passed": False, "reason": "matching forceCoeffs missing"})
            continue
        raw = parse_raw_forces(raw_path)
        coeff = parse_force_coefficients(coeff_path)
        corrected = corrected_coefficients_from_raw(raw, U_abs=U_abs, b_mesh=b_mesh)
        n = min(len(corrected.get("Cd", [])), len(coeff.get("cd", [])))
        cd = float(np.max(np.abs(corrected["Cd"][:n] - coeff["cd"][:n]))) if n else math.inf
        cl = float(np.max(np.abs(corrected["Cl"][:n] - coeff["cl"][:n]))) if n else math.inf
        records.append({"raw_path": str(raw_path), "forceCoeffs_path": str(coeff_path), "raw_sha256": sha256_file(raw_path), "forceCoeffs_sha256": sha256_file(coeff_path), "raw_rows": int(len(corrected.get("Cd", []))), "forceCoeffs_rows": int(len(coeff.get("cd", []))), "max_absolute_Cd_error": cd, "max_absolute_Cl_error": cl, "passed": bool(len(corrected.get("Cd", [])) == len(coeff.get("cd", [])) and cd <= 1.0e-10 and cl <= 1.0e-10)})
    return finite({"records": records, "tolerance": 1.0e-10, "passed": bool(records) and all(item.get("passed", False) for item in records)})


def statistics_gate(merged: dict[str, Any], *, U_abs: float, runtime_valid: bool, force_crosscheck_passed: bool, production_max_cfl: float | None) -> dict[str, Any]:
    if not merged.get("available"):
        return {"statistics_available": False, "statistics_valid": False, "reason": "force history unavailable"}
    corrected = corrected_coefficients_from_raw(merged, U_abs=U_abs, b_mesh=D)
    stats = corrected_statistics(corrected, U_abs=U_abs)
    windows = stats.get("three_consecutive_windows", [])
    stability: dict[str, Any] = {"available": len(windows) == 3, "changes": {}, "passed": False}
    if len(windows) == 3:
        keys = ("mean_Cd", "Cd_fluctuation_RMS", "Cl_fluctuation_RMS", "Cl_peak_to_peak")
        limits = {"mean_Cd": 0.02, "Cd_fluctuation_RMS": 0.05, "Cl_fluctuation_RMS": 0.05, "Cl_peak_to_peak": 0.05}
        for key in keys:
            values = [float(row[key]) for row in windows]
            base = max(abs(values[0]), 1.0e-12)
            changes = [abs(value - values[0]) / base for value in values[1:]]
            stability["changes"][key] = changes
        stability["passed"] = all(max(stability["changes"][key]) <= limit for key, limit in limits.items())
    checks = {
        "runtime_valid": bool(runtime_valid),
        "force_crosscheck_passed": bool(force_crosscheck_passed),
        "production_max_cfl_below_0_5": production_max_cfl is not None and float(production_max_cfl) < PRODUCTION_CFL_TARGET,
        "hard_stop_not_crossed": production_max_cfl is not None and float(production_max_cfl) < HARD_CFL,
        "frequency_status_evaluable_pass": stats.get("frequency_status") == "evaluable_pass",
        "effective_cycles_at_least_15": float(stats.get("effective_cycles", 0.0)) >= 15.0,
        "frequency_consistency_at_most_5_percent": stats.get("frequency_consistency_relative") is not None and float(stats["frequency_consistency_relative"]) <= 0.05,
        "finite_frequency_values": all(stats.get(key) is not None and math.isfinite(float(stats[key])) for key in ("dominant_frequency_Hz", "zero_crossing_frequency_Hz", "autocorrelation_frequency_Hz", "St")),
        "three_windows": len(windows) == 3,
        "three_window_stability": stability["passed"],
    }
    return finite({"statistics": stats, "stability": stability, "checks": checks, "statistics_valid": all(checks.values())})


def parse_checkmesh(log_path: Path) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    def number(label: str) -> float | None:
        match = re.search(label + r"\s*:\s*(%s)" % NUMBER, text)
        return None if not match else float(match.group(1))
    cells = re.search(r"^\s*cells:\s*(\d+)", text, flags=re.MULTILINE)
    points = re.search(r"^\s*points:\s*(\d+)", text, flags=re.MULTILINE)
    faces = re.search(r"^\s*faces:\s*(\d+)", text, flags=re.MULTILINE)
    non_orth = re.search(r"Mesh non-orthogonality Max:\s*(%s)\s+average:\s*(%s)" % (NUMBER, NUMBER), text, flags=re.IGNORECASE)
    skew = re.search(r"Max skewness\s*=\s*(%s)" % NUMBER, text, flags=re.IGNORECASE)
    min_volume = re.search(r"minimum volume:\s*(%s)" % NUMBER, text, flags=re.IGNORECASE)
    return finite({"log_path": str(log_path), "mesh_ok": "Mesh OK." in text, "cells": None if not cells else int(cells.group(1)), "points": None if not points else int(points.group(1)), "faces": None if not faces else int(faces.group(1)), "minimum_volume": None if not min_volume else float(min_volume.group(1)), "maximum_non_orthogonality": None if not non_orth else float(non_orth.group(1)), "average_non_orthogonality": None if not non_orth else float(non_orth.group(2)), "maximum_skewness": None if not skew else float(skew.group(1))})


def checkpoint_alignment(case_dir: Path, force_paths: list[Path], *, dt: float) -> dict[str, Any]:
    latest = latest_time(case_dir)
    force_times = []
    for path in force_paths:
        rows = numeric_rows(path, minimum=7)
        if rows.size:
            force_times.append(float(rows[-1, 0]))
    final_force = max(force_times) if force_times else None
    error = None if latest is None or final_force is None else abs(latest - final_force)
    return finite({"latest_field_time_s": latest, "final_force_time_s": final_force, "absolute_time_error_s": error, "threshold_dt_over_2_s": dt / 2.0, "passed": error is not None and error <= dt / 2.0})


def compare_statistics(a: dict[str, Any], b: dict[str, Any], *, limits: dict[str, float]) -> dict[str, Any]:
    values: dict[str, float | None] = {}
    passed = True
    for key, limit in limits.items():
        av, bv = a.get(key), b.get(key)
        if av is None or bv is None:
            values[key] = None
            passed = False
            continue
        denominator = max(abs(float(av)), 1.0e-12)
        values[key] = abs(float(bv) - float(av)) / denominator
        passed = passed and values[key] <= limit
    return finite({"relative_changes": values, "limits": limits, "passed": passed})


def gci_pair(coarse: float, fine: float, ratio: float, order: float = 2.0) -> dict[str, Any]:
    if not all(math.isfinite(v) for v in (coarse, fine, ratio, order)) or ratio <= 1.0 or coarse == fine:
        return {"available": False, "monotonic": False}
    extrapolated = fine + (fine - coarse) / (ratio**order - 1.0)
    gci = 1.25 * abs((fine - coarse) / max(abs(fine), 1.0e-30)) / (ratio**order - 1.0)
    return finite({"available": True, "monotonic_pair_only": True, "richardson_extrapolated": extrapolated, "gci_fine_fraction": gci})
