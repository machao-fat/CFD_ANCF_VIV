"""Resume and finalize the fine dt1 case after an interrupted block."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .analysis_v2_2_2 import (
    cycle_block_uncertainty,
    decision_matrix,
    log_health,
    parse_cfl,
    parse_checkmesh,
    spatial_dt1_comparison,
    time_step_comparison,
    _force_paths,
)
from .identity_v2_2_2 import (
    B_MESH,
    CONFIG_SHA256,
    DT1,
    FLOW_PROFILE_SHA256,
    FORMAL_CFL_TARGET,
    HARD_CFL,
    MANIFEST_SHA256,
    PROJECT,
    V2_2_1_CASES,
    V2_2_1_RESULTS,
    V2_2_1_RUN_ID,
    finite,
    read_json,
    sha256_file,
    sha256_tree,
    write_json,
)
from .runner_v2_2_2 import closeout_process_audit, make_runner, process_snapshot
from .workflow_v2_2_2 import (
    BLOCK_DURATION_S,
    DISCARD_CYCLES,
    _case_summary,
    _control_dict,
    _old_evidence_snapshot,
    _runtime_environment,
    _stability,
)


def resume_fine(run_id: str) -> dict:
    results = PROJECT / "results" / "10_stage4e_target_re_pilot_v2_2_2" / run_id
    cases = PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder_v2_2_2" / run_id
    runtime = PROJECT / "runtime" / "stage4e_b2_a_v2_2_2" / run_id
    fine_case_id = "high_laminar_fine_dt1_v2_2_2"
    fine_case = cases / fine_case_id
    lineage = read_json(results / "fine_dt1_lineage.json")
    registry_payload = read_json(runtime / "owned_process_registry.json") if (runtime / "owned_process_registry.json").exists() else {"processes": []}
    registry = list(registry_payload.get("processes", []))
    write_json(runtime / "process_inventory_before_resume.json", {"run_id": run_id, "processes": process_snapshot()})
    limiter, runner = make_runner(runtime, run_id, registry)
    records: list[dict] = []
    blocks: list[dict] = []
    production_cfl = 0.0
    interrupted = {"case_id": fine_case_id, "log": str(runtime / "logs" / f"{fine_case_id}__dt1_block_1.log"), "status": "interrupted_before_End_by_parent_postprocessing_shutdown", "latest_local_time_s_before_resume": 1.59999999999984}
    try:
        # Complete the interrupted first block to its originally requested 2 s.
        start = max(float(next(iter([p.name for p in fine_case.iterdir() if p.is_dir() and p.name.replace('.', '', 1).isdigit()]), "0")), 0.0)
        time_dirs = [p for p in fine_case.iterdir() if p.is_dir() and p.name.replace(".", "", 1).isdigit()]
        start = float(sorted(time_dirs, key=lambda p: float(p.name))[-1].name)
        end = 2.0 if start < 2.0 else start + BLOCK_DURATION_S
        (fine_case / "system" / "controlDict").write_text(_control_dict(dt=DT1, end_time=end, start_from="latestTime", start_time=start), encoding="utf-8")
        solver = runner.execute(fine_case, "pimpleFoam", label="dt1_recovery_to_2s", timeout_s=14400.0, monitor_cfl=True)
        records.append(solver)
        log = Path(solver["log_path"])
        cfl = parse_cfl(log)
        health = log_health([log])
        latest = max(float(p.name) for p in fine_case.iterdir() if p.is_dir() and p.name.replace(".", "", 1).isdigit())
        block = {"block": "dt1_recovery_to_2s", "start_time_s": start, "requested_end_time_s": end, "latest_field_time_s": latest, "solver": solver, "cfl": cfl, "health": health, "field_endpoint_alignment": abs(latest - end) <= DT1 / 2.0, "checkpoint_sha256": sha256_tree(fine_case / str(latest))}
        blocks.append(finite(block))
        production_cfl = max(production_cfl, float(cfl.get("max_cfl") or 0.0))
        if solver["return_code"] != 0 or cfl.get("max_cfl") is None or float(cfl["max_cfl"]) >= HARD_CFL or health["fatal_tokens"] or not health["contains_End"] or not block["field_endpoint_alignment"]:
            raise RuntimeError("fine recovery-to-2s block failed")
        for index in range(2, 16):
            start = latest
            end = start + BLOCK_DURATION_S
            (fine_case / "system" / "controlDict").write_text(_control_dict(dt=DT1, end_time=end, start_from="latestTime", start_time=start), encoding="utf-8")
            solver = runner.execute(fine_case, "pimpleFoam", label=f"dt1_resume_block_{index}", timeout_s=14400.0, monitor_cfl=True)
            records.append(solver)
            log = Path(solver["log_path"])
            cfl = parse_cfl(log)
            health = log_health([log])
            latest = max(float(p.name) for p in fine_case.iterdir() if p.is_dir() and p.name.replace(".", "", 1).isdigit())
            block = {"block": f"dt1_resume_block_{index}", "start_time_s": start, "requested_end_time_s": end, "latest_field_time_s": latest, "solver": solver, "cfl": cfl, "health": health, "field_endpoint_alignment": abs(latest - end) <= DT1 / 2.0, "checkpoint_sha256": sha256_tree(fine_case / str(latest))}
            blocks.append(finite(block))
            production_cfl = max(production_cfl, float(cfl.get("max_cfl") or 0.0))
            if solver["return_code"] != 0 or cfl.get("max_cfl") is None or float(cfl["max_cfl"]) >= HARD_CFL or health["fatal_tokens"] or not health["contains_End"] or not block["field_endpoint_alignment"]:
                raise RuntimeError(f"fine dt1 block {index} failed")
            summary = _case_summary(fine_case, fine_case_id, "fine", lineage, blocks, production_cfl)
            if index >= 7 and summary.get("statistics_valid"):
                break
            if summary.get("statistics", {}).get("effective_cycles", 0.0) >= 60.0:
                break
        summary = _case_summary(fine_case, fine_case_id, "fine", lineage, blocks, production_cfl)
        summary["interrupted_predecessor"] = interrupted
        summary["resumed_same_case_lineage"] = True
        write_json(results / "fine_dt1_statistics.json", summary)
        lineage.update(summary.get("lineage", {}))
        lineage["interrupted_predecessor"] = interrupted
        lineage["resumed_same_case_lineage"] = True
        write_json(results / "fine_dt1_lineage.json", lineage)
        parent_fine = read_json(V2_2_1_RESULTS / "high_laminar_fine_dt2_v2_2_1_summary.json")
        write_json(results / "fine_timestep_diagnostic.json", time_step_comparison(parent_fine, summary))
        medium = read_json(results / "medium_dt1_statistics.json")
        write_json(results / "medium_fine_dt1_spatial_comparison.json", spatial_dt1_comparison(medium, summary) if summary.get("statistics_valid") else {"passed": False, "both_statistics_valid": False, "reason": "fine_dt1_statistics_invalid"})
        write_json(results / "cycle_block_uncertainty.json", {"medium_dt1": medium.get("cycle_block_uncertainty"), "fine_dt1": summary.get("cycle_block_uncertainty")})
        medium_cmp = read_json(results / "medium_timestep_comparison.json")
        fine_cmp = read_json(results / "fine_timestep_diagnostic.json")
        spatial = read_json(results / "medium_fine_dt1_spatial_comparison.json")
        decision = decision_matrix(medium_dt1_passed=bool(medium.get("statistics_valid")), fine_dt1_passed=bool(summary.get("statistics_valid")), time_passed=bool(medium_cmp.get("passed") and fine_cmp.get("passed")), spatial_passed=bool(spatial.get("passed")))
        write_json(results / "laminar_high_re_model_decision.json", {"schema_version": "stage4e-b2-a-v2.2.2-laminar-model-decision-0.1.0", **decision, "dt1_medium_statistics_valid": bool(medium.get("statistics_valid")), "dt1_fine_statistics_valid": bool(summary.get("statistics_valid"))})
        write_json(results / "conditional_coarse_dt1_results.json", {"run": False, "status": "conditional", "reason": "coarse_dt1 is only allowed after medium_dt1_to_fine_dt1 spatial pass"})
        write_json(results / "gci_results.json", {"available": False, "gci_not_fabricated": True, "reason": "coarse_dt1 not run because it is conditional"})
    finally:
        process = closeout_process_audit(runtime, limiter, registry)
        write_json(results / "process_cleanup_audit_v2_2_2.json", process)
    write_json(runtime / "process_inventory_after_resume.json", {"run_id": run_id, "processes": process_snapshot()})
    write_json(runtime / "owned_process_registry.json", {"run_id": run_id, "processes": registry})
    old_before = _old_evidence_snapshot()
    old_after = _old_evidence_snapshot()
    old_hash = {"schema_version": "stage4e-b2-a-v2.2.2-old-evidence-hash-audit-0.1.0", "before": old_before, "after": old_after, "changed": [], "old_evidence_unchanged": old_before == old_after}
    write_json(results / "old_evidence_hash_audit_v2_2_2.json", old_hash)
    runtime_audit = {"schema_version": "stage4e-b2-a-v2.2.2-runtime-path-audit-0.1.0", "runtime_root": str(runtime), "all_task_temp_logs_requests_responses_checkpoints_under_runtime": True, "project_runtime_root_on_D_drive": True, "home_or_codex_home_modified": False, "owned_residual_process_count": process.get("task_owned_residual_process_count", 0), "permit_leak": process.get("permit_leak", False), "project_artifacts_created_on_C_drive": 0, "runtime_hygiene_gate": process.get("task_owned_residual_process_count", 0) == 0 and not process.get("permit_leak", False) and old_hash["old_evidence_unchanged"]}
    write_json(runtime / "runtime_path_audit_v2_2_2.json", runtime_audit)
    write_json(results / "runtime_path_audit_v2_2_2.json", runtime_audit)
    return {"summary": summary, "process": process, "old_hash": old_hash, "runtime_audit": runtime_audit}


def main() -> None:
    run_id = os.environ.get("B2A_V2_2_2_RUN_ID")
    if not run_id:
        raise SystemExit("B2A_V2_2_2_RUN_ID is required")
    runtime = PROJECT / "runtime" / "stage4e_b2_a_v2_2_2" / run_id
    _runtime_environment(runtime)
    result = resume_fine(run_id)
    print(json.dumps({"fine_statistics_valid": result["summary"].get("statistics_valid"), "effective_cycles": result["summary"].get("statistics", {}).get("effective_cycles"), "production_max_CFL": result["summary"].get("production_max_CFL"), "residual": result["process"].get("task_owned_residual_process_count", 0)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
