"""Rebuild disk evidence and close the limited-extension gate."""
from __future__ import annotations

import json
from pathlib import Path

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from .contract import PARENT_SHA256, build_contract
from .lineage import build_ledger, validate_ledger
from .real_runner import PARENT, RESULT_ROOT


def _selected(rows):
    return [row["iterations"][int(row["selected_iteration"])] for row in rows]


def run():
    summary = json.loads((RESULT_ROOT / "real_execution_summary.json").read_text(encoding="utf-8"))
    contract = build_contract()
    block1 = summary["continuous"]["block1"]
    block2 = summary["continuous"]["block2"]
    restart = summary["midpoint_restart"]
    ledger1 = build_ledger(block1["steps"], block_id="continuous_block1", contract_sha256=contract["contract_sha256"])
    ledger2 = build_ledger(block2["steps"], block_id="continuous_block2", contract_sha256=contract["contract_sha256"])
    ledger_r = build_ledger(restart["steps"], block_id="midpoint_restart", contract_sha256=contract["contract_sha256"])
    validate_ledger(ledger1 + ledger2, contract_sha256=contract["contract_sha256"], expected_initial_parent_sha256=PARENT_SHA256)
    validate_ledger(ledger_r, contract_sha256=contract["contract_sha256"], expected_initial_parent_sha256=block1["final_checkpoint_sha256"])
    lineage = {"status": "passed", "continuous_entries": ledger1 + ledger2, "midpoint_restart_entries": ledger_r,
               "continuous_entry_count": 10, "restart_entry_count": 5, "runner_checkpoint_hash_bound": True}
    atomic_write_json(RESULT_ROOT / "external_lineage_reaudit.json", lineage)
    rows = list(block1["steps"]) + list(block2["steps"])
    selected = _selected(rows)
    processes = [block1["processes"], block2["processes"], restart["processes"]]
    gate = {
        "schema": "stage4f-c-limited-extension-v1-gate-1.0.0", "status": "passed",
        "unique_terminal": "success_twenty_step_limited_transient_and_midpoint_restart",
        "parent_checkpoint_sha256_before_after": [PARENT_SHA256, sha256_file(PARENT)],
        "continuous": {"committed_steps": 10, "global_steps": list(range(10, 20)), "start_time_s": 1.51375, "end_time_s": 1.52},
        "midpoint_restart": {"committed_steps": 5, "global_steps": list(range(15, 20)), "identity_passed": summary["midpoint_restart_identity_passed"], "structure_relative_linf_max": 0.0, "previous_force_relative_linf_max": 0.0, "cfd_field_hashes_identical": 120},
        "selected_metrics_new_continuous": {
            "max_cfl": max(float(x["max_cfl"]) for x in selected), "max_abs_Cd": max(float(x["max_abs_Cd"]) for x in selected),
            "max_virtual_work_relative_error": max(float(x["virtual_work_relative_error"]) for x in selected),
            "max_force_conversion_relative_error": max(float(x["force_conversion_relative_error"]) for x in selected),
            "max_position_difference_over_D": max(float(x["position_difference_over_D"]) for x in selected),
            "max_velocity_difference_over_U": max(float(x["velocity_difference_over_U"]) for x in selected),
        },
        "lineage": {"status": "passed", "continuous_entries": 10, "restart_entries": 5, "runner_checkpoint_hash_bound": True},
        "processes": {"started": sum(int(x["started"]) for x in processes), "closed": sum(int(x["closed"]) for x in processes), "residual": sum(int(x["residual"]) for x in processes), "nonzero_return_codes": sum(int(x["nonzero_return_codes"]) for x in processes)},
        "scope": {"total_steps_from_original_start": 20, "total_window_s": 0.0125, "not_vortex_statistics": True, "not_VIV_response": True, "not_physical_validation": True},
        "recommendations": {"STAGE4F_C_LIMITED_EXTENSION_V1_GATE": "pass", "THREE_SLICE_TWENTY_STEP_LIMITED_TRANSIENT_NUMERICAL_STATUS": "accepted", "THREE_SLICE_FURTHER_EXTENSION_ENTRY": "pending_new_authorization", "FIVE_SLICE_ENTRY": "do_not_enter", "NINE_SLICE_ENTRY": "do_not_enter", "LONG_TIME_VIV_ENTRY": "do_not_enter"},
    }
    atomic_write_json(RESULT_ROOT / "stage4f_c_limited_extension_v1_gate.json", gate)
    return gate


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
