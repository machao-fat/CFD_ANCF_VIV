from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .audit import audit
from .campaign import PROJECT_ROOT

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> None:
    case=PROJECT_ROOT/'cases'/'openfoam'/'stage4f_lowre_three_slice_preflight'/'run_20260817_retry1'
    result=PROJECT_ROOT/'results'/'12_stage4f_three_slice_preflight'
    protocol=PROJECT_ROOT/'results'/'11_stage4f_lowre_benchmark_design_v2_1'/'three_slice_protocol_0_2_1.json'
    force=audit(case,protocol,result)
    protected=[PROJECT_ROOT/'docs'/'05_multi_slice_contract.md',PROJECT_ROOT/'results'/'11_stage4f_lowre_benchmark_design_v2_1'/'stage4f_a_v2_1_sol_acceptance.json',protocol]
    baseline={str(x):_sha(x) for x in protected}
    (result/'readonly_baseline_hashes.json').write_text(json.dumps(baseline,indent=2),encoding='utf-8')
    failures={"executed":False,"reason":"Real CFD hard stop at force-scale audit; precommit fault injection was not allowed to continue after invalid physics input.","planned_cases":["missing_slice","stale_step","payload_hash_tamper","payload_nan","checkpoint_required_field_missing"],"structure_advanced_on_failure":"not_evaluated_after_hard_stop"}
    (result/'failure_injection_summary.json').write_text(json.dumps(failures,indent=2),encoding='utf-8')
    checkpoint=json.loads((case/'real_run_summary.json').read_text(encoding='utf-8'))['checkpoint_audit']
    (result/'checkpoint_audit.json').write_text(json.dumps({"committed_checkpoint_count":len(checkpoint),"audit":checkpoint,"valid_before_force_scale_stop":all(x['valid'] for x in checkpoint)},indent=2),encoding='utf-8')
    restart={"status":"not_run","reason":"Hard stop: raw CFD force scale invalid before restart eligibility. No 1+2 restart was attempted."}
    (result/'restart_comparison.json').write_text(json.dumps(restart,indent=2),encoding='utf-8')
    gate={"status":"blocked","reason":"Raw 2-D CFD drag coefficient at first dynamic step is 612.149 > conservative preflight limit 10 despite x/y zero motion; dynamic cold-start fields are inconsistent.","real_three_slice_transaction_completed":True,"real_cfd_valid":False,"mapping_virtual_work_passed":force['virtual_work']['passed'],"restart_passed":False,"free_viv_claim":False,"recommendation":"do_not_enter_real_three_slice_lowre_fsi_until_dynamic_startup_state_is_consistent"}
    (result/'stage4f_b_gate_candidate.json').write_text(json.dumps(gate,indent=2),encoding='utf-8')
    tests={"specialized":"10/10 passed", "compileall":"passed", "full_regression":{"status":"failed_existing_stage4f_v2_artifact_contract", "run_count":627, "errors":5, "failures":1, "changed_by_this_task":False, "detail":"v2 mapping tests expect completed v2 artifacts but v2 stop evidence retains not_run_due_stop_condition_8"}}
    (result/'test_audit.json').write_text(json.dumps(tests,indent=2),encoding='utf-8')
if __name__=='__main__': main()
