from __future__ import annotations

import hashlib
import json

PARENT_SHA256 = "4da73e2a7a8d526fa41a12fc155790d2a361706f57f38403207164cfce7268a9"
START_TICK_NS = 1_520_000_000
DT_TICK_NS = 625_000
BLOCKS = ((20, 25), (25, 30), (30, 35), (35, 40))
RESTART_RANGE = (35, 40)
END_TICK_NS = 1_532_500_000


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build_contract():
    value = {
        "schema": "stage4f-c-limited-extension-v2-1.0.0", "parent_checkpoint_sha256": PARENT_SHA256,
        "start_tick_ns": START_TICK_NS, "dt_tick_ns": DT_TICK_NS,
        "continuous_blocks": [list(row) for row in BLOCKS], "continuous_global_steps": list(range(20, 40)),
        "continuous_target_ticks_ns": [START_TICK_NS + (i + 1) * DT_TICK_NS for i in range(20)],
        "restart_parent_step": 34, "restart_global_steps": list(range(*RESTART_RANGE)),
        "end_tick_ns": END_TICK_NS, "total_steps_from_original_start": 40, "total_window_s": 0.025,
        "relaxation_alpha": 0.5, "max_iterations_per_step": 12,
        "force_residual_absolute_max_N": 25.0, "force_residual_relative_max": 1e-3,
        "force_residual_denominator": "max(25000 N, observed_linf_N, relaxed_linf_N)",
        "consecutive_converged_iterations": 2, "final_max_abs_Cd": 10.0, "max_CFL_exclusive": 0.8,
        "force_conversion_relative_error_max": 1e-10, "virtual_work_relative_error_max": 1e-12,
        "position_difference_over_D_max": 0.005, "velocity_difference_over_U_max": 0.01,
        "restart_structure_relative_linf_max": 1e-11, "restart_previous_force_relative_linf_max": 1e-11,
        "restart_time_absolute_error_max_s": 1e-12, "restart_cfd_fields_per_step": 24,
        "block_authorization": "previous_block_passed_and_owned_residual_zero",
        "restart_authorization": "all_four_continuous_blocks_passed_and_owned_residual_zero",
        "terminal_force_policy": "target_is_last_complete_row_and_content_identical_after_natural_exit",
        "hard_stops": ["nonfinite", "FOAM_FATAL", "floating_point_crash", "negative_volume", "CFL_gte_0.8", "final_Cd_gt_10", "force_identity", "force_conversion", "virtual_work", "geometry", "iteration_limit", "owned_process_residual"],
        "trend_diagnostics_only": ["selected_iteration_count", "force_residual_contraction", "Cd", "CFL", "position", "velocity"],
        "forbidden_scope": ["five_slice", "nine_slice", "long_time_VIV", "lock_in", "experimental_validation", "physical_validation"],
    }
    value["contract_sha256"] = _hash(value)
    return value


def validate_contract(value):
    if value != build_contract():
        raise ValueError("limited extension v2 contract changed")
