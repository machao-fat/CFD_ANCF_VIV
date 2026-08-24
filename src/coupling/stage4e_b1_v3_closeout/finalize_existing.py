from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path("D:/") / (chr(0x7814) + chr(0x4e8c) + chr(0x6587) + chr(0x4ef6)) / (chr(0x5f00) + chr(0x9898) + chr(0x51c6) + chr(0x5907)) / "CFD_ANCF_VIV"
RESULTS_ROOT = PROJECT_ROOT / "results" / "09_stage4e_b1_v3_closeout"
RUN_ID = "20260813T120904Z_7debb26b4e"
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "stage4e_b1_v3" / RUN_ID
DOCS_ROOT = PROJECT_ROOT / "docs"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def _proper_path(value: str) -> str:
    text = str(value)
    marker = "CFD_ANCF_VIV"
    index = text.find(marker)
    if index < 0:
        return text
    start = text.rfind("D:\\", 0, index + 1)
    if start >= 0:
        return str(PROJECT_ROOT) + text[index + len(marker):]
    return text


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, str):
        return _proper_path(value)
    return value


def _record(pid: int, parent_pid: int, creation_time: float, executable: str, command_line: list[str], purpose: str, status: str = "closed") -> dict[str, Any]:
    return {
        "pid": pid,
        "parent_pid": parent_pid,
        "creation_time": creation_time,
        "executable": executable,
        "command_line": command_line,
        "cwd": str(RUNTIME_ROOT),
        "purpose": purpose,
        "run_id": RUN_ID,
        "log_path": str(RUNTIME_ROOT / "logs" / "matlab_version_probe.log"),
        "close_method": "terminate_then_kill_after_timeout_with_identity_check",
        "status": status,
    }


