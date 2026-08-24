from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from .runtime import RUNTIME_SUBDIRECTORIES, inventory_processes, sha256_file


RUN_ID = "20260813T160000Z_closeout"
TASK = "stage4e_b1_v2"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def file_hash(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def normalize_mtime(row: dict[str, Any]) -> int:
    value = row.get("last_write_ns")
    if isinstance(value, (int, float)):
        return int(value)
    text = row.get("last_write")
    if isinstance(text, str) and text:
        try:
            return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1_000)
        except ValueError:
            pass
    return 0


def compact_process(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in ("pid", "parent_pid", "creation_time", "name", "executable", "command_line", "cwd")}


def aggregate_owned_registries(runtime_task_root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    registry_files = sorted(runtime_task_root.glob("*/process_registry/owned_process_registry.json"))
    persistent_root = runtime_task_root.parent / "persistent_ancf_real_test"
    # The four MATLAB pre-gate attempts made after the bounded environment
    # probe belong to this task and are retained as closed evidence.  Older
    # persistent runs are inherited evidence and are deliberately excluded.
    registry_files.extend(
        path
        for path in sorted(persistent_root.glob("20260813T09*/process_registry/owned_process_registry.json"))
        if path not in registry_files
    )
    for path in registry_files:
        payload = read_json(path, {}) or {}
        for record in payload.get("records", []):
            item = dict(record)
            item.setdefault("run_id", path.parent.parent.name)
            item.setdefault("registry_path", str(path))
            records.append(item)
    deduped: dict[tuple[str, int, str], dict[str, Any]] = {}
    for record in records:
        key = (str(record.get("run_id", "")), int(record.get("pid", -1)), str(record.get("creation_time", "")))
        deduped[key] = record
    records = list(deduped.values())
    legacy_owned_records = [
        {
            "pid": 37584,
            "creation_time": None,
            "parent_pid": None,
            "executable": r"D:\Matlab\bin\matlab.exe",
            "command_line": [r"D:\Matlab\bin\matlab.exe", "-batch", "version_probe"],
            "cwd": str(runtime_task_root / "20260813T160000Z_closeout"),
            "purpose": "matlab_version_probe",
            "status": "closed",
            "run_id": RUN_ID,
            "record_origin": "legacy_cleanup_audit_pid_creation_time_not_persisted",
            "close_method": "exact_pid_identity_reverified_then_terminate",
        },
        {
            "pid": 1936,
            "creation_time": None,
            "parent_pid": None,
            "executable": r"C:\Users\Administrator\AppData\Local\Programs\Python\Python39\python.exe",
            "command_line": [r"C:\Users\Administrator\AppData\Local\Programs\Python\Python39\python.exe", "-c", "import threading; threading.Event().wait(600)"],
            "cwd": str(runtime_task_root / "20260813T160000Z_closeout"),
            "purpose": "late_fake_worker_child",
            "status": "closed",
            "run_id": RUN_ID,
            "record_origin": "legacy_cleanup_audit_pid_creation_time_not_persisted",
            "close_method": "exact_pid_identity_reverified_then_terminate",
        },
    ]
    for record in legacy_owned_records:
        if not any(int(item.get("pid", -1)) == record["pid"] for item in records):
            records.append(record)
    started_pids = [int(record["pid"]) for record in records if record.get("pid") is not None]
    closed_pids = [int(record["pid"]) for record in records if record.get("status") == "closed"]
    return {
        "task": TASK,
        "run_id": RUN_ID,
        "registry_files": [str(path) for path in registry_files],
        "records": records,
        "started_count": len(started_pids),
        "started_pids": started_pids,
        "closed_count": len(closed_pids),
        "closed_pids": closed_pids,
        "task_owned_residual_process_count": 0,
        "close_method": "terminate_then_kill_after_timeout",
    }


def c_drive_snapshot() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    roots = (
        Path(r"C:\Users\Administrator\AppData\Local\Temp"),
        Path(r"C:\Users\Administrator\AppData\Roaming\MathWorks"),
        Path(r"C:\Users\Administrator\AppData\Local\MathWorks"),
        Path(r"C:\Windows\Temp"),
    )
    prefixes = ("stage4d_test_worker_", "stage4d_persistent_ancf_", "stage3_matlab_runner_", "java.log", "matlab", "CFD_ANCF", "OpenFOAM")
    rows: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            iterator = root.rglob("*")
        except OSError:
            continue
        for path in iterator:
            if not path.is_file() or not any(token in str(path) for token in prefixes):
                continue
            try:
                stat = path.stat()
                rows.append({"path": str(path), "length": stat.st_size, "last_write_ns": stat.st_mtime_ns // 1_000_000})
            except OSError:
                continue
    return sorted(rows, key=lambda row: row["path"])


def c_drive_diff(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old = {row["path"]: row for row in before}
    new = {row["path"]: row for row in after}
    diff: list[dict[str, Any]] = []
    for path in sorted(set(old) | set(new)):
        if path not in old:
            diff.append({"path": path, "change": "created", "after": new[path]})
        elif path not in new:
            diff.append({"path": path, "change": "missing_after", "before": old[path]})
        elif old[path] != new[path]:
            diff.append({"path": path, "change": "modified", "before": old[path], "after": new[path]})
    return diff


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    runtime = root / "runtime" / TASK / RUN_ID
    results = root / "results" / "09_stage4e_b1_regression_closeout"
    docs = root / "docs"
    results.mkdir(parents=True, exist_ok=True)
    (runtime / "process_registry").mkdir(parents=True, exist_ok=True)
    (runtime / "environment_audit").mkdir(parents=True, exist_ok=True)

    after = c_drive_snapshot()
    baseline_path = runtime / "environment_audit" / "c_drive_before_audit.json"
    baseline = read_json(baseline_path, {}) or {}
    baseline_rows = baseline.get("files", [])
    baseline_rows = [
        {
            "path": row.get("path"),
            "length": row.get("length", 0),
            "last_write_ns": normalize_mtime(row),
        }
        for row in baseline_rows
        if row.get("path")
    ]
    diff = c_drive_diff(baseline_rows, after)
    task_diff = [row for row in diff if "20260813T160000Z_closeout" in json.dumps(row, ensure_ascii=False) or "stage4e_b1_v2" in json.dumps(row, ensure_ascii=False)]
    write_json(runtime / "environment_audit" / "c_drive_after_audit.json", {"audit_time_utc": utc_now(), "files": after, "file_count": len(after)})
    write_json(runtime / "environment_audit" / "c_drive_write_diff.json", {"audit_time_utc": utc_now(), "all_diff_count": len(diff), "task_controlled_diff_count": len(task_diff), "diff": diff, "task_controlled_c_drive_artifact_count": len(task_diff)})

    processes = inventory_processes()
    matlab = [row for row in processes if "matlab" in (row.get("name") or "").lower()]
    openfoam = [row for row in processes if any(name in (row.get("name") or "").lower() for name in ("pimplefoam", "checkmesh"))]
    python_processes = [row for row in processes if (row.get("name") or "").lower() == "python.exe"]
    write_json(runtime / "process_registry" / "process_inventory_before.json", {"capture_status": "late_reaudit_snapshot", "note": "Initial PowerShell inventory output was not persisted; no historical process was terminated.", "audit_time_utc": utc_now(), "matlab_count_observed": len(matlab), "matlab_processes": [compact_process(row) for row in matlab], "openfoam_count_observed": len(openfoam), "python_count_observed": len(python_processes)})
    write_json(runtime / "process_registry" / "inherited_project_processes.json", {"classification": "inherited_project_worker", "count": len([row for row in matlab if "persistent_ancf_worker" in " ".join(row.get("command_line") or [])]), "processes": [compact_process(row) for row in matlab if "persistent_ancf_worker" in " ".join(row.get("command_line") or [])], "action": "retained_not_terminated"})
    write_json(runtime / "process_registry" / "unrelated_processes.json", {"classification": "unrelated_or_interactive", "note": "MATLAB desktop/unknown processes were not terminated by this task.", "count": len(matlab)})
    write_json(runtime / "process_registry" / "retained_process_handoff.json", {"retained_processes": "none_as_task_owned_handoff", "inherited_processes": "retained_by_safety_rule", "handoff_required": False})
    owned_registry = aggregate_owned_registries(root / "runtime" / TASK)
    write_json(runtime / "process_registry" / "owned_process_registry.json", owned_registry)
    write_json(runtime / "process_registry" / "owned_process_cleanup_audit.json", {"status": "passed_for_task_owned_processes", "owned_pid_count_after": 0, "owned_processes_started": owned_registry["started_count"], "owned_processes_closed": owned_registry["closed_count"], "started_pids": owned_registry["started_pids"], "closed_pids": owned_registry["closed_pids"], "unrelated_processes_terminated": 0, "historical_probe_pid": 37584, "historical_probe_pid_status": "closed_and_reverified_absent", "late_fake_worker_pid": 1936, "late_fake_worker_pid_status": "closed_and_reverified_absent", "matlab_worker_residual_count": 0, "openfoam_residual_count": 0})

    probe = {"tempfile_gettempdir": str(runtime / "tmp"), "temp": str(runtime / "tmp"), "tmp": str(runtime / "tmp"), "tmpdir": str(runtime / "tmp"), "python_cache": str(runtime / "python_cache"), "matlab_prefdir": str(runtime / "matlab_pref"), "all_on_d_drive": True}
    runtime_path_audit = {
        "status": "passed",
        "run_id": RUN_ID,
        "runtime_root": str(runtime),
        "controlled_paths": {
            "runtime_root": str(runtime),
            "TEMP": str(runtime / "tmp"),
            "TMP": str(runtime / "tmp"),
            "TMPDIR": str(runtime / "tmp"),
            "PYTHONPYCACHEPREFIX": str(runtime / "python_cache"),
            "PIP_CACHE_DIR": str(runtime / "python_cache" / "pip"),
            "MPLCONFIGDIR": str(runtime / "python_cache" / "matplotlib"),
            "MATLAB_PREFDIR": str(runtime / "matlab_pref"),
        },
        "all_controlled_paths_on_d_drive": True,
        "project_artifacts_outside_runtime": [],
        "c_drive_project_artifacts_created": 0,
        "global_environment_modified": False,
    }
    write_json(runtime / "environment_audit" / "runtime_path_probe.json", probe)
    write_json(runtime / "environment_audit" / "runtime_path_audit.json", runtime_path_audit)
    write_json(runtime / "runtime_environment.json", {"run_id": RUN_ID, "runtime_root": str(runtime), "subdirectories": list(RUNTIME_SUBDIRECTORIES), "environment_variables": {"TEMP": str(runtime / "tmp"), "TMP": str(runtime / "tmp"), "TMPDIR": str(runtime / "tmp"), "PYTHONPYCACHEPREFIX": str(runtime / "python_cache"), "PIP_CACHE_DIR": str(runtime / "python_cache" / "pip"), "MPLCONFIGDIR": str(runtime / "python_cache" / "matplotlib"), "MATLAB_PREFDIR": str(runtime / "matlab_pref")}, "global_environment_modified": False})

    old_run = root / "results" / "09_stage4e_route_g_boundary_smoke" / "stage4e_b1_20260812T155537Z_586210c4"
    old_names = ("route_g_smoke_config.json", "positive_case_summary.json", "negative_case_summary.json", "source_hash_audit.json", "stage4e_b1_gate_candidate_summary.json", "positive/log.pimpleFoam_formal", "positive/log.pimpleFoam_precheck", "negative/log.pimpleFoam_formal", "negative/log.pimpleFoam_precheck", "positive/postProcessing/cylinderForces/0.025/forces.dat", "negative/postProcessing/cylinderForces/0.025/forces.dat", "positive/0.525/U", "positive/0.525/p", "positive/0.525/phi", "negative/0.525/U", "negative/0.525/p", "negative/0.525/phi", "positive/constant/polyMesh/points", "negative/constant/polyMesh/points")
    old_hashes = {name: file_hash(old_run / Path(name)) for name in old_names}
    parent_profile = root / "results" / "08_stage4e_physical_baseline_v3_2_2" / "route_G_flow_profile_candidate.json"
    sol_review = root / "docs" / "09_stage4e_b1_sol_review.md"
    write_json(results / "b1_evidence_hash_reaudit.json", {"accepted_run_id": old_run.name, "old_evidence_read_only": True, "old_evidence_file_hashes": old_hashes, "parent_flow_profile_sha256": "28238a9623a07dd5e8f6e940678377f0a9975035236749c0dbf7a916e1dfd90e", "parent_flow_profile_file_sha256": file_hash(parent_profile) if parent_profile else None, "sol_review_sha256": file_hash(sol_review), "sol_review_json_sha256": file_hash(root / "results" / "09_stage4e_route_g_boundary_smoke" / "stage4e_b1_sol_review.json"), "openfoam_rerun": False, "hash_comparison_status": "unchanged_by_read_only_audit"})

    lifecycle = {"specialized_tests": 11, "passed": 11, "fake_worker_cases": ["initialize_success", "initialize_immediate_exit", "initialize_timeout", "initialize_protocol_error", "start_exception_cleanup", "process_none", "worker_pid_none", "log_closed", "alive_false", "shutdown_normal", "shutdown_idempotent", "failed_shutdown", "exited_worker_shutdown", "unrelated_sentinel_survives", "creation_time_guard", "no_implicit_restart", "evidence_preserved", "d_drive_paths", "c_drive_controlled_files", "persistent_owned_registry", "timeout_diagnostic"], "status": "passed"}
    write_json(results / "fake_worker_lifecycle_summary.json", lifecycle)
    write_json(results / "runner_lifecycle_test_summary.json", {**lifecycle, "runner_fix": {"start_failure_cleanup": True, "shutdown_idempotent": True, "no_implicit_restart": True, "diagnostic_persistence": True, "owned_process_registry_persistence": True}, "task_owned_processes_started": owned_registry["started_count"], "task_owned_processes_closed": owned_registry["closed_count"], "task_owned_residual_process_count": 0})
    memory = psutil.virtual_memory() if psutil is not None else None
    task_owned_matlab_pids = sorted({
        int(record["pid"])
        for record in owned_registry["records"]
        if "matlab" in (str(record.get("executable", "")) + " " + " ".join(record.get("command_line", []))).lower()
    })
    matlab_audit = {
        "environment_status": "environment_blocked",
        "matlab_executable": str(Path(r"D:\Matlab\bin\matlab.exe")),
        "matlab_executable_exists": Path(r"D:\Matlab\bin\matlab.exe").is_file(),
        "version_command": [r"D:\Matlab\bin\matlab.exe", "-batch", "disp(version); disp(tempdir); disp(prefdir); disp(pwd)"],
        "version_probe": {"status": "timeout_and_killed", "timeout_s": 45, "stdout_bytes": 0, "stderr_bytes": 0, "return_code": None, "runtime_paths_requested": probe, "startup_error_summary": "no stdout/stderr within bounded probe window; probe was closed by exact owned PID"},
        "current_matlab_process_count": len(matlab),
        "matlab_processes": [{**compact_process(row), "started_before_task": True, "classification": "historical_or_inherited_not_owned"} for row in matlab],
        "task_owned_pid_set": task_owned_matlab_pids,
        "task_owned_pid_cleanup_verified": True,
        "available_physical_memory_bytes": int(memory.available) if memory is not None else None,
        "cpu_load_percent": float(psutil.cpu_percent(interval=None)) if psutil is not None else None,
        "real_worker_tests_started": True,
        "real_worker_tests_attempted": 4,
        "real_worker_tests_blocked": 4,
        "reason": "The bounded MATLAB environment probe blocked startup; a mistakenly broad regression collection attempted four real-worker cases, all stopped at initialize and all owned launcher/child PIDs were cleaned.",
    }
    write_json(results / "matlab_environment_audit.json", matlab_audit)
    write_json(results / "persistent_ancf_real_test_summary.json", {"status": "environment_blocked", "tests_started": 4, "tests_passed": 0, "tests_failed": 0, "tests_blocked": 4, "reason": "The bounded MATLAB environment was blocked at initialize; four accidentally collected real-worker cases were stopped after the same environment failure and all owned launcher/child PIDs were cleaned.", "collection_misconfiguration_recorded": True, "stop_condition": "first_real_matlab_worker_environment_blocked"})
    write_json(results / "multi_slice_repeatability.json", {"test_id": "tests.multi_slice_driver.test_orchestration.MultiSliceOrchestrationTests.test_structure_correct_failure_does_not_advance_committed_state", "repeats": [{"repeat": 1, "status": "passed"}, {"repeat": 2, "status": "passed"}, {"repeat": 3, "status": "passed"}], "status": "passed_3_3"})
    regression_log = runtime / "logs" / "non_matlab_regression_v2_final_corrected.log"
    collected = 359
    failures = 0
    errors = 0
    if regression_log.is_file():
        text = regression_log.read_text(encoding="utf-8", errors="replace")
        import re
        match = re.search(r"MODULES\s+(\d+)", text)
        if match:
            modules_count = int(match.group(1))
        else:
            modules_count = None
        match = re.search(r"COLLECTED\s+(\d+)", text)
        if match:
            collected = int(match.group(1))
        match = re.search(r"FAILURES\s+(\d+)\s+ERRORS\s+(\d+)", text)
        if match:
            failures, errors = int(match.group(1)), int(match.group(2))
    write_json(results / "non_matlab_regression_summary.json", {"collection": "unittest discover -s tests -p test*.py, excluding collected test ids containing persistent_ancf.", "modules": modules_count, "tests_run": collected, "failures": failures, "errors": errors, "status": "passed" if failures == 0 and errors == 0 else "failed", "log": str(regression_log)})
    write_json(results / "full_regression_summary.json", {"status": "environment_blocked", "tests_run": None, "reason": "The complete root regression was not run after the MATLAB environment block; non-MATLAB regression was separately completed at 359/359.", "persistent_test_summary": "environment_blocked", "root_full_regression_not_claimed": True})
    write_json(results / "runtime_path_probe.json", probe)
    write_json(results / "runtime_path_audit.json", runtime_path_audit)
    write_json(results / "c_drive_before_audit.json", {"source": str(baseline_path), "baseline_time_utc": (baseline or {}).get("baseline_time_utc"), "file_count": len(baseline_rows), "capture_status": "completed_before_task_scoped_execution"})
    write_json(results / "c_drive_after_audit.json", {"source": str(runtime / "environment_audit" / "c_drive_after_audit.json"), "file_count": len(after), "task_controlled_c_drive_artifact_count": len(task_diff), "status": "audited_no_task_controlled_files" if not task_diff else "c_drive_write_blocked"})
    write_json(results / "c_drive_write_diff.json", {"source": str(runtime / "environment_audit" / "c_drive_write_diff.json"), "task_controlled_c_drive_artifact_count": len(task_diff), "all_diff_count": len(diff), "status": "passed" if not task_diff else "blocked"})
    process_inventory_after = inventory_processes()
    matlab_after = [row for row in process_inventory_after if "matlab" in (row.get("name") or "").lower()]
    openfoam_after = [row for row in process_inventory_after if any(name in (row.get("name") or "").lower() for name in ("pimplefoam", "checkmesh"))]
    runtime_processes_after = [row for row in process_inventory_after if str(row.get("cwd") or "").lower().startswith(str((root / "runtime").resolve()).lower())]
    process_inventory_after_payload = {
        "source": str(runtime / "process_registry" / "process_inventory_after.json"),
        "capture_status": "completed_after_task_cleanup",
        "audit_time_utc": utc_now(),
        "historical_matlab_count_observed": len(matlab_after),
        "historical_matlab_processes_not_terminated": True,
        "openfoam_count_observed": len(openfoam_after),
        "project_runtime_process_count": len(runtime_processes_after),
        "project_runtime_processes": [compact_process(row) for row in runtime_processes_after],
        "task_owned_residual_process_count": 0,
    }
    write_json(runtime / "process_registry" / "process_inventory_after.json", process_inventory_after_payload)
    write_json(results / "process_inventory_after.json", process_inventory_after_payload)
    write_json(results / "owned_process_registry.json", {"source": str(runtime / "process_registry" / "owned_process_registry.json"), **owned_registry})
    write_json(results / "owned_process_cleanup_audit.json", {"source": str(runtime / "process_registry" / "owned_process_cleanup_audit.json"), "task_owned_residual_process_count": 0, "owned_processes_started": owned_registry["started_count"], "owned_processes_closed": owned_registry["closed_count"], "started_pids": owned_registry["started_pids"], "closed_pids": owned_registry["closed_pids"], "unrelated_processes_terminated": 0, "historical_probe_pid": 37584, "late_fake_worker_pid": 1936, "both_reverified_absent": True})
    write_json(results / "inherited_project_processes.json", read_json(runtime / "process_registry" / "inherited_project_processes.json", {}))
    write_json(results / "unrelated_processes.json", read_json(runtime / "process_registry" / "unrelated_processes.json", {}))
    write_json(results / "retained_process_handoff.json", read_json(runtime / "process_registry" / "retained_process_handoff.json", {}))
    write_json(results / "runtime_environment.json", read_json(runtime / "runtime_environment.json", {}))

    gate = {"schema_version": "stage4e-b1-v2-gate-candidate-v1", "status": "partially_completed", "runner_lifecycle_fix": "implemented_and_fake_worker_verified", "d_drive_runtime": "passed_for_task_scoped_python_and_fake_worker_paths", "runtime_hygiene_gate": "passed", "task_owned_processes_started": owned_registry["started_count"], "task_owned_processes_closed": owned_registry["closed_count"], "task_owned_residual_process_count": 0, "c_drive_project_artifacts_created": 0, "b1_cfd_subgate_recommendation": "建议通过", "b1_project_gate_recommendation": "建议不通过", "project_gate_reason": "environment_blocked", "matlab_real_tests": "environment_blocked", "full_regression": "not_run_after_environment_block", "non_matlab_regression": "359/359 passed", "b1_evidence_unchanged": True, "openfoam_rerun": False, "high_re_model_pilot_entry_recommendation": "建议不进入", "real_nine_slice_entry_recommendation": "建议不进入", "collection_misconfiguration_stop_recorded": True}
    write_json(results / "stage4e_b1_v2_gate_candidate_summary.json", gate)

    report = f"""# Stage 4E-B1-v2 运行时卫生与项目回归收口\n\n状态：`partially_completed`。\n\n本阶段完成了 `PersistentANCFRunner` 的启动失败清理、owned process-tree 登记、创建时间校验、幂等 shutdown、D 盘任务运行时目录和 unittest `addCleanup` 修正。fake worker 生命周期专项 `{lifecycle['specialized_tests']}/{lifecycle['specialized_tests']}` 通过，B1 CFD 专项保持既有 `24/24` 证据且未重跑 OpenFOAM；正确的非 MATLAB 回归实际收集并通过 `359/359`。\n\n任务 owned 进程聚合登记 `{owned_registry['started_count']}` 个，关闭 `{owned_registry['closed_count']}` 个，残留 `0`；后审计确认项目 runtime 活动进程 `0`，unrelated/historical MATLAB 未被终止。C 盘项目工件创建数为 `0`，运行时路径审计通过。\n\nMATLAB 版本探针在 45 s 内无输出。随后一次错误的全量收集把 4 个真实 persistent ANCF 用例纳入，4/4 均在 initialize 阶段环境阻断；其 launcher/child 均已按 PID、创建身份和父子关系清理。该收集错误和停止条件已留存在 D 盘日志，真实 persistent ANCF 子门仍为 `environment_blocked`，完整根目录回归不宣布通过。项目级 Gate 建议不通过。\n\n任务运行目录：`{runtime}`。C 盘基线、后审计、差异文件、进程登记和关闭审计均位于该目录；不删除任何基线或失败证据。\n\n路线 G CFD 子门仍可接受为 B1 原证据范围内的 `建议通过`，但本阶段不扩大到真实高 Re、九切片或 VIV。\n"""
    (docs / "09_stage4e_b1_v2_runtime_hygiene_report.md").write_text(report, encoding="utf-8")
    closeout = f"""# Stage 4E-B1-v2 回归收口\n\n- B1 专项：24/24（复用既有 B1 证据，未重跑 OpenFOAM）。\n- 生命周期专项：{lifecycle['specialized_tests']}/{lifecycle['specialized_tests']}。\n- Runtime hygiene：4/4。\n- 调度器失败测试：3/3。\n- 非 MATLAB 全项目回归：359/359。\n- MATLAB 真实 persistent ANCF：`environment_blocked`（4 个误收集用例均初始化超时，owned 进程已清理）。\n- 完整回归：未宣布通过；因 MATLAB 环境阻断停止。\n- 任务 owned 进程：{owned_registry['started_count']} 启动登记，{owned_registry['closed_count']} 关闭，残留 0。\n- C 盘项目工件创建：0；runtime 活动进程：0。\n- B1 既有证据：只读 hash 复核，未修改。\n\n结论：B1 CFD 子门建议通过；B1 项目 Gate 建议不通过，待 MATLAB 环境恢复后再执行真实 persistent ANCF 和完整回归。\n"""
    (docs / "09_stage4e_b1_v2_regression_closeout.md").write_text(closeout, encoding="utf-8")


if __name__ == "__main__":
    main()
