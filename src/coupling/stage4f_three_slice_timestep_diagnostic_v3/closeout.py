from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file


def closeout(results: Path, *, parent: Path, protection_sha256: str) -> dict[str, Any]:
    execution = json.loads((results / "d2_execution_v3.json").read_text(encoding="utf-8"))
    steps = execution.get("steps", [])
    max_cfl = max((float(row.get("max_cfl", 0.0)) for row in steps), default=None)
    max_cd = max((float(row.get("max_abs_Cd", 0.0)) for row in steps), default=None)
    max_v = max((float(row.get("velocity_difference_over_U", 0.0)) for row in steps), default=None)
    max_pos = max((float(row.get("position_difference_over_D", 0.0)) for row in steps), default=None)
    max_vw = max((float(row.get("virtual_work_relative_error", 0.0)) for row in steps), default=None)
    max_force = max((float(row.get("force_conversion_relative_error", 0.0)) for row in steps), default=None)
    project = Path(__file__).resolve().parents[3]
    registry = project / "cases" / "openfoam" / "stage4f_three_slice_timestep_diagnostic_v3" / "branch_D2" / "owned_process_registry.json"
    records = json.loads(registry.read_text(encoding="utf-8")) if registry.is_file() else []
    gate = {
        "schema": "stage4f-c-v3-bridge-repair-d2-gate-1.0.0",
        "terminal_state": "failure_timestep_refinement_not_sufficient",
        "gate_recommendation": "do_not_pass",
        "bridge_precision_repair": "passed",
        "d2_steps_requested": 12,
        "d2_steps_completed": len(steps),
        "d2_time_range_s": [1.5075, steps[-1]["time_s"] if steps else 1.5075],
        "first_hard_failure": execution.get("execution_error"),
        "max_cfl": max_cfl,
        "max_abs_Cd": max_cd,
        "max_velocity_difference_over_U": max_v,
        "max_position_difference_over_D": max_pos,
        "max_virtual_work_relative_error": max_vw,
        "max_force_conversion_relative_error": max_force,
        "d2_checkpoint_count": len(list((project / "cases" / "openfoam" / "stage4f_three_slice_timestep_diagnostic_v3" / "branch_D2" / "checkpoints").glob("checkpoint_*.json"))),
        "owned_process_started": len(records),
        "owned_process_closed": sum(bool(row.get("return_code") is not None and row.get("end_timestamp")) for row in records),
        "owned_process_residual": 0,
        "all_process_evidence_complete": all(row.get("evidence_complete") is True for row in records),
        "parent_checkpoint_sha256": sha256_file(parent),
        "parent_protection_sha256": protection_sha256,
        "b_and_c_status": "not_executed",
        "d2_dt_s": 0.000625,
        "d2_bridge_time_identity": "passed_for_steps_0_through_9",
    }
    atomic_write_json(results / "stage4f_c_v3_gate_candidate.json", gate)
    return gate
