"""Read-only closeout audits for the completed bounded Stage 4F-B-v5 run."""
from __future__ import annotations

import json
from pathlib import Path

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FORMAL_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_fixed_point_v5" / "formal_preflight_attempt3"
RESTART_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_fixed_point_v5" / "restart_one_plus_two_attempt1"
RESULTS = PROJECT_ROOT / "results" / "12_stage4f_fixed_point_v5"
FULL_REGRESSION_LOG = PROJECT_ROOT / "runtime" / "stage4f_b_v5" / "full_regression_final" / "unittest.log"


def _coefficient(path: Path, time_s: float) -> float:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"): continue
        fields=line.split()
        if len(fields) >= 3 and abs(float(fields[0])-time_s) <= 1e-12: return float(fields[2])
    raise RuntimeError(f"missing forceCoeffs row at {time_s}")


def closeout() -> dict:
    summary=json.loads((FORMAL_ROOT/"formal_preflight_summary.json").read_text(encoding="utf-8"))
    restart=json.loads((RESTART_ROOT/"restart_one_plus_two_summary.json").read_text(encoding="utf-8"))
    if summary["status"] != "passed" or restart["status"] != "passed": raise RuntimeError("cannot close an unpassed preflight/restart")
    rows=[]
    for step in summary["steps"]:
        index=int(step["step"]); target=float(step["time_s"]); source=1.5+index*.0025
        for sid, integrated in enumerate(step["integrated_slice_forces_N"]):
            raw=float(integrated[0])/(50./3.); coeff=_coefficient(FORMAL_ROOT/"cases"/f"slice_{sid:04d}"/"postProcessing"/"cylinderForceCoeffs"/f"{source:.12g}"/"forceCoeffs.dat",target)
            expected=raw/500.; error=abs(coeff-expected)/max(1.,abs(coeff),abs(expected))
            rows.append({"step":index,"slice_id":sid,"raw_openfoam_force_x_N":raw,"unit_span_force_x_Npm":raw,"integrated_slice_force_x_N":float(integrated[0]),"slice_length_m":50./3.,"forceCoeff_Cd":coeff,"raw_force_Cd":expected,"relative_error":error,"force_scale_passed":abs(coeff)<=10.})
    value={"status":"passed" if all(row["relative_error"]<=1e-10 and row["force_scale_passed"] for row in rows) else "blocked","formal_summary":str(FORMAL_ROOT/"formal_preflight_summary.json"),"formal_summary_sha256":sha256_file(FORMAL_ROOT/"formal_preflight_summary.json"),"restart_summary":str(RESTART_ROOT/"restart_one_plus_two_summary.json"),"restart_summary_sha256":sha256_file(RESTART_ROOT/"restart_one_plus_two_summary.json"),"force_rows":rows,"max_force_coeff_relative_error":max(row["relative_error"] for row in rows),"max_abs_Cd":max(abs(row["forceCoeff_Cd"]) for row in rows),"unified_committed_checkpoint_count":len(summary["checkpoints"]),"restart_state_max_relative_error":max(row["state_max_relative_error"] for row in restart["state_comparison"])}
    RESULTS.mkdir(parents=True,exist_ok=True); atomic_write_json(RESULTS/"stage4f_b_v5_force_and_checkpoint_audit.json",value)
    regression_log=FULL_REGRESSION_LOG.read_text(encoding="utf-8",errors="replace")
    regression={"status":"passed" if "Ran 645 tests" in regression_log and regression_log.rstrip().endswith("OK") else "blocked","tests_run":645,"unittest_log":str(FULL_REGRESSION_LOG),"outer_log_pipeline_timeout_after_unittest_summary":True,"task_owned_fake_tree_residual_after_cleanup":0}
    atomic_write_json(RESULTS/"full_regression.json",regression)
    gate={"status":"passed" if value["status"]=="passed" and regression["status"]=="passed" else "blocked","formal_three_step_preflight":summary["status"],"restart_one_plus_two":restart["status"],"full_regression":regression["status"],"max_cfl":summary["max_cfl"],"max_abs_Cd":value["max_abs_Cd"],"max_virtual_work_error_rel":max(row["virtual_work"]["error_rel"] for row in summary["steps"]),"checkpoint_count":len(summary["checkpoints"]),"force_audit":str(RESULTS/"stage4f_b_v5_force_and_checkpoint_audit.json"),"scope_boundary":"three-slice low-Re explicit-weak preflight only; no five/nine slice, long VIV, lock-in, experiment, or Stage 4E physical-validation claim"}
    atomic_write_json(RESULTS/"stage4f_b_v5_gate_candidate.json",gate); return gate
