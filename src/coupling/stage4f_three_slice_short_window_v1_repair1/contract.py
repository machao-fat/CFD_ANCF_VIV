"""Frozen numerical contract for the isolated Stage 4F-C repair run.

This module is deliberately independent of the real-process runner so the
comparison definitions can be written and tested before OpenFOAM is started.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..multi_slice_mapping.mapping import RuntimeConfig, atomic_write_json, sha256_file
from ..stage4f_equilibrated_startup_v3.equilibrium import _read_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PARENT_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_fixed_point_v5" / "formal_preflight_attempt3"
PARENT_CHECKPOINT = PARENT_ROOT / "checkpoints" / "checkpoint_step00000002_d4def62051c1.json"
PARENT_ANCF_STATE = PROJECT_ROOT / "results" / "12_stage4f_fixed_point_v5" / "iteration2_exact_hold" / "fixed_point_state.mat"
PARENT_ANCF_STATE_SHA256 = "6d6d4ff3ee5e30c32538848c4980b50440a85c3be2cd9e1cac23be8561aa9ed8"
PARENT_CASE_ROOT = PARENT_ROOT / "cases"
# Repair artifacts are independent of the preserved v1 attempt2 evidence.
EXECUTION_ID = "stage4f_three_slice_short_window_v1_repair1"
RESULTS_ROOT = PROJECT_ROOT / "results" / EXECUTION_ID
CASE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / EXECUTION_ID
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / EXECUTION_ID

START_TIME_S = 1.5075
END_TIME_S = 1.5575
WINDOW_S = 0.05
D_M = 1.0
U_MPS = 1.0
RHO_KGPM3 = 1000.0
TOTAL_SPAN_M = 50.0
Q_INF_PA = 0.5 * RHO_KGPM3 * U_MPS * U_MPS

THRESHOLDS = {
    "cfl_strict_upper": 0.8,
    "abs_cd_max": 10.0,
    "virtual_work_relative_error_max": 1.0e-12,
    "force_conversion_relative_error_max": 1.0e-10,
    "restart_structure_relative_error_max": 1.0e-11,
    "restart_field_relative_error_max": 1.0e-11,
    "restart_force_relative_error_max": 1.0e-11,
    "mesh_center_motion_absolute_error_m_max": 1.0e-10,
    "committed_predictor_position_gap_over_D_max": 0.005,
    "committed_predictor_velocity_gap_over_U_max": 0.01,
    "dt_half_endpoint_position_over_D_max": 0.005,
    "dt_half_endpoint_velocity_over_U_max": 0.01,
    "dt_half_normalized_impulse_difference_max": 0.05,
    "dt_half_tension_relative_difference_max": 0.05,
}

BRANCHES = {
    "A": {"dt_s": 0.0025, "steps": 20, "segments": [20]},
    "B": {"dt_s": 0.0025, "steps": 20, "segments": [5, 15]},
    "C": {"dt_s": 0.00125, "steps": 40, "segments": [40]},
}

SCALES = {
    "D_m": D_M,
    "U_mps": U_MPS,
    "rho_kgpm3": RHO_KGPM3,
    "q_inf_Pa": Q_INF_PA,
    "total_span_m": TOTAL_SPAN_M,
    "impulse_scale_Ns": Q_INF_PA * D_M * TOTAL_SPAN_M * WINDOW_S,
    "state_position_abs_scale_m": D_M,
    "state_velocity_abs_scale_mps": U_MPS,
    "state_acceleration_abs_scale_mps2": U_MPS * U_MPS / D_M,
    "field_abs_scale": 1.0,
    "force_abs_scale_N": Q_INF_PA * D_M * TOTAL_SPAN_M,
    "tension_abs_scale_N": 1.0,
}

COMPARISON_DEFINITIONS = {
    "relative": "abs(a-b)/max(frozen_abs_scale,abs(a),abs(b))",
    "endpoint_position": "max Euclidean difference over ANCF node position triplets divided by D",
    "endpoint_velocity": "max Euclidean difference over ANCF node velocity triplets divided by U",
    "force_impulse": "component-wise trapezoidal integration including the parent t0 force; normalized by q_inf*D*total_span*window",
    "tension": "compare endpoint min and max with the frozen 1 N absolute scale in the relative denominator",
    "restart_fields": "SHA-256 equality preferred; otherwise parsed finite numeric tokens use frozen relative norm",
    "time_alignment": "A and B compare every identical target time; A and C compare the common endpoint and full-window trapezoidal impulses",
    "near_zero": "no data-dependent tiny denominator is permitted",
    "geometry": "cylinder boundary point centroid must equal the exact target motion record; predictor-to-corrected committed lag is separately bounded",
}

AUTHORIZATION = {"B_requires_A": True, "C_requires_A_and_B": True}
SCOPE_EXCLUSIONS = ["five_slice", "nine_slice", "long_time_viv", "lock_in", "experimental_validation", "stage4e_physical_validation"]


def _sha256_json(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def _times(dt_s: float, steps: int) -> list[float]:
    return [START_TIME_S + (index + 1) * dt_s for index in range(steps)]


def build_frozen_contract(parent_audit: Mapping[str, Any]) -> dict[str, Any]:
    manifest = _read_manifest()
    branch_rows: dict[str, Any] = {}
    for name, branch in BRANCHES.items():
        config = RuntimeConfig(
            schema_version="0.2.1", case_id=manifest.case_id,
            dt_s=float(branch["dt_s"]), timeout_s=90.0,
            start_time_s=START_TIME_S, coupling_iteration=0,
            coupling_scheme="explicit_weak",
            slice_manifest_sha256=manifest.slice_manifest_sha256,
        )
        branch_rows[name] = {
            **branch, "times_s": _times(float(branch["dt_s"]), int(branch["steps"])),
            "end_time_s": END_TIME_S, "runtime_config": config.to_dict(),
        }
    value: dict[str, Any] = {
        "schema": "stage4f-c-v1-frozen-contract-1.0.0",
        "frozen_before_real_execution": True,
        "parent_checkpoint": str(PARENT_CHECKPOINT),
        "parent_checkpoint_sha256": parent_audit["parent_checkpoint_sha256"],
        "parent_ancf_state": str(PARENT_ANCF_STATE),
        "parent_ancf_state_sha256": sha256_file(PARENT_ANCF_STATE),
        "parent_protection_combo_sha256": parent_audit["combined_sha256"],
        "protocol_schema": "0.2.1",
        "case_id": manifest.case_id,
        "slice_manifest_sha256": manifest.slice_manifest_sha256,
        "expected_slice_ids": [item.slice_id for item in manifest.slices],
        "start_time_s": START_TIME_S, "end_time_s": END_TIME_S,
        "window_s": WINDOW_S, "branches": branch_rows,
        "scales": dict(SCALES),
        "thresholds": dict(THRESHOLDS),
        "comparison_definitions": dict(COMPARISON_DEFINITIONS),
        "authorization": dict(AUTHORIZATION),
        "scope_exclusions": list(SCOPE_EXCLUSIONS),
    }
    value["contract_sha256"] = _sha256_json(value)
    return value


def validate_frozen_contract(value: Mapping[str, Any]) -> None:
    copy = dict(value)
    digest = str(copy.pop("contract_sha256", ""))
    if digest != _sha256_json(copy):
        raise ValueError("frozen contract hash mismatch")
    manifest = _read_manifest()
    if value.get("schema") != "stage4f-c-v1-frozen-contract-1.0.0":
        raise ValueError("contract schema changed")
    if not value.get("frozen_before_real_execution") or value.get("protocol_schema") != "0.2.1":
        raise ValueError("contract identity is not frozen")
    if str(value.get("parent_checkpoint")) != str(PARENT_CHECKPOINT):
        raise ValueError("parent checkpoint path changed")
    if value.get("parent_checkpoint_sha256") != sha256_file(PARENT_CHECKPOINT):
        raise ValueError("parent checkpoint hash changed")
    if str(value.get("parent_ancf_state")) != str(PARENT_ANCF_STATE) or value.get("parent_ancf_state_sha256") != PARENT_ANCF_STATE_SHA256:
        raise ValueError("parent ANCF state identity changed")
    if sha256_file(PARENT_ANCF_STATE) != PARENT_ANCF_STATE_SHA256:
        raise ValueError("parent ANCF state hash changed")
    if value.get("case_id") != manifest.case_id or value.get("slice_manifest_sha256") != manifest.slice_manifest_sha256:
        raise ValueError("manifest identity changed")
    if value.get("expected_slice_ids") != [item.slice_id for item in manifest.slices]:
        raise ValueError("expected slice identity changed")
    for key, expected in (("start_time_s", START_TIME_S), ("end_time_s", END_TIME_S), ("window_s", WINDOW_S)):
        if not math.isclose(float(value.get(key, math.nan)), expected, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"{key} changed")
    if set(value.get("branches", {})) != set(BRANCHES):
        raise ValueError("branch identity changed")
    for name, expected in BRANCHES.items():
        branch = value["branches"][name]
        if (not math.isclose(float(branch.get("dt_s", math.nan)), float(expected["dt_s"]), rel_tol=0.0, abs_tol=1e-15)
                or int(branch["steps"]) != expected["steps"] or list(branch["segments"]) != expected["segments"]):
            raise ValueError(f"branch {name} schedule changed")
        times = branch["times_s"]
        expected_times = _times(float(expected["dt_s"]), int(expected["steps"]))
        if (len(times) != len(expected_times)
                or any(not math.isclose(float(actual), frozen, rel_tol=0.0, abs_tol=1e-12) for actual, frozen in zip(times, expected_times))
                or not math.isclose(float(branch.get("end_time_s", math.nan)), END_TIME_S, rel_tol=0.0, abs_tol=1e-12)):
            raise ValueError(f"branch {name} time grid changed")
        expected_runtime = RuntimeConfig(
            schema_version="0.2.1", case_id=manifest.case_id,
            dt_s=float(expected["dt_s"]), timeout_s=90.0,
            start_time_s=START_TIME_S, coupling_iteration=0,
            coupling_scheme="explicit_weak",
            slice_manifest_sha256=manifest.slice_manifest_sha256,
        ).to_dict()
        if branch.get("runtime_config") != expected_runtime:
            raise ValueError(f"branch {name} runtime identity changed")
    if value["thresholds"] != THRESHOLDS:
        raise ValueError("hard thresholds changed")
    if value.get("scales") != SCALES:
        raise ValueError("frozen comparison scales changed")
    if value.get("comparison_definitions") != COMPARISON_DEFINITIONS:
        raise ValueError("comparison definitions changed")
    if value.get("authorization") != AUTHORIZATION or value.get("scope_exclusions") != SCOPE_EXCLUSIONS:
        raise ValueError("authorization or scope boundary changed")


def write_frozen_contract(path: Path, parent_audit: Mapping[str, Any]) -> dict[str, Any]:
    value = build_frozen_contract(parent_audit)
    validate_frozen_contract(value)
    atomic_write_json(path, value)
    return value


def scaled_relative(a: float, b: float, absolute_scale: float) -> float:
    values = (float(a), float(b), float(absolute_scale))
    if not all(math.isfinite(item) for item in values) or absolute_scale <= 0.0:
        raise ValueError("relative comparison requires finite values and a positive frozen scale")
    return abs(a - b) / max(absolute_scale, abs(a), abs(b))


def trapezoidal_impulse(times_s: Sequence[float], forces_N: Sequence[Sequence[float]]) -> list[float]:
    if len(times_s) != len(forces_N) or len(times_s) < 2:
        raise ValueError("impulse needs aligned time and force rows")
    if any(float(times_s[index + 1]) <= float(times_s[index]) for index in range(len(times_s) - 1)):
        raise ValueError("impulse times must be strictly increasing")
    result = [0.0, 0.0, 0.0]
    for index in range(len(times_s) - 1):
        dt = float(times_s[index + 1]) - float(times_s[index])
        for axis in range(3):
            result[axis] += 0.5 * dt * (float(forces_N[index][axis]) + float(forces_N[index + 1][axis]))
    if not all(math.isfinite(value) for value in result):
        raise ValueError("impulse contains NaN/Inf")
    return result
