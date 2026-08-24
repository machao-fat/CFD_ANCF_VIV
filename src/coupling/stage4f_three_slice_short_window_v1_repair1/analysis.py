"""Restart and dt/2 audits for Stage 4F-C-v1."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from .contract import D_M, Q_INF_PA, START_TIME_S, THRESHOLDS, TOTAL_SPAN_M, U_MPS, WINDOW_S, scaled_relative, trapezoidal_impulse
from .evidence import numeric_file_comparison

FIELDS = ("U", "p", "phi", "Uf", "meshPhi", "polyMesh/points", "uniform/time")


def _load_checkpoint(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _state_error(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, float]:
    scales = {"q": D_M, "qdot": U_MPS, "qddot": U_MPS * U_MPS / D_M}
    return {key: max((scaled_relative(float(a), float(b), scales[key]) for a, b in zip(left[key], right[key])), default=math.inf) if len(left[key]) == len(right[key]) else math.inf for key in scales}


def _case_root(checkpoint_path: Path) -> Path:
    return checkpoint_path.parent.parent / "cases"


def _field_rows(left_path: Path, right_path: Path) -> list[dict[str, Any]]:
    left, right = _load_checkpoint(left_path), _load_checkpoint(right_path)
    left_cases, right_cases = _case_root(left_path), _case_root(right_path)
    rows = []
    for lentry, rentry in zip(sorted(left["slices"], key=lambda row: row["slice_id"]), sorted(right["slices"], key=lambda row: row["slice_id"])):
        if int(lentry["slice_id"]) != int(rentry["slice_id"]):
            raise RuntimeError("restart slice ordering mismatch")
        lfiles = {Path(item["relative_path"]).name if item["relative_path"].endswith("uniform/time") else "/".join(Path(item["relative_path"]).parts[1:]): item for item in lentry["time_files"]}
        rfiles = {Path(item["relative_path"]).name if item["relative_path"].endswith("uniform/time") else "/".join(Path(item["relative_path"]).parts[1:]): item for item in rentry["time_files"]}
        for field in FIELDS:
            key = "time" if field == "uniform/time" else field
            li, ri = lfiles[key], rfiles[key]
            lp = left_cases / str(lentry["case_relative_path"]) / str(li["relative_path"])
            rp = right_cases / str(rentry["case_relative_path"]) / str(ri["relative_path"])
            if str(li["sha256"]) == str(ri["sha256"]) and sha256_file(lp) == sha256_file(rp):
                comparison = {"sha256_equal": True, "numeric_token_count_equal": True, "max_relative_error": 0.0,
                    "left": str(lp), "right": str(rp), "left_sha256": sha256_file(lp), "right_sha256": sha256_file(rp)}
            else:
                comparison = numeric_file_comparison(lp, rp, absolute_scale=1.0)
            rows.append({"slice_id": int(lentry["slice_id"]), "field": field, **comparison,
                "passed": bool(comparison["numeric_token_count_equal"] and comparison["max_relative_error"] is not None and comparison["max_relative_error"] <= THRESHOLDS["restart_field_relative_error_max"])})
    return rows


def restart_audit(branch_a: Mapping[str, Any], branch_b: Mapping[str, Any], output: Path) -> dict[str, Any]:
    a_steps, b_steps = branch_a["steps"], branch_b["steps"]
    rows = []
    if len(a_steps) != 20 or len(b_steps) != 20:
        value = {"status": "blocked", "error": "A/B do not both have 20 steps", "rows": []}
        atomic_write_json(output, value); return value
    for arow, brow in zip(a_steps, b_steps):
        if int(arow["step"]) != int(brow["step"]) or abs(float(arow["time_s"]) - float(brow["time_s"])) > 1e-12:
            raise RuntimeError("A/B time grids differ")
        ap, bp = Path(arow["checkpoint"]), Path(brow["checkpoint"])
        acp, bcp = _load_checkpoint(ap), _load_checkpoint(bp)
        state = _state_error(acp["structure"], bcp["structure"])
        force_error = max((scaled_relative(float(x), float(y), Q_INF_PA * D_M * TOTAL_SPAN_M) for left, right in zip(arow["integrated_slice_forces_N"], brow["integrated_slice_forces_N"]) for x, y in zip(left, right)), default=math.inf)
        fields = _field_rows(ap, bp)
        passed = max(state.values()) <= THRESHOLDS["restart_structure_relative_error_max"] and force_error <= THRESHOLDS["restart_force_relative_error_max"] and all(item["passed"] for item in fields)
        rows.append({"step": int(arow["step"]), "time_s": float(arow["time_s"]), "structure_relative_error": state,
            "force_max_relative_error": force_error, "fields": fields, "passed": passed})
    b_steps_exact = [int(row["step"]) for row in b_steps] == list(range(20))
    b_times_exact = all(abs(float(row["time_s"]) - (START_TIME_S + (index + 1) * .0025)) <= 1e-12 for index, row in enumerate(b_steps))
    passed = all(row["passed"] for row in rows) and b_steps_exact and b_times_exact and int(branch_b["checkpoint_count"]) == 20
    value = {"status": "passed" if passed else "blocked", "rows": rows, "max_structure_relative_error": max((max(row["structure_relative_error"].values()) for row in rows), default=None),
        "max_force_relative_error": max((row["force_max_relative_error"] for row in rows), default=None),
        "max_field_relative_error": max((field["max_relative_error"] for row in rows for field in row["fields"] if field["max_relative_error"] is not None), default=None),
        "b_commit_steps_exact": b_steps_exact, "b_commit_times_exact": b_times_exact, "b_checkpoint_count": branch_b["checkpoint_count"]}
    atomic_write_json(output, value); return value


def _node_vectors(values: Sequence[float]) -> list[tuple[float, float, float]]:
    if len(values) % 6:
        raise ValueError("ANCF vector is not a 6-dof node layout")
    return [(float(values[index]), float(values[index + 1]), float(values[index + 2])) for index in range(0, len(values), 6)]


def _endpoint_norm(left: Sequence[float], right: Sequence[float], scale: float) -> float:
    a, b = _node_vectors(left), _node_vectors(right)
    if len(a) != len(b):
        return math.inf
    return max((math.sqrt(sum((x-y) ** 2 for x, y in zip(ra, rb))) / scale for ra, rb in zip(a, b)), default=math.inf)


def _total_force(row: Mapping[str, Any]) -> list[float]:
    return [sum(float(force[axis]) for force in row["integrated_slice_forces_N"]) for axis in range(3)]


def dt_half_audit(branch_a: Mapping[str, Any], branch_c: Mapping[str, Any], parent_checkpoint: Path, output: Path) -> dict[str, Any]:
    if len(branch_a["steps"]) != 20 or len(branch_c["steps"]) != 40:
        value = {"status": "blocked", "error": "A/C step counts are incomplete"}; atomic_write_json(output, value); return value
    a_final = _load_checkpoint(branch_a["steps"][-1]["checkpoint"])
    c_final = _load_checkpoint(branch_c["steps"][-1]["checkpoint"])
    position = _endpoint_norm(a_final["structure"]["q"], c_final["structure"]["q"], D_M)
    velocity = _endpoint_norm(a_final["structure"]["qdot"], c_final["structure"]["qdot"], U_MPS)
    parent = _load_checkpoint(parent_checkpoint)
    initial_force = [sum(float(row[axis]) for row in parent["previous_slice_forces_N"]) for axis in range(3)]
    a_times = [START_TIME_S] + [float(row["time_s"]) for row in branch_a["steps"]]
    c_times = [START_TIME_S] + [float(row["time_s"]) for row in branch_c["steps"]]
    a_impulse = trapezoidal_impulse(a_times, [initial_force] + [_total_force(row) for row in branch_a["steps"]])
    c_impulse = trapezoidal_impulse(c_times, [initial_force] + [_total_force(row) for row in branch_c["steps"]])
    impulse_scale = Q_INF_PA * D_M * TOTAL_SPAN_M * WINDOW_S
    impulse_difference = [abs(a_impulse[axis] - c_impulse[axis]) / impulse_scale for axis in range(3)]
    at, ct = branch_a["steps"][-1]["tension_N"], branch_c["steps"][-1]["tension_N"]
    tension = {key: scaled_relative(float(at[key]), float(ct[key]), 1.0) for key in ("minimum_N", "maximum_N")}
    passed = (position <= THRESHOLDS["dt_half_endpoint_position_over_D_max"]
        and velocity <= THRESHOLDS["dt_half_endpoint_velocity_over_U_max"]
        and impulse_difference[0] <= THRESHOLDS["dt_half_normalized_impulse_difference_max"]
        and impulse_difference[1] <= THRESHOLDS["dt_half_normalized_impulse_difference_max"]
        and max(tension.values()) <= THRESHOLDS["dt_half_tension_relative_difference_max"])
    value = {"status": "passed" if passed else "blocked", "endpoint_position_difference_over_D": position,
        "endpoint_velocity_difference_over_U": velocity, "A_impulse_Ns": a_impulse, "C_impulse_Ns": c_impulse,
        "impulse_scale_Ns": impulse_scale, "normalized_impulse_difference": {axis: impulse_difference[index] for index, axis in enumerate("xyz")},
        "A_endpoint_tension_N": at, "C_endpoint_tension_N": ct, "tension_relative_difference": tension,
        "thresholds": {key: THRESHOLDS[key] for key in THRESHOLDS if key.startswith("dt_half")}}
    atomic_write_json(output, value); return value