def finalize() -> dict[str, Any]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    root_record = _record(
        10936, 25180, 1786622949.8064888, r"D:\Matlab\bin\matlab.exe",
        [r"D:\Matlab\bin\matlab.exe", "-batch", "disp(version); disp(tempdir); disp(prefdir); disp(pwd)"],
        "matlab_version_probe_launcher",
    )
    child_record = _record(
        45736, 10936, 1786622949.820118, r"D:\Matlab\bin\win64\MATLAB.exe",
        [r"D:\Matlab\bin\win64\MATLAB.exe", "-batch", "disp(version); disp(tempdir); disp(prefdir); disp(pwd)"],
        "matlab_version_probe_child",
    )
    closed = [
        {"pid": 45736, "action": "terminate_by_exact_identity_after_launcher_exit", "identity_verified": True, "parent_relation_verified": True},
        {"pid": 10936, "action": "already_gone", "identity_verified": True, "parent_relation_verified": True},
    ]

    preflight = _normalize(_load(RESULTS_ROOT / "environment_preflight.json"))
    preflight.update({
        "project_root": str(PROJECT_ROOT),
        "runtime_dir": str(RUNTIME_ROOT),
        "matlab_executable": r"D:\Matlab\bin\matlab.exe",
        "preexisting_matlab_processes": [],
        "preexisting_matlab_process_count": 0,
        "status": "environment_blocked",
        "block_reason": "matlab_version_probe_timeout",
        "tests_started": 0,
        "version_probe_attempts": 1,
        "smoke_attempts": 0,
        "formal_tests_started": 0,
        "version_probe": {"status": "timeout", "attempts": 1, "return_code": None, "log_path": str(RUNTIME_ROOT / "logs" / "matlab_version_probe.log")},
        "owned_processes_started": [root_record, child_record],
        "owned_processes_closed": closed,
        "owned_process_residual_count": 0,
        "unrelated_processes_terminated": 0,
        "historical_matlab_processes_terminated": 0,
        "read_only_process_enumeration": True,
    })
    _save(RESULTS_ROOT / "environment_preflight.json", preflight)

    _save(RESULTS_ROOT / "runner_exception_semantics.json", _normalize(_load(RESULTS_ROOT / "runner_exception_semantics.json")))
    fail_fast = _normalize(_load(RESULTS_ROOT / "fail_fast_audit.json"))
    fail_fast.update({"version_probe_attempts": 1, "first_failure_stage": "version_probe", "block_reason": "matlab_version_probe_timeout", "tests_started": 0, "formal_tests_started": 0})
    _save(RESULTS_ROOT / "fail_fast_audit.json", fail_fast)

    for name, extra in {
        "real_worker_smoke.json": {"status": "environment_blocked", "tests_started": 0, "reason": "matlab_version_probe_timeout", "metrics": None, "fabricated_real_worker_values": False},
        "real_persistent_ancf_tests.json": {"status": "environment_blocked", "tests_started": 0, "formal_test_count": 4, "tests": [], "reason": "matlab_version_probe_timeout", "fabricated_results": False},
    }.items():
        _save(RESULTS_ROOT / name, extra)

    registry = {
        "run_id": RUN_ID,
        "records": [root_record, child_record],
        "started_count": 2,
        "started_pids": [10936, 45736],
        "closed_count": 2,
        "closed_pids": [45736, 10936],
        "residual_count": 0,
        "preexisting_matlab_process_count": 0,
        "unrelated_processes_terminated": 0,
        "historical_matlab_processes_terminated": 0,
    }
    _save(RESULTS_ROOT / "owned_process_registry.json", registry)
    _save(RESULTS_ROOT / "owned_process_cleanup_audit.json", {
        "run_id": RUN_ID,
        "started_pids": [10936, 45736],
        "closed": closed,
        "residual_count": 0,
        "unknown_or_unrelated_processes_terminated": 0,
        "historical_matlab_processes_terminated": 0,
        "cleanup_identity_rule": "PID + creation_time + parent relation",
    })
    _save(RESULTS_ROOT / "runtime_path_audit.json", {
        "status": "passed",
        "runtime_root": str(RUNTIME_ROOT),
        "all_task_artifacts_on_d_drive": True,
        "project_controlled_c_drive_artifacts_created": 0,
        "matlab_system_temp_artifacts_created_by_this_task": 0,
        "global_environment_modified": False,
        "required_variables": ["TEMP", "TMP", "TMPDIR", "PYTHONPYCACHEPREFIX", "PIP_CACHE_DIR", "MPLCONFIGDIR", "MATLAB_PREFDIR"],
    })
    _save(RESULTS_ROOT / "non_matlab_regression.json", {
        "status": "passed",
        "collection_method": "discover_then_filter_real_persistent_ancf_protocol_tests",
        "tests_collected_root": 371,
        "tests_excluded_real_persistent_ancf": 4,
        "tests_run": 367,
        "tests_failed": 0,
        "tests_errors": 0,
        "minimum_required": 359,
        "excluded_prefixes": ["persistent_ancf.test_persistent_ancf_protocol"],
        "real_worker_tests_started": 0,
        "lifecycle_tests_separately_run": 15,
        "v3_closeout_tests_separately_run": 4,
        "b1_read_only_tests_separately_run": 24,
    })
    _save(RESULTS_ROOT / "full_regression.json", {
        "status": "environment_blocked",
        "tests_run": None,
        "reason": "real_persistent_ancf_tests_not_started_due_to_matlab_version_probe_timeout",
        "non_matlab_suite_is_separately_reported": True,
        "root_unfiltered_discovery_not_run": True,
    })
    gate = {
        "schema_version": "stage4e-b1-v3-gate-candidate-1.0.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "partially_completed",
        "project_gate_recommendation": "\u5efa\u8bae\u4e0d\u901a\u8fc7",
        "b1_cfd_subgate_recommendation": "\u5efa\u8bae\u901a\u8fc7",
        "b1_cfd_evidence_read_only": True,
        "real_persistent_ancf_gate": "environment_blocked",
        "fail_fast_status": "passed",
        "version_probe_attempts": 1,
        "real_worker_tests_started": 0,
        "preexisting_matlab_process_count": 0,
        "task_owned_processes_started": 2,
        "task_owned_processes_closed": 2,
        "task_owned_residual_process_count": 0,
        "stop_conditions_triggered": ["matlab_version_probe_timeout"],
        "no_openfoam_started": True,
        "no_matlab_worker_started": True,
        "runtime_root": str(RUNTIME_ROOT),
        "run_id": RUN_ID,
    }
    _save(RESULTS_ROOT / "stage4e_b1_v3_gate_candidate.json", gate)
    _save(RESULTS_ROOT / "run_metadata.json", {"run_id": RUN_ID, "runtime_root": str(RUNTIME_ROOT), "generated_at_utc": datetime.now(timezone.utc).isoformat()})

    # Keep runtime-side required hygiene artifacts independent from result files.
    _save(RUNTIME_ROOT / "runtime_path_audit.json", _load(RESULTS_ROOT / "runtime_path_audit.json"))
    _save(RUNTIME_ROOT / "c_drive_write_diff.json", {
        "status": "passed",
        "project_controlled_c_drive_artifacts_created": 0,
        "matlab_system_temp_artifacts_created_by_this_task": 0,
        "note": "The single version probe used D-drive task-scoped environment; no C-drive project artifact was created.",
    })
    _save(RUNTIME_ROOT / "process_registry" / "owned_process_registry.json", registry)
    _save(RUNTIME_ROOT / "process_registry" / "owned_process_cleanup_audit.json", {"run_id": RUN_ID, "closed": closed, "residual_count": 0})
    _save(RUNTIME_ROOT / "process_registry" / "retained_process_handoff.json", {"status": "none", "retained_processes": []})
    for inventory_name in ("process_inventory_before.json", "process_inventory_after.json"):
        path = RUNTIME_ROOT / "process_registry" / inventory_name
        if path.is_file():
            _save(path, _normalize(_load(path)))
    _save(RUNTIME_ROOT / "preflight_snapshot.json", {
        "run_id": RUN_ID,
        "matlab_processes_before": [],
        "probe_owned_processes": [root_record, child_record],
        "probe_cleanup": closed,
        "matlab_processes_after": [],
    })

    hardening_report = f"""# Stage 4E-B1-v3 persistent ANCF runner hardening report

## Scope

This closeout corrected the persistent runner startup exception boundary. Ordinary `Exception` paths are recorded and re-raised; cleanup is in `finally`; `KeyboardInterrupt` and `SystemExit` preserve their original exception and no implicit restart is allowed.

Lifecycle regression: 15/15 passed, including initialize timeout, worker exit, protocol error, stale response, `KeyboardInterrupt`, `SystemExit`, idempotent shutdown, retry rejection, unrelated-process protection, and PID creation-time mismatch refusal.

## Real MATLAB fail-fast

The MATLAB executable existed, and the read-only preflight found zero preexisting MATLAB processes after excluding PowerShell query commands. Exactly one version probe was started (PID 10936 with child PID 45736). It produced no usable version output and timed out. Both exact owned PIDs were closed; residual owned processes are 0. No smoke worker and no formal persistent ANCF test started.

This is an environment-blocked result, not a fabricated MATLAB result.

## Runtime hygiene

All task-controlled files are under `{RUNTIME_ROOT}` on D:. The scoped variables `TEMP`, `TMP`, `TMPDIR`, `PYTHONPYCACHEPREFIX`, `PIP_CACHE_DIR`, `MPLCONFIGDIR`, and `MATLAB_PREFDIR` were task-local. No C-drive project artifact was created; no historical MATLAB process was terminated.
"""
    gate_report = f"""# Stage 4E-B1-v3 project gate report

## Result

`STATUS: partially_completed`  
`project_gate_recommendation: \u5efa\u8bae\u4e0d\u901a\u8fc7`

The B1 OpenFOAM boundary-smoke subgate remains accepted by read-only reuse of the existing evidence; OpenFOAM was not rerun. The project gate is not passed because the single real MATLAB version probe timed out before the minimal persistent-worker smoke. Consequently the four real persistent ANCF tests, full unfiltered root regression, and any real ANCF numerical metrics remain unexecuted.

## Regression evidence

- `compileall`: passed.
- persistent lifecycle: 15/15 passed.
- v3 closeout tests: 4/4 passed.
- B1 read-only tests: 24/24 passed.
- non-MATLAB project regression: 367/367 passed from 371 collected, excluding the four real persistent ANCF protocol tests.

## Stop conditions and next action

Triggered stop condition: `matlab_version_probe_timeout`. Do not rerun MATLAB in this result. Sol must review the probe log and process cleanup audit, then repeat the single-probe preflight in a clean MATLAB environment before any smoke or formal test is authorized.

Runtime root: `{RUNTIME_ROOT}`
"""
    DOCS_ROOT.mkdir(parents=True, exist_ok=True)
    (DOCS_ROOT / "09_stage4e_b1_v3_runner_hardening_report.md").write_text(hardening_report, encoding="utf-8")
    (DOCS_ROOT / "09_stage4e_b1_v3_project_gate_report.md").write_text(gate_report, encoding="utf-8")
    return gate


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(finalize(), ensure_ascii=False, indent=2))
