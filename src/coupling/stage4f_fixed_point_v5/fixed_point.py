"""Materialize one fixed-point ANCF equilibrium from a real held-CFD force.

This module deliberately has no coupling scheduler.  It establishes the
initial-state consistency required before the frozen three-step preflight can
be allowed to start.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import scipy.io as sio

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from ..multi_slice_driver.real_process import parse_force_exact
from ..stage4f_equilibrated_startup_v3.equilibrium import HELPER_ROOT, MATLAB, SLICE_LENGTH_M

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HELD_AUDIT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_held_geometry_v4" / "hold_20260817_attempt2" / "held_geometry_audit.json"
RESULTS_ROOT = PROJECT_ROOT / "results" / "12_stage4f_fixed_point_v5"
MAX_STATIC_GREEN_STRAIN = 0.01
HELD_WINDOW_START_S = 1.25
HELD_WINDOW_END_S = 1.5
HELD_SAMPLE_DT_S = 0.0025


def integrated_slice_loads(unit_span_force_N: list[float], slice_length_m: float = SLICE_LENGTH_M) -> list[list[float]]:
    """Apply the frozen slice length exactly once to a finite unit-span force."""
    if len(unit_span_force_N) != 3 or not math.isfinite(slice_length_m) or slice_length_m <= 0:
        raise ValueError("invalid unit-span force or slice length")
    if not all(math.isfinite(float(value)) for value in unit_span_force_N):
        raise ValueError("force is non-finite")
    return [[float(value) * slice_length_m for value in unit_span_force_N] for _ in range(3)]


def _matrix(rows: list[list[float]]) -> str:
    return "[" + ";".join(" ".join(format(value, ".17g") for value in row) for row in rows) + "]"


def held_tail_mean_force(held_audit_path: Path = HELD_AUDIT) -> dict[str, Any]:
    """Return a reproducible zero-motion tail-window force statistic.

    An endpoint may retain solver noise, so this fixed first-stage window is
    the only CFD load admitted to a static fixed-point solve.
    """
    held = json.loads(held_audit_path.read_text(encoding="utf-8"))
    force_path = Path(held["log"]).parent / "postProcessing" / "cylinderForces" / f"{held['start_time_s']:.12g}" / "forces.dat"
    return force_window_statistics(force_path, start_s=HELD_WINDOW_START_S, end_s=HELD_WINDOW_END_S)


def force_window_statistics(force_path: Path, *, start_s: float, end_s: float) -> dict[str, Any]:
    """Parse an inclusive fixed time window of finite raw-force rows."""
    count = round((end_s - start_s) / HELD_SAMPLE_DT_S) + 1
    samples = []
    for index in range(count):
        time_s = start_s + index * HELD_SAMPLE_DT_S
        row = parse_force_exact(force_path, target_time_s=time_s, time_tolerance=1e-10)
        if row is None:
            raise RuntimeError(f"missing exact held-force sample at {time_s:.12g} s")
        samples.append([float(value) for value in row.force_N])
    means = [sum(row[column] for row in samples) / len(samples) for column in range(3)]
    std = [(sum((row[column] - means[column]) ** 2 for row in samples) / len(samples)) ** .5 for column in range(3)]
    half = len(samples) // 2
    first = [sum(row[column] for row in samples[:half]) / half for column in range(3)]
    second = [sum(row[column] for row in samples[half:]) / (len(samples) - half) for column in range(3)]
    drift = [abs(second[column] - first[column]) / max(1.0, abs(means[column])) for column in range(3)]
    return {"force_path": str(force_path), "force_sha256": sha256_file(force_path), "window_start_s": start_s,
            "window_end_s": end_s, "sample_dt_s": HELD_SAMPLE_DT_S, "sample_count": len(samples),
            "mean_unit_span_force_N": means, "std_unit_span_force_N": std, "first_half_mean_unit_span_force_N": first,
            "second_half_mean_unit_span_force_N": second, "relative_half_window_drift": drift}


def _run_static(output_dir: Path, unit_forces: list[list[float]], source: dict[str, Any]) -> dict[str, Any]:
    """Run one real MATLAB static solve for three audited unit-span loads."""
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if not MATLAB.is_file():
        raise FileNotFoundError(MATLAB)
    if len(unit_forces) != 3:
        raise ValueError("exactly three slice forces are required")
    loads = [integrated_slice_loads([float(value) for value in force])[0] for force in unit_forces]
    output_dir.mkdir(parents=True)
    state_path = output_dir / "fixed_point_state.mat"
    log_path = output_dir / "matlab_static_fixed_point.log"
    helper = str(HELPER_ROOT.resolve()).replace("\\", "/").replace("'", "''")
    target = str(state_path.resolve()).replace("\\", "/").replace("'", "''")
    script = f"addpath('{helper}'); stage4f_b3_equilibrate('{target}',{_matrix(loads)});"
    with log_path.open("w", encoding="utf-8") as stream:
        completed = subprocess.run([str(MATLAB), "-batch", script], cwd=str(output_dir), stdout=stream, stderr=subprocess.STDOUT, timeout=240, check=False)
    if completed.returncode != 0 or not state_path.is_file():
        raise RuntimeError(f"fixed-point static solve failed ({completed.returncode})")
    report = sio.loadmat(state_path, squeeze_me=True, struct_as_record=False).get("report")
    if report is None:
        raise RuntimeError("fixed-point state has no MATLAB report")
    static = report.static
    motion = report.slice_motion
    record: dict[str, Any] = {
        "status": "passed" if bool(static.passes) and float(static.maximum_green_strain) <= MAX_STATIC_GREEN_STRAIN else "blocked",
        **source,
        "unit_span_force_N": unit_forces,
        "slice_length_m": SLICE_LENGTH_M,
        "integrated_slice_force_N": loads,
        "unit_span_to_integrated_length_applications": 1,
        "static": {
            "converged": bool(static.converged), "residual_N": float(static.residual_N),
            "maximum_green_strain": float(static.maximum_green_strain), "minimum_tension_N": float(static.minimum_tension_N),
            "negative_tension_fraction": float(static.negative_tension_fraction), "passes": bool(static.passes),
        },
        "slice_motion": {key: [float(value) for value in getattr(motion, key).reshape(-1)] for key in ("x_m", "y_m", "z_m", "vx_mps", "vy_mps", "vz_mps", "ax_mps2", "ay_mps2", "az_mps2")},
        "state_mat": str(state_path), "state_mat_sha256": sha256_file(state_path), "matlab_log": str(log_path),
        "formal_fsi_started": False,
    }
    record["max_xy_displacement_m"] = max(math.hypot(x, y) for x, y in zip(record["slice_motion"]["x_m"], record["slice_motion"]["y_m"]))
    record["fixed_point_static_sha256"] = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    atomic_write_json(output_dir / "fixed_point_static_audit.json", record)
    return record


def run_static_fixed_point(output_dir: Path, held_audit_path: Path = HELD_AUDIT) -> dict[str, Any]:
    """Run the first static solve from the frozen zero-motion tail window."""
    held = json.loads(held_audit_path.read_text(encoding="utf-8"))
    if held.get("status") != "passed" or held.get("motion") != "held_at_equilibrium_zero_increment":
        raise ValueError("held-CFD source is not an accepted zero-increment state")
    tail = held_tail_mean_force(held_audit_path)
    force = [float(value) for value in tail["mean_unit_span_force_N"]]
    return _run_static(output_dir, [force, force, force], {"source_held_geometry_audit": str(held_audit_path),
        "source_held_geometry_sha256": sha256_file(held_audit_path), "held_force_tail_window": tail})


def run_static_from_exact_hold(output_dir: Path, exact_hold_audit: Path) -> dict[str, Any]:
    """Use each exact-geometry held-CFD tail mean as its own slice load."""
    audit = json.loads(exact_hold_audit.read_text(encoding="utf-8"))
    if audit.get("status") != "passed" or audit.get("exact_alpha") != 1.0 or len(audit.get("slices", [])) != 3:
        raise ValueError("exact three-slice hold audit is not accepted")
    rows = [[float(value) for value in item["held_force"]["mean_unit_span_force_N"]] for item in sorted(audit["slices"], key=lambda item: item["slice_id"])]
    return _run_static(output_dir, rows, {"source_exact_geometry_hold_audit": str(exact_hold_audit),
        "source_exact_geometry_hold_sha256": sha256_file(exact_hold_audit), "exact_alpha": 1.0,
        "per_slice_held_force_windows": [item["held_force"] for item in sorted(audit["slices"], key=lambda item: item["slice_id"])]})
