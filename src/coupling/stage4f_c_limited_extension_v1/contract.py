"""Frozen contract for the bounded extension and midpoint restart."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA = "stage4f-c-limited-extension-v1-1.0.0"
PARENT_SHA256 = "c27916359016ffbd09fef9d6eed19175a48dc85a1a11ee00f12664d240023fb0"
START_TICK_NS = 1_513_750_000
DT_TICK_NS = 625_000
CONTINUOUS_STEPS = tuple(range(10, 20))
RESTART_STEPS = tuple(range(15, 20))
MIDPOINT_PARENT_STEP = 14
END_TICK_NS = 1_520_000_000


def canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_contract() -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "parent_checkpoint_sha256": PARENT_SHA256,
        "start_tick_ns": START_TICK_NS,
        "dt_tick_ns": DT_TICK_NS,
        "continuous_global_steps": list(CONTINUOUS_STEPS),
        "continuous_atomic_blocks": [[10, 11, 12, 13, 14], [15, 16, 17, 18, 19]],
        "continuous_target_ticks_ns": [START_TICK_NS + (i + 1) * DT_TICK_NS for i in range(10)],
        "restart_parent_global_step": MIDPOINT_PARENT_STEP,
        "restart_global_steps": list(RESTART_STEPS),
        "restart_target_ticks_ns": [START_TICK_NS + (i + 1) * DT_TICK_NS for i in range(5, 10)],
        "end_tick_ns": END_TICK_NS,
        "total_window_from_original_start_s": 0.0125,
        "relaxation_alpha": 0.5,
        "max_iterations_per_step": 12,
        "force_residual_absolute_max_N": 25.0,
        "force_residual_relative_max": 1.0e-3,
        "force_residual_denominator": "max(25000 N, observed_linf_N, relaxed_linf_N)",
        "consecutive_converged_iterations": 2,
        "final_max_abs_Cd": 10.0,
        "max_CFL_exclusive": 0.8,
        "force_conversion_relative_error_max": 1.0e-10,
        "virtual_work_relative_error_max": 1.0e-12,
        "position_difference_over_D_max": 0.005,
        "velocity_difference_over_U_max": 0.01,
        "mesh_motion_absolute_error_max_m": 1.0e-10,
        "restart_structure_relative_linf_max": 1.0e-11,
        "restart_previous_force_relative_linf_max": 1.0e-11,
        "restart_time_absolute_error_max_s": 1.0e-12,
        "restart_cfd_fields_per_step": 24,
        "external_lineage_ledger_required": True,
        "terminal_force_policy": "natural_exit_then_unique_exact_row_content_identity_then_terminal_fingerprint_audit",
        "continuous_failure_forbids_restart": True,
        "intermediate_finite_Cd_over_10": "diagnostic_only_never_committed",
        "hard_stops": ["nonfinite", "FOAM_FATAL", "floating_point_crash", "negative_volume", "CFL_gte_0.8", "force_identity", "force_conversion", "virtual_work", "geometry", "iteration_limit", "owned_process_residual"],
        "forbidden_scope": ["five_slice", "nine_slice", "long_time_VIV", "lock_in", "experimental_validation", "physical_validation"],
    }
    value["contract_sha256"] = canonical_sha256(value)
    return value


def validate_contract(value: Mapping[str, Any]) -> None:
    if dict(value) != build_contract():
        raise ValueError("limited extension contract changed")
