"""Real 1+2 restart identity and bounded seven-step extension runner."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Sequence

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from ..stage4f_c_predictor_consistent_strong_v2.contract import (
    ALPHA, CONSECUTIVE_CONVERGED_ITERATIONS, FORCE_RESIDUAL_ABSOLUTE_MAX_N,
    FORCE_RESIDUAL_RELATIVE_MAX, FORCE_RESIDUAL_RELATIVE_SCALE_N, MAX_ABS_CD,
    MAX_ITERATIONS,
)
from ..stage4f_c_predictor_consistent_strong_v2.iteration_engine import CandidateIterationEngine
from ..stage4f_c_predictor_consistent_strong_v2.real_runner import (
    _collect_processes, _force, _residual, _safety_failure,
)
from ..stage4f_c_restart_identity_v1.compare import RestartIdentityTolerances, compare_checkpoint_files
from .contract import DT_S, END_TIME_S, START_TIME_S, build_contract, validate_contract

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ORIGINAL_PARENT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_fixed_point_v5" / "formal_preflight_attempt3" / "checkpoints" / "checkpoint_step00000002_d4def62051c1.json"
BASELINE_SUMMARY = PROJECT_ROOT / "results" / "15_stage4f_c_predictor_consistent_strong_v2_attempt2" / "real_execution_summary.json"
DEFAULT_CASE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_c_restart_extended_v1_attempt1"
DEFAULT_RESULT_ROOT = PROJECT_ROOT / "results" / "16_stage4f_c_restart_extended_v1_attempt1"


def _relax(old, observed):
    return [[(1.0-ALPHA)*float(a)+ALPHA*float(b) for a,b in zip(ra,rb)] for ra,rb in zip(old,observed)]


def _run_segment(*, name: str, parent: Path, start_step: int, end_step: int, case_root: Path, result_root: Path) -> dict[str, Any]:
    payload=json.loads(parent.read_text(encoding="utf-8")); previous=_force(payload["previous_slice_forces_N"])
    parent_sha=sha256_file(parent); current_parent=parent; steps=[]; failure=None
    for step in range(start_step,end_step):
        current=START_TIME_S+step*DT_S; target=current+DT_S; relaxed=_force(previous); streak=0
        row={"physical_step":step,"current_time_s":current,"target_time_s":target,"parent_checkpoint":str(current_parent),"parent_checkpoint_sha256":parent_sha,"iterations":[],"status":"running"}; steps.append(row)
        for iteration in range(MAX_ITERATIONS):
            root=case_root/f"step_{step:02d}"/f"iteration_{iteration:02d}"; engine=None
            try:
                engine=CandidateIterationEngine({"branch":name,"dt_s":DT_S,"physical_step":step,"current_time_s":current,"target_time_s":target,"case_root":str(root),"source_checkpoint":str(current_parent)})
                evidence=dict(engine.run_trial(previous_slice_forces_N=relaxed)); observed=_force(evidence["observed_slice_forces_N"])
                absolute,relative=_residual(observed,relaxed); safety=_safety_failure(evidence)
                residual_ok=absolute<=FORCE_RESIDUAL_ABSOLUTE_MAX_N and relative<=FORCE_RESIDUAL_RELATIVE_MAX
                streak=streak+1 if residual_ok else 0; final=streak>=CONSECUTIVE_CONVERGED_ITERATIONS; cd_ok=float(evidence["max_abs_Cd"])<=MAX_ABS_CD
                row["iterations"].append({"strong_iteration":iteration,"force_residual_absolute_N":absolute,"force_residual_relative":relative,"residual_consecutive_count":streak,"max_abs_Cd":evidence["max_abs_Cd"],"max_cfl":evidence["max_cfl"],"position_difference_over_D":evidence["position_difference_over_D"],"velocity_difference_over_U":evidence["velocity_difference_over_U"],"virtual_work_relative_error":evidence["virtual_work_relative_error"],"force_conversion_relative_error":evidence["force_conversion_relative_error"],"safety_failure":safety,"final_candidate":final,"final_Cd_acceptance":cd_ok if final else None})
                atomic_write_json(result_root/f"{name}_progress.json",{"steps":steps,"failure":failure})
                if safety:
                    failure={"step":step,"iteration":iteration,"reason":safety}; engine.discard_trial(); row["status"]="failed_hard_gate"; break
                if final and cd_ok:
                    checkpoint=engine.promote(); row.update(status="committed",selected_iteration=iteration,checkpoint=str(checkpoint),checkpoint_sha256=sha256_file(checkpoint)); current_parent=Path(checkpoint); parent_sha=sha256_file(checkpoint); previous=observed; break
                engine.discard_trial(); relaxed=_relax(relaxed,observed)
            except Exception as exc:
                failure={"step":step,"iteration":iteration,"reason":f"{type(exc).__name__}: {exc}"}; row["status"]="failed_exception"; break
            finally:
                if engine is not None: engine.shutdown()
        if row["status"]=="running": row["status"]="failed_iteration_limit"; failure={"step":step,"iteration":MAX_ITERATIONS-1,"reason":"iteration_limit"}
        if row["status"]!="committed": break
    result={"name":name,"requested_steps":end_step-start_step,"committed_steps":sum(r["status"]=="committed" for r in steps),"steps":steps,"failure":failure,"status":"passed" if len(steps)==end_step-start_step and all(r["status"]=="committed" for r in steps) else "failed","final_checkpoint":str(current_parent),"final_checkpoint_sha256":parent_sha,"processes":_collect_processes(case_root)}
    atomic_write_json(result_root/f"{name}_summary.json",result); return result


def run(*, case_root: Path, result_root: Path) -> dict[str, Any]:
    case_root,result_root=case_root.resolve(),result_root.resolve()
    if case_root.exists() or (result_root.exists() and any(result_root.iterdir())): raise FileExistsError("restart/extension roots must be new")
    result_root.mkdir(parents=True); original_sha=sha256_file(ORIGINAL_PARENT); contract=build_contract(original_sha); validate_contract(contract); atomic_write_json(result_root/"restart_extended_contract.json",contract)
    baseline=json.loads(BASELINE_SUMMARY.read_text(encoding="utf-8")); baseline_checkpoints=[Path(row["checkpoint"]) for row in baseline["steps"]]
    first=_run_segment(name="first_leg",parent=ORIGINAL_PARENT,start_step=0,end_step=1,case_root=case_root/"first_leg",result_root=result_root)
    if first["status"]!="passed" or first["processes"]["residual"]!=0: return _finish(result_root,contract,first,None,None,[],"first_leg_failed")
    restart_parent=Path(first["final_checkpoint"])
    second=_run_segment(name="restart_leg",parent=restart_parent,start_step=1,end_step=3,case_root=case_root/"restart_leg",result_root=result_root)
    comparisons=[]
    candidate_checkpoints=[Path(first["steps"][0]["checkpoint"])]+[Path(row["checkpoint"]) for row in second["steps"] if row["status"]=="committed"]
    if second["status"]=="passed":
        tolerance=RestartIdentityTolerances(structure_relative_linf=1e-11,previous_force_relative_linf=1e-11,time_absolute_s=1e-12)
        comparisons=[compare_checkpoint_files(ref,cand,tolerances=tolerance) for ref,cand in zip(baseline_checkpoints,candidate_checkpoints)]
    audit_passed=second["status"]=="passed" and len(comparisons)==3 and all(item["passed"] for item in comparisons) and second["processes"]["residual"]==0
    atomic_write_json(result_root/"restart_identity_comparison.json",{"passed":audit_passed,"comparisons":comparisons})
    if not audit_passed: return _finish(result_root,contract,first,second,None,comparisons,"restart_identity_failed")
    extension=_run_segment(name="extension",parent=Path(second["final_checkpoint"]),start_step=3,end_step=10,case_root=case_root/"extension",result_root=result_root)
    return _finish(result_root,contract,first,second,extension,comparisons,"passed" if extension["status"]=="passed" else "extension_failed")


def _finish(result_root,contract,first,second,extension,comparisons,status):
    summary={"schema":"stage4f-c-restart-extended-v1-result-1.0.0","status":status,"contract_sha256":contract["contract_sha256"],"first_leg":first,"restart_leg":second,"restart_identity_passed":bool(comparisons) and all(x["passed"] for x in comparisons),"restart_comparisons":comparisons,"extension":extension,"authorized_end_time_s":END_TIME_S}
    atomic_write_json(result_root/"real_execution_summary.json",summary); return summary


def main(argv: Sequence[str]|None=None)->int:
    p=argparse.ArgumentParser();p.add_argument("--execute",action="store_true");p.add_argument("--case-root",default=str(DEFAULT_CASE_ROOT));p.add_argument("--result-root",default=str(DEFAULT_RESULT_ROOT));a=p.parse_args(argv)
    if not a.execute: print('{"status":"not_executed","reason":"--execute required"}');return 0
    print(json.dumps(run(case_root=Path(a.case_root),result_root=Path(a.result_root)),ensure_ascii=False,indent=2));return 0

if __name__=="__main__": raise SystemExit(main())
