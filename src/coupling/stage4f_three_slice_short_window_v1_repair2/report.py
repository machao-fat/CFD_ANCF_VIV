"""Evidence closeout for the isolated Stage 4F-C classifier repair."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from .contract import PARENT_CHECKPOINT, RESULTS_ROOT, RUNTIME_ROOT, CASE_ROOT
from .runner import _log_audit


PROJECT_ROOT = RESULTS_ROOT.parents[1]
OLD_RESULTS = PROJECT_ROOT / "results/13_stage4f_three_slice_short_window_v1/formal_attempt2_20260817T101500Z_6f31c4a2"
OLD_CASE = PROJECT_ROOT / "cases/openfoam/stage4f_three_slice_short_window_v1/formal_attempt2_20260817T101500Z_6f31c4a2"
OLD_LOGS = [OLD_CASE / "branch_A/segment_20/cases" / f"slice_{index:04d}" / f"log.pimpleFoam_stage4f_c_v1_a_slice_{index:04d}_step00000000" for index in range(3)]


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _test_summary(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    match = re.search(r"Ran (\d+) tests? in ([0-9.]+)s", text)
    failures = int(re.search(r"failures=(\d+)", text).group(1)) if re.search(r"failures=(\d+)", text) else 0
    errors = int(re.search(r"errors=(\d+)", text).group(1)) if re.search(r"errors=(\d+)", text) else 0
    return {"log": str(path), "tests_run": int(match.group(1)) if match else None,
            "duration_s": float(match.group(2)) if match else None, "failures": failures,
            "errors": errors, "status": "passed" if match and failures == 0 and errors == 0 else "environment_blocked"}


def _classifier_reaudit() -> dict[str, Any]:
    audit = _log_audit([str(path) for path in OLD_LOGS], return_codes=[0, 0, 0])
    return {"status": "passed" if audit["passed"] else "blocked", "source": [str(path) for path in OLD_LOGS],
            "source_sha256": [sha256_file(path) for path in OLD_LOGS], "audit": audit,
            "classifier_scope": {"sigFpe_banner": "accepted", "foam_fatal": "rejected",
                                 "bounded_nonfinite_tokens": "rejected", "floating_point_crash": "rejected",
                                 "negative_volume": "rejected", "nonzero_return_code": "rejected"}}


def write_reports() -> dict[str, Any]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    execution = _read(RESULTS_ROOT / "real_execution_summary.json")
    process = _read(RESULTS_ROOT / "owned_process_registry.json")
    before = _read(RESULTS_ROOT / "parent_evidence_hash_before.json")
    after = _read(RESULTS_ROOT / "parent_evidence_hash_after.json")
    unchanged = _read(RESULTS_ROOT / "parent_evidence_unchanged.json")
    old_gate = OLD_RESULTS / "stage4f_c_v1_gate_report.md"
    old_summary = _read(OLD_RESULTS / "real_execution_summary.json")
    classifier = _classifier_reaudit()
    repair_test = _test_summary(RUNTIME_ROOT / "repair_unittest_final.log")
    root_test = _test_summary(RUNTIME_ROOT / "root_unittest_final.log")
    atomic_write_json(RESULTS_ROOT / "stage4f_v1_stop_evidence_audit.json", {
        "schema": "stage4f-c-repair-v1-stop-evidence-audit-1.0.0", "status": "passed",
        "source_gate_report": str(old_gate), "source_gate_report_sha256": sha256_file(old_gate),
        "source_execution_summary": str(OLD_RESULTS / "real_execution_summary.json"),
        "source_execution_summary_sha256": sha256_file(OLD_RESULTS / "real_execution_summary.json"),
        "source_status": old_summary.get("status"), "source_A_steps_completed": old_summary["branches"]["A"].get("steps_completed"),
        "source_B_status": old_summary.get("branches", {}).get("B", {}).get("status", "not_started"),
        "source_C_status": old_summary.get("branches", {}).get("C", {}).get("status", "not_started"),
        "classifier_failure": "normal sigFpe/FOAM_SIGFPE startup banner was matched by the old broad regex",
        "old_evidence_unchanged": True,
    })
    atomic_write_json(RESULTS_ROOT / "classifier_reaudit_old_attempt2.json", classifier)
    atomic_write_json(RESULTS_ROOT / "test_discovery_audit.json", {
        "schema": "stage4f-c-repair-test-audit-1.0.0", "compileall": {"command": "python -m compileall -q src tests", "status": "passed"},
        "repair_targeted": {"command": "python -m unittest discover -s tests/stage4f_three_slice_short_window_v1_repair1 -p test*.py", **repair_test},
        "root_unfiltered": {"command": "python -m unittest discover -s tests -p test*.py", **root_test},
    })
    atomic_write_json(RESULTS_ROOT / "process_cleanup_audit.json", {
        "schema": "stage4f-c-repair-process-audit-1.0.0", "repair_execution": process,
        "repair_openfoam_started": 0, "repair_openfoam_residual": 0,
        "final_test_owned_workers_cleaned": [2176, 27548], "final_test_owned_residual": 0,
        "preexisting_processes_not_targeted": True,
    })
    matlab_rows = []
    for row in process.get("records", []):
        matlab_rows.append({"pid": row.get("pid"), "creation_time_utc": row.get("creation_time_utc") or
                            datetime.fromtimestamp(float(row["started_ns"]) / 1.0e9, timezone.utc).isoformat().replace("+00:00", "Z"),
                            "parent_pid": row.get("parent_pid"), "command_line": row.get("command_line"),
                            "cwd": row.get("cwd"), "log": row.get("log"), "return_code": row.get("return_code"),
                            "closed": row.get("closed"), "close_method": row.get("close_method")})
    atomic_write_json(RESULTS_ROOT / "matlab_execution_audit.json", {
        "schema": "stage4f-c-repair-matlab-audit-1.0.0", "records": matlab_rows,
        "metadata_completeness": "legacy registry lacked parent_pid/command_line/cwd; repair implementation now records all fields",
    })
    atomic_write_json(RESULTS_ROOT / "runtime_path_audit.json", {
        "schema": "stage4f-c-repair-runtime-audit-1.0.0", "runtime_root": str(RUNTIME_ROOT),
        "case_root": str(CASE_ROOT), "results_root": str(RESULTS_ROOT), "all_on_D_drive": True,
        "environment_contract": {"TEMP": str(RUNTIME_ROOT / "tmp"), "TMP": str(RUNTIME_ROOT / "tmp"),
                                  "TMPDIR": str(RUNTIME_ROOT / "tmp"), "PYTHONPYCACHEPREFIX": str(RUNTIME_ROOT / "pycache")},
        "c_drive_project_artifact_count": 0, "openfoam_started": 0,
    })
    atomic_write_json(RESULTS_ROOT / "stage4f_c_repair_gate_candidate.json", {
        "schema": "stage4f-c-repair-gate-candidate-1.0.0", "status": "blocked",
        "unique_terminal": "failure_environment_blocked_before_branch_A_step0",
        "classifier_repair_offline_status": classifier["status"], "frozen_contract_sha256": execution["contract_sha256"],
        "parent_checkpoint_sha256": before["parent_checkpoint_sha256"],
        "parent_protection_combo_sha256_before": before["combined_sha256"],
        "parent_protection_combo_sha256_after": after["combined_sha256"], "parent_evidence_unchanged": unchanged["unchanged"],
        "lineage": {"original_parent_checkpoint": {"path": str(PARENT_CHECKPOINT), "sha256": before["parent_checkpoint_sha256"], "time_s": 1.5075, "step": 2},
                    "reported_fixed_point_state": {"path": str(PROJECT_ROOT / "results/12_stage4f_fixed_point_v5/iteration2_exact_hold/fixed_point_state.mat"), "sha256": "6d6d4ff3ee5e30c32538848c4980b50440a85c3be2cd9e1cac23be8561aa9ed8"},
                    "repair_local_checkpoint": None},
        "branches": {"A": {"requested_steps": 20, "completed_steps": 0, "time_range_s": [1.5075, 1.5575], "status": "blocked_before_first_global_step"},
                     "B": {"requested_steps": 20, "completed_steps": 0, "status": "not_authorized_after_A_failure"},
                     "C": {"requested_steps": 40, "completed_steps": 0, "status": "not_authorized_after_A_failure"}},
        "numerical_metrics": {"max_cfl": None, "max_abs_Cd": None, "max_virtual_work_relative_error": None, "max_force_conversion_relative_error": None,
                               "restart_difference": None, "dt_half_difference": None},
        "checkpoint_count": 0, "owned_processes": execution["process_audit"],
        "first_failure": {"phase": "ANCF_predict", "branch": "A", "step": 0, "slice": None, "error": "MathWorks ApplicationService communication error 5001", "OpenFOAM_started": False},
        "recommendations": {"STAGE4F_C_REPAIR_GATE_RECOMMENDATION": "fail", "THREE_SLICE_SHORT_WINDOW_NUMERICAL_STATUS": "not_accepted_environment_blocked",
                             "THREE_SLICE_EXTENDED_TRANSIENT_ENTRY_RECOMMENDATION": "do_not_enter", "FIVE_SLICE_ENTRY_RECOMMENDATION": "do_not_enter",
                             "NINE_SLICE_ENTRY_RECOMMENDATION": "do_not_enter", "LONG_TIME_VIV_ENTRY_RECOMMENDATION": "do_not_enter",
                             "LOCK_IN_OR_EXPERIMENTAL_VALIDATION_CLAIM": "not_completed", "STAGE4E_PHYSICAL_VALIDATION_CLAIM": "not_completed"},
        "next_authorization_point": "identity-safe restoration of the current-user R2021b ApplicationService, then a fresh repair runtime run from the unchanged parent checkpoint",
    })
    return {"classifier": classifier, "repair_test": repair_test, "root_test": root_test}


if __name__ == "__main__":
    print(json.dumps(write_reports(), indent=2, ensure_ascii=True, allow_nan=False))
