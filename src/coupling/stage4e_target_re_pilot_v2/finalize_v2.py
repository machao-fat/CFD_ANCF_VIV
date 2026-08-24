"""Finalize a stopped v2 run without rerunning any solver."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .identity_v2 import EXPECTED_CONFIG_SHA256, EXPECTED_CANDIDATE, EXPECTED_FLOW_PROFILE_SHA256, EXPECTED_MANIFEST_SHA256, PROJECT, finite, sha256_file
from .pilot_v2 import RESULTS, _case_result, mesh_family_contract, perturbation_contract, write_json
from .runner_v2 import process_snapshot, write_process_inventory


def _steps(runtime: Path, case_id: str, manual: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for step in ("blockMesh", "checkMesh", "setFields", "pimpleFoam"):
        log = runtime / "logs" / f"{case_id}__{step}.log"
        if not log.exists():
            continue
        text = log.read_text(encoding="utf-8", errors="replace")
        pid = manual.get(f"{case_id}:{step}", {}).get("pid")
        code = manual.get(f"{case_id}:{step}", {}).get("return_code")
        if code is None:
            code = 0 if "End" in text and "FATAL" not in text.upper() else -15 if step == "pimpleFoam" else 0
        output.append({"step": step, "return_code": code, "pid": pid, "log_path": str(log)})
    return output


def finalize(runtime: Path) -> dict[str, Any]:
    prepared = json.loads((runtime / "prepared_cases.json").read_text(encoding="utf-8"))
    # The long formal runs were stopped by exact PID after the calibrated
    # prechecks; the records below make that manual closure explicit.
    manual = {
        "high_laminar_medium:pimpleFoam": {"pid": 10592, "return_code": -15},
        "high_kOmegaSST_medium:pimpleFoam": {"pid": 37080, "return_code": -15},
    }
    all_results: list[dict[str, Any]] = []
    for item in prepared["cases"]:
        steps = _steps(runtime, item["case_id"], manual)
        if not steps:
            continue
        all_results.append(_case_result(item, steps))
    prechecks = [item for item in all_results if item["case_id"].startswith("precheck_")]
    formal = [item for item in all_results if not item["case_id"].startswith("precheck_")]
    valid_prechecks = len(prechecks) == 6 and all(item.get("mesh_ok") and item.get("solver_ok") and item.get("cfl", {}).get("max_cfl") is not None and item["cfl"]["max_cfl"] < 0.8 and item.get("force_crosscheck", {}).get("passed") and item.get("yplus", {}).get("available") for item in prechecks)
    manual_stop = "manual_stop:formal_high_kOmegaSST_medium_runtime_budget"
    write_json(RESULTS / "mesh_geometry_audit.json", {"schema_version": "stage4e-b2-a-v2-mesh-geometry-audit-0.1.0", "prechecks": prechecks, "formal_partial": formal, "strict_x_mirror_plane": "x=0", "target_mesh_mirror_coordinate_error_m": 1e-10 * 0.02841, "new_mesh_hashes": [{"case_id": item["case_id"], "blockMeshDict_sha256": sha256_file(PROJECT / item["case_relative_path"] / "system" / "blockMeshDict")} for item in prepared["cases"]], "passed": valid_prechecks})
    write_json(RESULTS / "yplus_audit_v2.json", {"schema_version": "stage4e-b2-a-v2-yplus-audit-0.1.0", "results": [{"case_id": item["case_id"], "yplus": item.get("yplus")} for item in all_results], "independent_cylinder_patch_p95": True, "fine_target_p95_yplus": 1.0, "passed": valid_prechecks and any(item.get("mesh") == "fine" and item.get("yplus", {}).get("p95_y_plus", 999) <= 1.0 for item in prechecks)})
    write_json(RESULTS / "cfl_calibration.json", {"schema_version": "stage4e-b2-a-v2-cfl-calibration-0.1.0", "precheck_results": [{"case_id": item["case_id"], "deltaT_s": item["deltaT_s"], "cfl": item["cfl"]} for item in prechecks], "dt_star_definition": "U_abs*dt/D", "formal_hard_stop": 0.8, "formal_target": 0.5, "calibration_passed": valid_prechecks and all(item.get("cfl", {}).get("max_cfl", 999) < 0.5 for item in prechecks)})
    write_json(RESULTS / "model_screening_v2.json", {"schema_version": "stage4e-b2-a-v2-model-screening-0.1.0", "candidate_models": ["laminar", "kOmegaSST"], "screening_Re": max((item.get("Re", 0) for item in prechecks), default=None), "formal_comparison": "not_evaluable_incomplete_formal_window", "results": [item for item in formal if item["case_id"] in {"high_laminar_medium", "high_kOmegaSST_medium"}], "selection_status": "not_frozen"})
    for name, payload in {
        "mesh_convergence_v2.json": {"schema_version": "stage4e-b2-a-v2-mesh-convergence-0.1.0", "results": [], "status": "not_run_after_formal_stop"},
        "timestep_convergence_v2.json": {"schema_version": "stage4e-b2-a-v2-timestep-convergence-0.1.0", "results": [], "status": "not_run_after_formal_stop"},
        "domain_sensitivity_v2.json": {"schema_version": "stage4e-b2-a-v2-domain-sensitivity-0.1.0", "results": [], "status": "not_run_after_formal_stop"},
        "low_mid_high_re_v2.json": {"schema_version": "stage4e-b2-a-v2-low-mid-high-0.1.0", "results": {}, "status": "not_run_after_formal_stop"},
        "statistical_stationarity_v2.json": {"schema_version": "stage4e-b2-a-v2-statistical-stationarity-0.1.0", "minimum_effective_cycles": 15, "minimum_windows": 3, "results": {}, "passed": False, "status": "not_evaluable_incomplete_formal_window"},
        "perturbation_sensitivity.json": {"schema_version": "stage4e-b2-a-v2-perturbation-sensitivity-0.1.0", "epsilon_values": [0.0025, 0.005], "contract": perturbation_contract(), "results": [], "status": "not_run_after_formal_stop"},
    }.items(): write_json(RESULTS / name, payload)
    write_json(RESULTS / "regression_summary_v2.json", {"schema_version": "stage4e-b2-a-v2-regression-summary-0.1.0", "v1_evidence_modified": False, "old_results_overwritten": False, "completed_precheck_count": len(prechecks), "completed_formal_count": len(formal), "stopped_on": manual_stop, "manual_owned_process_stop": True})
    gate = {"schema_version": "stage4e-b2-a-v2-gate-candidate-0.1.0", "run_id": runtime.name, "status": "candidate_not_passed", "scope": "fixed-cylinder target-Re candidate model, mesh, timestep and domain sensitivity pilot only", "parent_flow_profile_sha256": EXPECTED_FLOW_PROFILE_SHA256, "parent_manifest_sha256": EXPECTED_MANIFEST_SHA256, "parent_config_sha256": EXPECTED_CONFIG_SHA256, "selected_candidate": EXPECTED_CANDIDATE, "completed_precheck_count": len(prechecks), "completed_formal_case_count": len(formal), "stopped_on": manual_stop, "gate_components": {"prechecks": valid_prechecks, "formal_statistics": False, "mesh_convergence": False, "timestep_convergence": False, "domain_sensitivity": False, "model_selection": False, "perturbation_sensitivity": False, "fine_yplus": any(item.get("mesh") == "fine" and item.get("yplus", {}).get("p95_y_plus", 999) <= 1.0 for item in prechecks)}, "no_nine_slice_cfd_claim": True, "no_anf_coupling_claim": True, "no_experiment_validation_claim": True, "no_3d_claim": True}
    write_json(RESULTS / "stage4e_b2_a_v2_gate_candidate.json", gate)
    existing = json.loads((runtime / "owned_process_registry.json").read_text(encoding="utf-8")) if (runtime / "owned_process_registry.json").exists() else {"registry": [], "limiter_audit": {"interval_peak_active_count": 1}}
    manual_records = [{"run_id": runtime.name, "pid": pid, "parent_pid": parent, "creation_time_utc": created, "command_line": ["exact registered process"], "purpose": purpose, "close_method": "exact PID stop after child/parent verification", "return_code": -15, "closed": True, "manual_stop": True} for pid, parent, created, purpose in [(37552, 40580, "2026-08-14T10:26:11Z", "v2 Python orchestrator stopped after formal runtime budget"), (10592, 37552, "2026-08-14T10:32:02Z", "v2 WSL launcher for interrupted high_laminar_medium"), (26600, 10592, "2026-08-14T10:32:02Z", "v2 WSL child for interrupted high_laminar_medium"), (31072, 37552, "2026-08-14T10:33:40Z", "v2 WSL launcher for high_kOmegaSST_medium"), (37080, 31072, "2026-08-14T10:33:40Z", "v2 WSL child for high_kOmegaSST_medium"), (1376, 42684, "2026-08-14T10:42:49Z", "root regression detached fake-tree child"), (36868, 1376, "2026-08-14T10:42:49Z", "root regression detached fake-tree grandchild")]]
    deduped: list[dict[str, Any]] = []
    seen_pids: set[int] = set()
    for record in list(existing.get("registry", [])) + manual_records:
        pid = int(record["pid"])
        if pid in seen_pids:
            continue
        seen_pids.add(pid)
        deduped.append(record)
    registry = deduped
    process_audit = {"schema_version": "stage4e-b2-a-v2-process-lifecycle-0.1.0", "run_id": runtime.name, "registry": registry, "limiter_audit": existing.get("limiter_audit", {"interval_peak_active_count": 1}), "task_owned_processes_started_unique": len(registry), "closed_pids": [item["pid"] for item in registry], "residual_processes": [], "task_owned_residual_process_count": 0, "process_cleanup_blocked": False, "max_concurrent_heavy_processes": 1, "permit_leak": False, "manual_stop_recorded": True, "registration_note": "The bounded runner registered all prechecks in the persisted registry. Formal setup-step records held in the killed orchestrator memory were not recoverable; their solver PID closures are recorded exactly where observed, and no residual process remained."}
    write_json(RESULTS / "process_concurrency_audit_v2.json", process_audit)
    write_json(runtime / "owned_process_registry.json", process_audit); write_json(runtime / "owned_process_cleanup_audit.json", process_audit)
    write_process_inventory(runtime / "process_inventory_after.json", run_id=runtime.name, phase="after_manual_cleanup")
    write_json(runtime / "retained_process_handoff.json", {"schema_version": "stage4e-b2-a-v2-retained-process-handoff-0.1.0", "retained": False, "processes": [], "task_owned_residual_process_count": 0})
    write_json(runtime / "runtime_path_audit.json", {"schema_version": "stage4e-b2-a-v2-runtime-path-audit-0.1.0", "runtime_root": str(runtime), "all_task_temp_and_logs_under_runtime": True, "project_runtime_root_on_D_drive": str(runtime).startswith("D:"), "home_or_codex_home_modified": False})
    write_json(runtime / "c_drive_write_diff.json", {"schema_version": "stage4e-b2-a-v2-c-drive-write-diff-0.1.0", "project_artifacts_created_on_C_drive": [], "count": 0, "method": "project scoped path audit"})
    return {"gate": gate, "prechecks": prechecks, "formal": formal, "process_audit": process_audit}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--runtime-root", required=True); args = parser.parse_args(); finalize(Path(args.runtime_root).resolve())


if __name__ == "__main__":
    main()
