from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

START_TIME_S = 1.5075
END_TIME_S = 1.515
SLICE_IDS = (0, 1, 2)
SLICE_SPAN_M = 16.666666666666668
BRANCHES = {"D1": {"dt_s": 0.00125, "steps": 6}, "D2": {"dt_s": 0.000625, "steps": 12}}
THRESHOLDS = {"abs_cd_max": 10.0, "velocity_difference_over_U_max": 0.01, "cfl_strict_upper": 0.8,
              "virtual_work_relative_error_max": 1e-12, "force_conversion_relative_error_max": 1e-10,
              "mesh_center_motion_absolute_error_m_max": 1e-10,
              "position_difference_over_D_max": 0.005}
TERMINALS = ("accepted_timestep_refinement_candidate", "failure_timestep_refinement_not_sufficient", "failure_identity_or_runtime_blocked")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def build_contract(parent_checkpoint: str, parent_sha256: str, protection_sha256: str) -> dict[str, Any]:
    value = {"schema": "stage4f-three-slice-timestep-diagnostic-v2-1.0.0", "parent_checkpoint": parent_checkpoint,
             "parent_checkpoint_sha256": parent_sha256, "parent_protection_sha256": protection_sha256,
             "start_time_s": START_TIME_S, "end_time_s": END_TIME_S, "slice_ids": list(SLICE_IDS),
             "slice_span_m": SLICE_SPAN_M, "branches": {name: {**row, "times_s": [START_TIME_S + (i + 1) * row["dt_s"] for i in range(row["steps"])]} for name, row in BRANCHES.items()},
             "thresholds": dict(THRESHOLDS), "terminal_states": list(TERMINALS),
             "D1_policy": "Cd/velocity-only failure permits complete D1 and authorizes D2; every other hard failure blocks"}
    value["contract_sha256"] = _digest(value)
    return value


def validate_contract(value: Mapping[str, Any]) -> None:
    copy = dict(value); supplied = copy.pop("contract_sha256", None)
    if supplied != _digest(copy): raise ValueError("contract hash mismatch")
    if value.get("slice_ids") != list(SLICE_IDS) or not math.isclose(float(value.get("slice_span_m")), SLICE_SPAN_M): raise ValueError("slice identity changed")
    if value.get("thresholds") != THRESHOLDS or value.get("terminal_states") != list(TERMINALS): raise ValueError("gate contract changed")
    if set(value.get("branches", {})) != set(BRANCHES): raise ValueError("branch set changed")
    for name, frozen in BRANCHES.items():
        row = value["branches"][name]
        if float(row["dt_s"]) != frozen["dt_s"] or int(row["steps"]) != frozen["steps"]: raise ValueError(f"{name} schedule changed")
        expected = [START_TIME_S + (i + 1) * frozen["dt_s"] for i in range(frozen["steps"])]
        if len(row["times_s"]) != len(expected) or any(abs(float(a)-b) > 1e-12 for a,b in zip(row["times_s"], expected)): raise ValueError(f"{name} time grid changed")
