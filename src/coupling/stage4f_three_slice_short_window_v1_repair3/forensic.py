"""Pure, offline audits used before any repair3 real execution."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from ..stage4f_three_slice_short_window_v1_repair2.contract import (
    D_M,
    Q_INF_PA,
    THRESHOLDS,
    TOTAL_SPAN_M,
    U_MPS,
    scaled_relative,
)

AXES = "xyz"
EXPECTED_SLICE_IDS = (0, 1, 2)
STATE_ROLES = {"predictor", "committed"}


def _finite(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def audit_force_row(load: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild raw -> unit-span -> integrated force and Cd independently."""
    unit_span = _finite(load["unit_span_m"], "unit_span_m")
    slice_length = _finite(load["slice_length_m"], "slice_length_m")
    extrusion = _finite(load.get("extrusion_thickness_m", unit_span), "extrusion_thickness_m")
    if unit_span <= 0 or slice_length <= 0 or extrusion <= 0:
        raise ValueError("force dimensions must be positive")
    raw = [_finite(load[f"openfoam_force_{axis}_N"], f"raw_{axis}") for axis in AXES]
    unit = [_finite(load[f"force_2d_{axis}_Npm"], f"unit_{axis}") for axis in AXES]
    integrated = [_finite(load[f"force_{axis}_N"], f"integrated_{axis}") for axis in AXES]
    conversion = []
    for index, axis in enumerate(AXES):
        expected_unit = raw[index] / extrusion
        expected_integrated = expected_unit * slice_length
        conversion.extend((
            {"axis": axis, "conversion": "raw_to_unit_span", "expected": expected_unit,
             "actual": unit[index], "relative_error": scaled_relative(unit[index], expected_unit, Q_INF_PA * D_M)},
            {"axis": axis, "conversion": "unit_span_to_integrated_slice", "expected": expected_integrated,
             "actual": integrated[index], "relative_error": scaled_relative(integrated[index], expected_integrated, Q_INF_PA * D_M * TOTAL_SPAN_M)},
        ))
    cd_from_raw = raw[0] / (Q_INF_PA * D_M * extrusion)
    cd_from_unit = unit[0] / (Q_INF_PA * D_M)
    cd_crosscheck_error = scaled_relative(cd_from_raw, cd_from_unit, 1.0)
    reported_cd = load.get("force_coeff_Cd", load.get("Cd"))
    reported_cd = None if reported_cd is None else _finite(reported_cd, "force_coeff_Cd")
    reported_cd_error = 0.0 if reported_cd is None else scaled_relative(cd_from_raw, reported_cd, 1.0)
    max_conversion_error = max(row["relative_error"] for row in conversion)
    passed = (max_conversion_error <= THRESHOLDS["force_conversion_relative_error_max"]
              and cd_crosscheck_error <= THRESHOLDS["force_conversion_relative_error_max"]
              and reported_cd_error <= THRESHOLDS["force_conversion_relative_error_max"]
              and abs(cd_from_raw) <= THRESHOLDS["abs_cd_max"])
    return {"slice_id": int(load["slice_id"]), "step": int(load["step"]), "time_s": _finite(load["time_s"], "time_s"),
            "raw_force_N": raw, "unit_span_force_Npm": unit, "integrated_slice_force_N": integrated,
            "unit_span_m": unit_span, "extrusion_thickness_m": extrusion, "slice_length_m": slice_length,
            "Cd_from_raw": cd_from_raw, "Cd_from_unit_span": cd_from_unit,
            "force_coeff_Cd": reported_cd, "Cd_crosscheck_relative_error": cd_crosscheck_error,
            "reported_Cd_relative_error": reported_cd_error, "conversion": conversion,
            "max_conversion_relative_error": max_conversion_error, "passed": passed}


