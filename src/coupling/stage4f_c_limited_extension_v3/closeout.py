from __future__ import annotations

import json
from pathlib import Path
from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from ..stage4f_c_limited_extension_v1.lineage import validate_ledger
from .contract import BLOCKS, PARENT_SHA256, build_contract
from .disk_audit import audit_block
from .real_runner import CASE_ROOT, PARENT, RESULT_ROOT


def run():
    summary=json.loads((RESULT_ROOT/"real_execution_summary.json").read_text(encoding="utf-8")); contract=build_contract()
    if summary.get("status")!="passed" or not summary.get("continuous_passed") or not summary.get("restart_identity_passed"): raise RuntimeError("runner evidence does not authorize a passing closeout")
    blocks=summary["continuous_blocks"]
    if len(blocks)!=4: raise RuntimeError("four continuous blocks are required")
    disk_blocks=[audit_block(block,case_block_root=CASE_ROOT/f"continuous_block{i}",expected_start=start,expected_end=end) for i,(block,(start,end)) in enumerate(zip(blocks,BLOCKS),1)]
    restart=audit_block(summary["final_window_restart"],case_block_root=CASE_ROOT/"final_window_restart",expected_start=35,expected_end=40)
    ledgers=summary["lineage_counts"]
    if ledgers!={"continuous_block1":5,"continuous_block2":5,"continuous_block3":5,"continuous_block4":5,"final_window_restart":5}: raise RuntimeError("lineage counts are incomplete")
    disk_ledger=json.loads((RESULT_ROOT/"external_lineage_ledgers.json").read_text(encoding="utf-8"))
    continuous=sum((disk_ledger[f"continuous_block{i}"] for i in range(1,5)),[])
    validate_ledger(continuous,contract_sha256=contract["contract_sha256"],expected_initial_parent_sha256=PARENT_SHA256)
    validate_ledger(disk_ledger["final_window_restart"],contract_sha256=contract["contract_sha256"],expected_initial_parent_sha256=blocks[2]["final_checkpoint_sha256"])
    comparisons=summary["restart_comparisons"]
    if len(comparisons)!=5 or not all(x["passed"] and x["comparisons"]["cfd_manifest_field_hashes"]["candidate_count"]==24 for x in comparisons): raise RuntimeError("restart identity comparison is incomplete")
    selected=[row["iterations"][row["selected_iteration"]] for block in blocks for row in block["steps"]]
    process_rows=[x["processes"] for x in blocks]+[summary["final_window_restart"]["processes"]]
    disk={"status":"passed","continuous_blocks":disk_blocks,"restart_block":restart,"unique_committed_steps":25,"continuous_lineage_entries":20,"restart_lineage_entries":5,"restart_cfd_hashes_identical":120}
    atomic_write_json(RESULT_ROOT/"disk_rebuilt_gate_audit.json",disk)
    gate={"schema":"stage4f-c-limited-extension-v2-gate-1.0.0","status":"passed","unique_terminal":"success_forty_step_limited_transient_and_final_window_restart","parent_checkpoint_sha256_before_after":[PARENT_SHA256,sha256_file(PARENT)],"continuous":{"committed_steps":20,"global_steps":list(range(20,40)),"start_time_s":1.52,"end_time_s":1.5325},"restart":{"committed_steps":5,"global_steps":list(range(35,40)),"identity_passed":True,"structure_relative_linf_max":0.0,"previous_force_relative_linf_max":0.0,"cfd_field_hashes_identical":120},"selected_metrics":{"max_cfl":max(x["max_cfl"] for x in selected),"max_abs_Cd":max(x["max_abs_Cd"] for x in selected),"max_virtual_work_relative_error":max(x["virtual_work_relative_error"] for x in selected),"max_force_conversion_relative_error":max(x["force_conversion_relative_error"] for x in selected),"max_position_difference_over_D":max(x["position_difference_over_D"] for x in selected),"max_velocity_difference_over_U":max(x["velocity_difference_over_U"] for x in selected)},"disk_audit":disk,"processes":{"started":sum(x["started"] for x in process_rows),"closed":sum(x["closed"] for x in process_rows),"residual":sum(x["residual"] for x in process_rows),"nonzero_return_codes":sum(x["nonzero_return_codes"] for x in process_rows)},"scope":{"total_steps_from_original_start":40,"total_window_s":0.025,"not_vortex_statistics":True,"not_VIV_response":True,"not_physical_validation":True},"recommendations":{"STAGE4F_C_LIMITED_EXTENSION_V2_GATE":"pass","THREE_SLICE_FORTY_STEP_LIMITED_TRANSIENT_NUMERICAL_STATUS":"accepted","THREE_SLICE_FURTHER_EXTENSION_ENTRY":"pending_new_authorization","FIVE_SLICE_ENTRY":"do_not_enter","NINE_SLICE_ENTRY":"do_not_enter","LONG_TIME_VIV_ENTRY":"do_not_enter"}}
    if gate["processes"]["started"]!=gate["processes"]["closed"] or gate["processes"]["residual"] or gate["processes"]["nonzero_return_codes"]: raise RuntimeError("process evidence does not pass")
    atomic_write_json(RESULT_ROOT/"stage4f_c_limited_extension_v2_gate.json",gate);return gate

if __name__=="__main__":print(json.dumps(run(),ensure_ascii=False,indent=2))
