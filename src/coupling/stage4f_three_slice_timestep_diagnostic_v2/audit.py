from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .contract import BRANCHES, END_TIME_S, SLICE_IDS, THRESHOLDS

TOLERATED_D1 = {"abs_cd", "velocity_consistency"}


def audit_step(row: Mapping[str, Any], *, branch: str, expected_step: int) -> dict[str, Any]:
    schedule = BRANCHES[branch]; expected_time = 1.5075 + (expected_step + 1) * schedule["dt_s"]
    slices = list(row.get("slices", [])); ids = [int(item["slice_id"]) for item in slices]
    failures = []
    if sorted(ids) != list(SLICE_IDS) or len(set(ids)) != len(SLICE_IDS): failures.append("slice_identity")
    if int(row.get("step", -1)) != expected_step or abs(float(row.get("time_s", math.nan))-expected_time) > 1e-12: failures.append("time_alignment")
    if row.get("force_observation_unique") is not True: failures.append("force_observation_identity")
    if row.get("state_role") != "committed" or row.get("geometry_state_role") != "predictor": failures.append("state_role")
    gates = (("cfl", float(row.get("max_cfl", math.inf)) < THRESHOLDS["cfl_strict_upper"]),
             ("virtual_work", float(row.get("virtual_work_relative_error", math.inf)) <= THRESHOLDS["virtual_work_relative_error_max"]),
             ("force_conversion", float(row.get("force_conversion_relative_error", math.inf)) <= THRESHOLDS["force_conversion_relative_error_max"]),
             ("mesh_geometry", float(row.get("mesh_center_motion_error_m", math.inf)) <= THRESHOLDS["mesh_center_motion_absolute_error_m_max"]),
             ("position_consistency", float(row.get("position_difference_over_D", math.inf)) <= THRESHOLDS["position_difference_over_D_max"]),
             ("abs_cd", float(row.get("max_abs_Cd", math.inf)) <= THRESHOLDS["abs_cd_max"]),
             ("velocity_consistency", float(row.get("velocity_difference_over_U", math.inf)) <= THRESHOLDS["velocity_difference_over_U_max"]),
             ("log", row.get("log_passed") is True), ("checkpoint", row.get("checkpoint_passed") is True),
             ("process_evidence", row.get("process_evidence_passed") is True))
    failures.extend(name for name, passed in gates if not passed)
    blocking = [name for name in failures if name not in TOLERATED_D1]
    return {"branch": branch, "step": expected_step, "expected_time_s": expected_time, "failures": failures,
            "blocking_failures": blocking, "diagnostic_continuation_allowed": branch == "D1" and not blocking,
            "passed": not failures}


def audit_branch(branch: str, steps: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    expected = BRANCHES[branch]["steps"]
    rows = [audit_step(row, branch=branch, expected_step=i) for i, row in enumerate(steps)]
    complete = len(steps) == expected and len(rows) == expected and abs(float(steps[-1]["time_s"])-END_TIME_S) <= 1e-12 if steps else False
    blocking = sorted({failure for row in rows for failure in row["blocking_failures"]})
    failures = sorted({failure for row in rows for failure in row["failures"]})
    authorize_d2 = branch == "D1" and complete and not blocking
    return {"branch": branch, "steps_requested": expected, "steps_completed": len(steps), "complete": complete,
            "failures": failures, "blocking_failures": blocking, "D2_authorized": authorize_d2, "rows": rows,
            "passed": complete and not failures}


def final_gate(d1: Mapping[str, Any], d2: Mapping[str, Any] | None) -> dict[str, Any]:
    if not d1.get("complete") or d1.get("blocking_failures"):
        terminal = "failure_identity_or_runtime_blocked"
    elif not d1.get("D2_authorized") or d2 is None or not d2.get("complete"):
        terminal = "failure_identity_or_runtime_blocked"
    elif d2.get("blocking_failures"):
        terminal = "failure_identity_or_runtime_blocked"
    elif d2.get("failures"):
        terminal = "failure_timestep_refinement_not_sufficient"
    else:
        terminal = "accepted_timestep_refinement_candidate"
    return {"terminal_state": terminal, "passed": terminal == "accepted_timestep_refinement_candidate"}