def audit_force_step(loads: Sequence[Mapping[str, Any]], *, expected_step: int, expected_time_s: float) -> dict[str, Any]:
    """Reject missing, duplicate, stale, or time-shifted slice observations."""
    identities = [(int(row["slice_id"]), int(row["step"]), _finite(row["time_s"], "time_s")) for row in loads]
    ids = [item[0] for item in identities]
    duplicate_ids = sorted({sid for sid in ids if ids.count(sid) > 1})
    missing_ids = sorted(set(EXPECTED_SLICE_IDS) - set(ids))
    unexpected_ids = sorted(set(ids) - set(EXPECTED_SLICE_IDS))
    identity_ok = (not duplicate_ids and not missing_ids and not unexpected_ids and
                   all(step == expected_step and abs(time_s - expected_time_s) <= 1e-12 for _, step, time_s in identities))
    rows = [audit_force_row(row) for row in loads]
    aggregate = [sum(row["integrated_slice_force_N"][axis] for row in rows) for axis in range(3)]
    # This sum is already an integrated total. No further span factor is permitted.
    passed = identity_ok and len(rows) == len(EXPECTED_SLICE_IDS) and all(row["passed"] for row in rows)
    return {"expected_step": expected_step, "expected_time_s": expected_time_s, "duplicate_slice_ids": duplicate_ids,
            "missing_slice_ids": missing_ids, "unexpected_slice_ids": unexpected_ids, "identity_passed": identity_ok,
            "slice_audits": rows, "aggregate_integrated_force_N": aggregate,
            "aggregate_definition": "sum(integrated_slice_force_N); no additional span multiplication", "passed": passed}


def node_vectors(values: Sequence[Any]) -> list[tuple[float, float, float]]:
    if len(values) == 0 or len(values) % 6:
        raise ValueError("ANCF state must use a non-empty 6-dof node layout")
    finite = [_finite(value, "state component") for value in values]
    return [(finite[index], finite[index + 1], finite[index + 2]) for index in range(0, len(finite), 6)]


def audit_motion_state(motion: Mapping[str, Any], state: Mapping[str, Any], *, expected_step: int,
                       expected_time_s: float, expected_role: str) -> dict[str, Any]:
    """Compare like-for-like motion/state identities and the ANCF node layout."""
    role = str(state.get("role", ""))
    if expected_role not in STATE_ROLES:
        raise ValueError("unknown expected state role")
    identity_ok = (int(motion["step"]) == expected_step == int(state["step"])
                   and abs(_finite(motion["time_s"], "motion time") - expected_time_s) <= 1e-12
                   and abs(_finite(state["time_s"], "state time") - expected_time_s) <= 1e-12
                   and role == expected_role)
    node_index = int(motion["node_index"])
    positions, velocities = node_vectors(state["q"]), node_vectors(state["qdot"])
    if node_index < 0 or node_index >= len(positions) or len(positions) != len(velocities):
        raise ValueError("node index/layout mismatch")
    position_error = math.dist(tuple(map(float, motion["position_m"])), positions[node_index]) / D_M
    velocity_error = math.dist(tuple(map(float, motion["velocity_mps"])), velocities[node_index]) / U_MPS
    passed = identity_ok and position_error <= THRESHOLDS["committed_predictor_position_gap_over_D_max"] and velocity_error <= THRESHOLDS["committed_predictor_velocity_gap_over_U_max"]
    return {"identity_passed": identity_ok, "state_role": role, "node_index": node_index,
            "position_difference_over_D": position_error, "velocity_difference_over_U": velocity_error, "passed": passed}


def audit_checkpoint_identity(checkpoint: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    required = ("case_id", "slice_manifest_sha256", "config_sha256", "step", "time_s", "status")
    missing = [key for key in required if key not in checkpoint]
    mismatches = []
    for key in required:
        if key in checkpoint and key in expected:
            if key == "time_s":
                equal = abs(_finite(checkpoint[key], key) - _finite(expected[key], key)) <= 1e-12
            else:
                equal = checkpoint[key] == expected[key]
            if not equal:
                mismatches.append(key)
    slice_ids = [int(row["slice_id"]) for row in checkpoint.get("slices", [])]
    if sorted(slice_ids) != list(EXPECTED_SLICE_IDS) or len(set(slice_ids)) != len(EXPECTED_SLICE_IDS):
        mismatches.append("slices")
    passed = not missing and not mismatches and checkpoint.get("status") == "committed"
    return {"missing_fields": missing, "mismatched_fields": sorted(set(mismatches)), "slice_ids": slice_ids, "passed": passed}
