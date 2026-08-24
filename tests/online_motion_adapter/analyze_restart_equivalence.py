"""Strict per-step audit for uninterrupted versus restarted OpenFOAM runs.

This analyzer never mutates a case.  It merges function-object files from all
start-time directories, reports duplicate restart-boundary samples, and
compares force histories plus U/p/mesh points at the restart and final states.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
FORCE_RE = re.compile(
    rf"^\s*({FLOAT})\s+\(\(({FLOAT})\s+({FLOAT})\s+({FLOAT})\)\s+\(({FLOAT})\s+({FLOAT})\s+({FLOAT})\)\)"
)


def _numeric_directory_key(path: Path) -> float:
    try:
        return float(path.parent.name)
    except ValueError:
        return math.inf


def read_force_segments(case: Path) -> tuple[dict[float, tuple[float, float, float]], list[dict[str, Any]]]:
    files = sorted((case/"postProcessing"/"cylinderForces").glob("*/forces.dat"), key=_numeric_directory_key)
    merged: dict[float, tuple[float, float, float]] = {}
    duplicates: list[dict[str, Any]] = []
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = FORCE_RE.match(line)
            if not match:
                continue
            values = [float(value) for value in match.groups()]
            time_s = values[0]
            force = (values[1]+values[4], values[2]+values[5], values[3]+values[6])
            if time_s in merged:
                old = merged[time_s]
                duplicates.append({
                    "time_s": time_s, "previous": old, "replacement": force,
                    "max_abs_difference_N": max(abs(a-b) for a, b in zip(old, force)),
                    "replacement_file": str(path),
                })
            merged[time_s] = force
    return merged, duplicates


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(value*value for value in values)/len(values)) if values else float("nan")


def compare_force_series(reference_case: Path, restarted_case: Path, *, restart_time_s: float) -> dict[str, Any]:
    reference, _ = read_force_segments(reference_case)
    restarted, duplicates = read_force_segments(restarted_case)
    common = sorted(set(reference) & set(restarted))
    errors = [[restarted[t][i]-reference[t][i] for t in common] for i in range(3)]
    reference_values = [[reference[t][i] for t in common] for i in range(3)]
    post = [t for t in common if t >= restart_time_s-1.0e-12]
    post_errors = [[restarted[t][i]-reference[t][i] for t in post] for i in range(3)]
    def relative(error: list[float], values: list[float]) -> float | None:
        denom = _rms(values)
        return _rms(error)/denom if values and math.isfinite(denom) and denom > 1.0e-30 else None
    return {
        "reference_samples": len(reference), "restarted_samples": len(restarted),
        "common_samples": len(common),
        "missing_reference_times_s": sorted(set(reference)-set(restarted)),
        "unexpected_restarted_times_s": sorted(set(restarted)-set(reference)),
        "restart_boundary_duplicates": duplicates,
        "max_restart_boundary_duplicate_difference_N": max((item["max_abs_difference_N"] for item in duplicates), default=0.0),
        "time_sequence_exact": sorted(reference) == sorted(restarted),
        "force_rmse_N": {axis: _rms(errors[i]) for i, axis in enumerate(("x", "y", "z"))},
        "force_relative_rmse": {axis: relative(errors[i], reference_values[i]) for i, axis in enumerate(("x", "y", "z"))},
        "post_restart_samples": len(post),
        "post_restart_force_rmse_N": {axis: _rms(post_errors[i]) for i, axis in enumerate(("x", "y", "z"))},
    }


def numeric_tokens(path: Path) -> list[float]:
    if not path.is_file():
        return []
    return [float(value) for value in re.findall(FLOAT, path.read_text(encoding="utf-8", errors="replace"))]


def _time_directory(case: Path, time_s: float) -> Path | None:
    candidates = []
    for path in case.iterdir():
        if not path.is_dir():
            continue
        try:
            value = float(path.name)
        except ValueError:
            continue
        candidates.append((abs(value-time_s), path))
    if not candidates:
        return None
    difference, path = min(candidates, key=lambda item: item[0])
    return path if difference <= 1.0e-10*max(1.0, abs(time_s)) else None


def compare_state(reference_case: Path, restarted_case: Path, time_s: float) -> dict[str, Any]:
    ref_time = _time_directory(reference_case, time_s)
    rst_time = _time_directory(restarted_case, time_s)
    result: dict[str, Any] = {"time_s": time_s, "reference_time_directory": str(ref_time) if ref_time else None, "restarted_time_directory": str(rst_time) if rst_time else None}
    for name, relative in (("U", Path("U")), ("p", Path("p")), ("mesh_points", Path("polyMesh/points"))):
        ref = numeric_tokens(ref_time/relative) if ref_time else []
        rst = numeric_tokens(rst_time/relative) if rst_time else []
        result[name] = {
            "reference_tokens": len(ref), "restarted_tokens": len(rst),
            "token_count_equal": len(ref) == len(rst) and bool(ref),
            "max_numeric_difference": max((abs(a-b) for a, b in zip(ref, rst)), default=None) if len(ref) == len(rst) and ref else None,
        }
    return result


def _series_passed(record: dict[str, Any], tolerance: float) -> bool:
    rel_y = record["force_relative_rmse"]["y"]
    return bool(record["time_sequence_exact"] and rel_y is not None and rel_y <= tolerance and record["max_restart_boundary_duplicate_difference_N"] <= max(1.0e-10, tolerance))


def _state_passed(record: dict[str, Any], tolerance: float) -> bool:
    return all(
        record[name]["token_count_equal"]
        and record[name]["max_numeric_difference"] is not None
        and record[name]["max_numeric_difference"] <= tolerance
        for name in ("U", "p", "mesh_points")
    )


def analyze(
    *, reference_native: Path, restarted_native: Path,
    reference_file: Path, restarted_file: Path,
    restart_time_s: float, end_time_s: float,
    force_relative_tolerance: float = 1.0e-8,
    field_absolute_tolerance: float = 1.0e-8,
) -> dict[str, Any]:
    native_forces = compare_force_series(reference_native, restarted_native, restart_time_s=restart_time_s)
    file_forces = compare_force_series(reference_file, restarted_file, restart_time_s=restart_time_s)
    cross_forces = compare_force_series(restarted_native, restarted_file, restart_time_s=restart_time_s)
    states = {
        "native_restart_boundary": compare_state(reference_native, restarted_native, restart_time_s),
        "file_restart_boundary": compare_state(reference_file, restarted_file, restart_time_s),
        "native_final": compare_state(reference_native, restarted_native, end_time_s),
        "file_final": compare_state(reference_file, restarted_file, end_time_s),
        "restarted_native_vs_file_final": compare_state(restarted_native, restarted_file, end_time_s),
    }
    enough_data = all(record["common_samples"] > 0 for record in (native_forces, file_forces, cross_forces))
    passed = enough_data and all(_series_passed(record, force_relative_tolerance) for record in (native_forces, file_forces, cross_forces)) and all(_state_passed(record, field_absolute_tolerance) for record in states.values())
    return {
        "status": "passed" if passed else ("failed" if enough_data else "not_run_or_incomplete"),
        "restart_attempted": bool(enough_data),
        "restart_checked": bool(passed),
        "restart_time_s": restart_time_s, "end_time_s": end_time_s,
        "tolerances": {"force_relative_rmse": force_relative_tolerance, "field_absolute": field_absolute_tolerance},
        "native_uninterrupted_vs_restart": native_forces,
        "file_uninterrupted_vs_restart": file_forces,
        "restarted_native_vs_file": cross_forces,
        "state_comparisons": states,
        "interpretation": "restart_checked is true only after strict per-step time/force equivalence and U/p/mesh-point equivalence at restart and final states; a completed publisher alone is not restart equivalence.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-native", type=Path, required=True)
    parser.add_argument("--restarted-native", type=Path, required=True)
    parser.add_argument("--reference-file", type=Path, required=True)
    parser.add_argument("--restarted-file", type=Path, required=True)
    parser.add_argument("--restart-time", type=float, required=True)
    parser.add_argument("--end-time", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = analyze(
        reference_native=args.reference_native, restarted_native=args.restarted_native,
        reference_file=args.reference_file, restarted_file=args.restarted_file,
        restart_time_s=args.restart_time, end_time_s=args.end_time,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
