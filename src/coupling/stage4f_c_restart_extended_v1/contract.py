"""Frozen, offline-only restart and bounded-extension contract."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


SCHEMA = "stage4f-c-restart-extended-v1-1.0.0"
RELAXATION_ALPHA = 0.5
MAX_ITERATIONS_PER_STEP = 12
FINAL_MAX_ABS_CD = 10.0
FORCE_RESIDUAL_RELATIVE_MAX = 1.0e-3
FORCE_RESIDUAL_ABSOLUTE_MAX_N = 25.0
FORCE_RESIDUAL_RELATIVE_SCALE_N = 25_000.0
CONSECUTIVE_CONVERGED_ITERATIONS = 2
MAX_CFL_EXCLUSIVE = 0.8
POSITION_DIFFERENCE_OVER_D_MAX = 0.005
VELOCITY_DIFFERENCE_OVER_U_MAX = 0.01
VIRTUAL_WORK_RELATIVE_ERROR_MAX = 1.0e-12
FORCE_CONVERSION_RELATIVE_ERROR_MAX = 1.0e-10
STRUCTURE_RELATIVE_TOLERANCE = 1.0e-11
START_TIME_S = 1.5075
DT_S = 0.000625
RESTART_IDENTITY_STEPS = 3
FIRST_LEG_STEPS = 1
RESTART_LEG_STEPS = 2
TOTAL_AUTHORIZED_STEPS = 10
EXTENSION_STEPS = 7
END_TIME_S = 1.51375
CFD_FIELDS = ("U", "p", "phi", "Uf", "meshPhi", "points")
HARD_GATES = (
    "nonfinite",
    "FATAL",
    "CFL",
    "negative_volume",
    "force_conversion",
    "virtual_work",
    "geometry_failure",
)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def build_contract(original_parent_checkpoint_sha256: str) -> dict[str, Any]:
    """Build the immutable gate; it deliberately exposes no execution entry point."""
    if not is_sha256(original_parent_checkpoint_sha256):
        raise ValueError("original parent checkpoint SHA-256 is invalid")
    contract: dict[str, Any] = {
        "schema": SCHEMA,
        "execution_mode": "real_restart_identity_then_bounded_extension",
        "original_parent_checkpoint_sha256": original_parent_checkpoint_sha256,
        "restart_identity_protocol": "continuous_3_steps_vs_first_leg_1_step_shutdown_restart_leg_2_steps",
        "restart_identity_steps": RESTART_IDENTITY_STEPS,
        "first_leg_steps": FIRST_LEG_STEPS,
        "restart_leg_steps": RESTART_LEG_STEPS,
        "compare_final_predictor": ["q", "qdot", "qddot"],
        "structure_relative_tolerance": STRUCTURE_RELATIVE_TOLERANCE,
        "compare_cfd_fields": list(CFD_FIELDS),
        "cfd_comparison": "identical_sha256_or_strictly_identical_parsed_numeric_values",
        "compare_observed_forces": "strictly_identical_finite_numeric_values",
        "compare_checkpoint_lineage": "each_stream_is_contiguous_and_restart_leg_begins_at_first_leg_commit",
        "restart_process_boundary": "all_owned_processes_closed_with_zero_residual_and_zero_nonzero_return_codes",
        "relaxation_alpha": RELAXATION_ALPHA,
        "max_iterations_per_physical_step": MAX_ITERATIONS_PER_STEP,
        "final_acceptance_gate": "residual_converged_twice_and_abs_Cd_lte_10",
        "final_max_abs_Cd": FINAL_MAX_ABS_CD,
        "force_residual_relative_max": FORCE_RESIDUAL_RELATIVE_MAX,
        "force_residual_absolute_max_N": FORCE_RESIDUAL_ABSOLUTE_MAX_N,
        "force_residual_relative_scale_N": FORCE_RESIDUAL_RELATIVE_SCALE_N,
        "consecutive_residual_converged_iterations": CONSECUTIVE_CONVERGED_ITERATIONS,
        "max_CFL_exclusive": MAX_CFL_EXCLUSIVE,
        "position_difference_over_D_max": POSITION_DIFFERENCE_OVER_D_MAX,
        "velocity_difference_over_U_max": VELOCITY_DIFFERENCE_OVER_U_MAX,
        "virtual_work_relative_error_max": VIRTUAL_WORK_RELATIVE_ERROR_MAX,
        "force_conversion_relative_error_max": FORCE_CONVERSION_RELATIVE_ERROR_MAX,
        "hard_gates": list(HARD_GATES),
        "extended_authorization": "only_after_restart_identity_audit_passes",
        "total_authorized_physical_steps": TOTAL_AUTHORIZED_STEPS,
        "additional_authorized_physical_steps": EXTENSION_STEPS,
        "start_time_s": START_TIME_S,
        "dt_s": DT_S,
        "authorized_end_time_s": END_TIME_S,
    }
    contract["contract_sha256"] = canonical_sha256(contract)
    return contract


def validate_contract(value: Mapping[str, Any]) -> None:
    candidate = dict(value)
    supplied = candidate.pop("contract_sha256", None)
    if supplied != canonical_sha256(candidate):
        raise ValueError("contract hash mismatch")
    parent = candidate.get("original_parent_checkpoint_sha256")
    if not isinstance(parent, str) or dict(value) != build_contract(parent):
        raise ValueError("frozen restart and extension contract changed")
