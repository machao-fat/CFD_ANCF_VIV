"""Frozen, offline-only contract for predictor-consistent strong coupling."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


SCHEMA = "stage4f-c-predictor-consistent-strong-v2-1.0.0"
ALPHA = 0.5
MAX_ITERATIONS = 12
FORCE_RESIDUAL_RELATIVE_MAX = 1.0e-3
FORCE_RESIDUAL_ABSOLUTE_MAX_N = 25.0
FORCE_RESIDUAL_RELATIVE_SCALE_N = 25_000.0
CONSECUTIVE_CONVERGED_ITERATIONS = 2
MAX_ABS_CD = 10.0
MAX_CFL_EXCLUSIVE = 0.8
POSITION_DIFFERENCE_OVER_D_MAX = 0.005
VELOCITY_DIFFERENCE_OVER_U_MAX = 0.01
VIRTUAL_WORK_RELATIVE_ERROR_MAX = 1.0e-12
FORCE_CONVERSION_RELATIVE_ERROR_MAX = 1.0e-10


def canonical_sha256(value: Any) -> str:
    """Hash JSON evidence deterministically; non-finite values are forbidden."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def build_contract(parent_checkpoint_sha256: str) -> dict[str, Any]:
    if not is_sha256(parent_checkpoint_sha256):
        raise ValueError("parent checkpoint SHA-256 must be 64 lowercase hexadecimal characters")
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "parent_checkpoint_sha256": parent_checkpoint_sha256,
        "execution_scope": "three_physical_step_real_preflight",
        "relaxation_alpha": ALPHA,
        "max_iterations_per_physical_step": MAX_ITERATIONS,
        "force_residual_relative_max": FORCE_RESIDUAL_RELATIVE_MAX,
        "force_residual_absolute_max_N": FORCE_RESIDUAL_ABSOLUTE_MAX_N,
        "force_residual_relative_denominator": "max(25000_N,norm_inf(F_relaxed),norm_inf(F_observed))",
        "consecutive_residual_converged_iterations": CONSECUTIVE_CONVERGED_ITERATIONS,
        "candidate_cfd_motion": "must be generated from the current relaxed-force predictor",
        "predictor_cfd_provenance": "predictor_state_sha256 and cfd_motion_sha256 must be recomputable and linked",
        "commit_policy": "commit exactly one selected predictor ANCF state and its matching predictor-geometry CFD field",
        "previous_slice_forces_policy": "store actual_observed_CFD_force_not_relaxed_force",
        "final_acceptance_gate": "residual_converged_twice_and_abs_Cd_lte_10",
        "intermediate_Cd_policy": "record_only_when_finite; no_immediate_stop_for_finite_excess",
        "immediate_hard_stop": "nonfinite_or_FATAL_or_CFL_or_negative_volume_or_conversion_or_virtual_work_or_geometry_failure",
    }
    value["contract_sha256"] = canonical_sha256(value)
    return value


def validate_contract(value: Mapping[str, Any]) -> None:
    candidate = dict(value)
    supplied = candidate.pop("contract_sha256", None)
    if supplied != canonical_sha256(candidate):
        raise ValueError("contract hash mismatch")
    parent = candidate.get("parent_checkpoint_sha256")
    if not isinstance(parent, str) or dict(value) != build_contract(parent):
        raise ValueError("frozen predictor-consistent strong-coupling contract changed")
