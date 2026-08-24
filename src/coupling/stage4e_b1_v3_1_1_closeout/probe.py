from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from src.coupling.runtime_hygiene import build_task_environment, create_runtime_run, inventory_processes
from src.coupling.stage4e_b1_v3_1_closeout.evidence import (
    EventLog,
    ProcessEvidence,
    canonical_sha256,
    enumerate_matlab_processes,
    file_sha256,
    process_snapshot,
    validate_event_log,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MATLAB_EXE = Path(os.environ.get("CFD_ANCF_MATLAB_EXE", r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")).resolve()
MATLAB_CORE = MATLAB_EXE.parent / "win64" / "MATLAB.exe"
OLD_MATLAB_EXE = Path(r"D:\Matlab\bin\matlab.exe")
SCHEMA = "stage4e-b1-v3.1.1-probe-1.0.0"


def _matlab_path_quote(value: str | Path) -> str:
    return str(Path(value).resolve()).replace("\\", "/").replace("'", "''")


def _matlab_text_quote(value: str) -> str:
    return str(value).replace("\\", "/").replace("'", "''")


def _is_under(path_value: str | Path, parent: Path) -> bool:
    try:
        Path(path_value).resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def _servicehost_classification(*, before: list[dict[str, Any]], runtime: Path, token: str, launcher_pid: int | None = None, records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    owned_descendants = {int(row["pid"]) for row in records or []}
    rows = []
    for item in before:
        name = Path(str(item.get("executable") or item.get("name") or "")).name.lower()
        command = [str(part) for part in item.get("command_line") or []]
        if "mathworksservicehost" not in name:
            continue
        mode = "service" if "service" in [part.lower() for part in command] else "monitor" if "monitor" in [part.lower() for part in command] or "monitor" in name else "other"
        rows.append({
            "pid": item.get("pid"),
            "creation_time": item.get("creation_time"),
            "command_line": command,
            "mode": mode,
            "classification": "preexisting_license_infrastructure" if mode in {"service", "monitor"} and token not in command and not _is_under(str(item.get("cwd") or ""), runtime) and int(item.get("pid") or -1) not in owned_descendants else "preexisting_or_unclassified_servicehost",
            "termination_requested": False,
        })
    return {"rows": rows, "preexisting_infrastructure_count": sum(row["classification"] == "preexisting_license_infrastructure" for row in rows), "owned_client_v1_count": 0, "bulk_name_termination_used": False}


def _payload_expression(*, run_id: str, token: str, payload_path: Path) -> str:
    path = _matlab_path_quote(payload_path)
    return (
        f"probe=struct; probe.schema_version='{_matlab_text_quote(SCHEMA)}'; probe.run_id='{_matlab_text_quote(run_id)}'; "
        f"probe.run_token='{_matlab_text_quote(token)}'; probe.probe_begin=true; probe.version=version; "
        "probe.release=version('-release'); probe.architecture=computer('arch'); "
        "probe.license_test_matlab=license('test','MATLAB'); probe.tempdir=tempdir; "
        "probe.prefdir=prefdir; probe.pwd=pwd; probe.probe_end=true; "
        f"payload=jsonencode(probe); fid=fopen('{path}','w','n','UTF-8'); "
        "assert(fid>0); fprintf(fid,'%s',payload); fclose(fid);"
    )


def _validate_payload(payload_path: Path, *, run: Path, run_id: str, token: str, return_code: int | None) -> dict[str, Any]:
    checks: dict[str, bool] = {
        "payload_exists": payload_path.is_file(),
        "payload_utf8_json": False,
        "schema_version": False,
        "run_id": False,
        "run_token": False,
        "probe_begin": False,
        "probe_end": False,
        "version_9_11_series": False,
        "release_R2021b": False,
        "architecture_win64": False,
        "license_test_one": False,
        "tempdir_under_runtime_tmp": False,
        "prefdir_under_runtime_matlab_pref": False,
        "pwd_under_runtime": False,
        "launcher_return_code_zero": return_code == 0,
    }
    payload: dict[str, Any] | None = None
    error: str | None = None
    if payload_path.is_file():
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            checks["payload_utf8_json"] = isinstance(payload, dict)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            error = f"{type(exc).__name__}: {exc}"
    if payload is not None:
        checks.update({
            "schema_version": payload.get("schema_version") == SCHEMA,
            "run_id": payload.get("run_id") == run_id,
            "run_token": payload.get("run_token") == token,
            "probe_begin": payload.get("probe_begin") is True,
            "probe_end": payload.get("probe_end") is True,
            "version_9_11_series": bool(re.match(r"^9\.11(?:\.|$)", str(payload.get("version", "")))),
            "release_R2021b": payload.get("release") == "R2021b",
            "architecture_win64": payload.get("architecture") == "win64",
            "license_test_one": payload.get("license_test_matlab") == 1,
            "tempdir_under_runtime_tmp": _is_under(payload.get("tempdir", ""), run / "tmp"),
            "prefdir_under_runtime_matlab_pref": _is_under(payload.get("prefdir", ""), run / "matlab_pref"),
            "pwd_under_runtime": _is_under(payload.get("pwd", ""), run),
        })
    return {"payload": payload, "checks": checks, "all_checks_passed": all(checks.values()), "error": error, "payload_sha256": file_sha256(payload_path)}


def run_probe(*, project_root: str | Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(project_root).resolve()
    run = create_runtime_run(root, "stage4e_b1_v3_1_1")
    run_id = run.name
    token = f"r2021b_probe_{run_id}_{uuid.uuid4().hex}"
    internal_log = run / "logs" / "matlab_internal.log"
    console_log = run / "logs" / "launcher_console.log"
    payload_path = run / "responses" / "probe_payload.json"
    event_log = EventLog(run / "logs" / "raw_event_log.jsonl", run_id=run_id, run_token=token)
    evidence = ProcessEvidence(event_log, run_dir=run, run_token=token)
    env = build_task_environment(run, {**os.environ, "CFD_ANCF_MATLAB_EXE": str(MATLAB_EXE)})
    before_inventory = inventory_processes()
    before_matlab = enumerate_matlab_processes()
    identity = {
        "launcher_path": str(MATLAB_EXE), "launcher_sha256": file_sha256(MATLAB_EXE),
        "core_path": str(MATLAB_CORE), "core_sha256": file_sha256(MATLAB_CORE),
        "old_path": str(OLD_MATLAB_EXE), "old_path_exists": OLD_MATLAB_EXE.is_file(),
        "selected_path": str(MATLAB_EXE), "environment_value": env.get("CFD_ANCF_MATLAB_EXE"),
    }
    event_log.append("preflight_completed", purpose="version_license_probe", log_path=internal_log, payload={"preexisting_matlab_count": len(before_matlab), "servicehost_classification": "pending"})
    command = [str(MATLAB_EXE), "-wait", "-logfile", str(internal_log), "-batch", _payload_expression(run_id=run_id, token=token, payload_path=payload_path)]
    result: dict[str, Any] = {
        "schema_version": "stage4e-b1-v3.1.1-r2021b-probe-result-1.0.0", "status": "environment_blocked",
        "run_id": run_id, "run_token": token, "runtime_root": str(run), "matlab_installation_identity": identity,
        "environment": {key: env.get(key) for key in ("CFD_ANCF_MATLAB_EXE", "TEMP", "TMP", "TMPDIR", "PYTHONPYCACHEPREFIX", "PIP_CACHE_DIR", "MPLCONFIGDIR", "MATLAB_PREFDIR")},
        "preexisting_matlab_process_count": len(before_matlab), "preexisting_matlab_processes": before_matlab,
        "command": command, "internal_log_path": str(internal_log), "launcher_console_log_path": str(console_log), "probe_payload_path": str(payload_path),
        "probe_attempts": 1, "return_code": None, "payload_validation": None, "owned_processes_started": [], "owned_processes_closed": [],
        "owned_residual_count": 0, "unrelated_terminated": 0,
    }
    servicehost = _servicehost_classification(before=before_inventory, runtime=run, token=token)
    result["servicehost_classification"] = servicehost
    if before_matlab:
        result["block_reason"] = "preexisting_matlab_processes_blocked"
    elif not MATLAB_EXE.is_file() or not MATLAB_CORE.is_file():
        result["block_reason"] = "r2021b_installation_missing"
    else:
        event_log.append("probe_launch_requested", purpose="version_license_probe", log_path=internal_log, payload={"command": command, "stdout_log": str(console_log)})
        evidence.start()
        process = None
        try:
            with console_log.open("w", encoding="utf-8") as console:
                process = subprocess.Popen(command, cwd=str(run), env=env, stdout=console, stderr=subprocess.STDOUT, text=True, shell=False)
                root_row = evidence.register_pid(process.pid, purpose="matlab_probe_launcher", log_path=internal_log)
                result["owned_processes_started"] = [root_row] if root_row else []
                event_log.append("probe_process_started", process=root_row, purpose="matlab_probe_launcher", log_path=internal_log, payload={"command": command, "stdout_log": str(console_log)})
                try:
                    result["return_code"] = process.wait(timeout=300.0)
                except subprocess.TimeoutExpired:
                    result["block_reason"] = "matlab_version_license_probe_timeout"
                    event_log.append("probe_timeout", process=root_row, purpose="matlab_probe_launcher", log_path=internal_log, cleanup_action="deferred_to_tree_cleanup", payload={"timeout_s": 300.0})
                else:
                    event_log.append("probe_process_exited", process=root_row, purpose="matlab_probe_launcher", log_path=internal_log, exit_code=result["return_code"], payload={"payload_exists": payload_path.is_file()})
                    result["payload_validation"] = _validate_payload(payload_path, run=run, run_id=run_id, token=token, return_code=result["return_code"])
                    if result["payload_validation"]["all_checks_passed"]:
                        result["status"] = "passed"
                        result["block_reason"] = None
                    else:
                        result["block_reason"] = "structured_probe_payload_checks_failed"
        except OSError as exc:
            result["block_reason"] = "matlab_version_license_probe_launch_failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            evidence.stop()
            result["owned_processes_closed"] = evidence.cleanup(timeout_s=15.0)
            result["owned_residual_count"] = sum(1 for row in evidence.snapshot_records() if row.get("pid") and process_snapshot(int(row["pid"]), purpose="residual") is not None)
    result["event_log_path"] = str(event_log.path)
    result["event_log_sha256"] = event_log.sha256()
    result["event_log_audit"] = validate_event_log(event_log.path)
    result["owned_process_tree_records"] = evidence.snapshot_records()
    result["process_inventory_before_count"] = len(before_inventory)
    result["process_inventory_after_count"] = len(inventory_processes())
    result["nonfatal_post_payload_shutdown_warning"] = bool(result.get("status") == "passed" and result.get("owned_residual_count") == 0 and result.get("return_code") == 0 and (result.get("payload_validation") or {}).get("checks", {}).get("probe_end"))
    (run / "process_registry" / "probe_summary.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_probe(), ensure_ascii=False, indent=2))
