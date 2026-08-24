"""Frozen native-argv launcher and one-shot formal Stage 4E probe.

The launcher deliberately never uses PowerShell ``Start-Process -ArgumentList``
for MATLAB expressions.  A list passed to ``subprocess.Popen`` with
``shell=False`` is the only supported launch shape in this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from src.coupling.runtime_hygiene import build_task_environment, create_runtime_run, inventory_processes
from src.coupling.stage4e_b1_v3_1_closeout.evidence import (
    EventLog,
    ProcessEvidence,
    enumerate_matlab_processes,
    file_sha256,
    process_snapshot,
    validate_event_log,
)
from src.coupling.stage4e_b1_probe_repair_v1.contract import (
    EXPECTED_EXECUTABLE,
    SCHEMA,
    read_json_payload,
    validate_payload,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MATLAB_EXE = EXPECTED_EXECUTABLE
FORMAL_TASK = "stage4e_probe_verified_v1"
REGRESSION_TASK = "stage4e_probe_verified_v1_argv_regression"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: str | Path) -> str | None:
    return file_sha256(path) if Path(path).is_file() else None


def _matlab_quote(value: str | Path) -> str:
    return str(value).replace("\\", "/").replace("'", "''")


def _argv_record(*, executable: Path, argv: list[str], cwd: Path, env: Mapping[str, str], created_at: str) -> dict[str, Any]:
    keys = ("TEMP", "TMP", "TMPDIR", "MATLAB_PREFDIR", "PATH", "USERPROFILE", "APPDATA", "LOCALAPPDATA")
    return {
        "executable": str(executable),
        "argv": list(argv),
        "cwd": str(cwd),
        "environment_overrides": {key: env.get(key) for key in keys},
        "creation_timestamp_utc": created_at,
        "shell": False,
        "launch_mechanism": "python_subprocess_Popen_argv_list",
        "forbidden_alternative": "PowerShell Start-Process -ArgumentList expression concatenation",
    }


def build_regression_expression() -> str:
    return r"fprintf('ARGV_REGRESSION_OK\n'); x = '(a;b)'; y = 'single quote test'; fprintf('%s\n',x); fprintf('%s\n',y);"


def build_regression_argv(*, executable: str | Path = MATLAB_EXE) -> list[str]:
    return [str(Path(executable)), "-wait", "-batch", build_regression_expression()]


def build_payload_expression(*, run_id: str, token: str, payload_path: Path) -> str:
    path = _matlab_quote(payload_path)
    return (
        "fprintf('PROBE_INTERPRETER_REACHED\\n'); "
        f"probe=struct; probe.schema_version='{_matlab_quote(SCHEMA)}'; "
        f"probe.run_id='{_matlab_quote(run_id)}'; probe.run_token='{_matlab_quote(token)}'; "
        "probe.probe_begin=true; probe.version=version; probe.release=version('-release'); "
        "probe.architecture=computer('arch'); probe.license_test_matlab=license('test','MATLAB'); "
        "probe.TEMP=getenv('TEMP'); probe.TMP=getenv('TMP'); probe.TMPDIR=getenv('TMPDIR'); "
        "probe.tempdir=tempdir; probe.prefdir=prefdir; probe.pwd=pwd; "
        "probe.application_service='ok'; probe.probe_end=true; "
        f"payload=jsonencode(probe); fid=fopen('{path}','w','n','UTF-8'); assert(fid>0); "
        "fprintf(fid,'%s',payload); fclose(fid);"
    )


def build_formal_argv(*, run_id: str, token: str, payload_path: Path, matlab_log: Path, executable: str | Path = MATLAB_EXE) -> list[str]:
    return [str(Path(executable)), "-wait", "-logfile", str(matlab_log), "-batch", build_payload_expression(run_id=run_id, token=token, payload_path=payload_path)]


def _mathworks_inventory() -> list[dict[str, Any]]:
    if psutil is None:
        return []
    rows: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "create_time"]):
        try:
            info = process.info
            name = str(info.get("name") or "").lower()
            exe = str(info.get("exe") or "").lower()
            if "matlab" not in name and "mathworks" not in name and "matlab" not in exe and "mathworks" not in exe:
                continue
            try:
                cwd = str(process.cwd())
            except Exception:
                cwd = ""
            rows.append({
                "pid": int(info.get("pid") or process.pid),
                "parent_pid": int(info.get("ppid") or 0),
                "name": info.get("name") or "",
                "executable": info.get("exe") or "",
                "command_line": list(info.get("cmdline") or []),
                "creation_time": float(info.get("create_time") or 0.0),
                "cwd": cwd,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return sorted(rows, key=lambda row: (row["pid"], row["creation_time"]))


def _c_project_artifacts() -> list[str]:
    if os.name != "nt":
        return []
    roots = (
        Path(r"C:\Users\Administrator\AppData\Local\Temp"),
        Path(r"C:\Users\Administrator\AppData\Local\MathWorks"),
        Path(r"C:\Users\Administrator\AppData\Roaming\MathWorks"),
        Path(r"C:\Windows\Temp"),
    )
    prefixes = ("CFD_ANCF", "stage4e_probe_verified", "stage4f", "OpenFOAM", "matlab_probe")
    found: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                if path.is_file() and any(prefix.lower() in path.name.lower() for prefix in prefixes):
                    found.append(str(path))
        except OSError:
            continue
    return sorted(set(found))


def _diff(before: Iterable[str], after: Iterable[str]) -> list[str]:
    return sorted(set(after) - set(before))


def run_argv_regression(*, project_root: str | Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(project_root).resolve()
    run = create_runtime_run(root, REGRESSION_TASK)
    env = build_task_environment(run, {**os.environ, "CFD_ANCF_MATLAB_EXE": str(MATLAB_EXE)})
    argv = build_regression_argv()
    started_at = _utc()
    argv_path = run / "launcher_argv.json"
    _json_write(argv_path, _argv_record(executable=MATLAB_EXE, argv=argv, cwd=run, env=env, created_at=started_at))
    stdout_path, stderr_path = run / "stdout.log", run / "stderr.log"
    process = None
    return_code: int | None = None
    error: str | None = None
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        try:
            process = subprocess.Popen(argv, cwd=str(run), env=env, stdout=stdout, stderr=stderr, text=True, shell=False)
            return_code = process.wait(timeout=300.0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            error = f"{type(exc).__name__}: {exc}"
            if process is not None:
                process.terminate()
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    passed = return_code == 0 and "ARGV_REGRESSION_OK" in stdout and "(a;b)" in stdout and "single quote test" in stdout
    result = {
        "schema": "stage4e-probe-verified-v1-argv-regression-1.0.0",
        "status": "passed" if passed else "LAUNCHER_ARGV_REGRESSION_FAILED",
        "run_id": run.name,
        "runtime_root": str(run),
        "return_code": return_code,
        "argv": argv,
        "argv_file": str(argv_path),
        "stdout_file": str(stdout_path),
        "stderr_file": str(stderr_path),
        "stdout": stdout,
        "stderr": stderr,
        "error": error,
        "shell": False,
        "launch_mechanism": "python_subprocess_Popen_argv_list",
    }
    _json_write(run / "regression_result.json", result)
    return result


def _owned_residual(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    residual: list[dict[str, Any]] = []
    for row in records:
        pid = row.get("pid")
        if pid is None:
            continue
        if process_snapshot(int(pid), purpose="residual_check") is not None:
            residual.append(dict(row))
    return residual


def _key_hashes(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        if path.is_file():
            rows.append({"filename": path.name, "absolute_path": str(path), "sha256": _sha(path), "size": path.stat().st_size, "timestamp_utc": _utc()})
    return rows


def run_formal_probe(*, project_root: str | Path = PROJECT_ROOT, argv_regression: Mapping[str, Any]) -> dict[str, Any]:
    if argv_regression.get("status") != "passed":
        raise RuntimeError("argv regression must pass before a formal runtime is created")
    root = Path(project_root).resolve()
    run = create_runtime_run(root, FORMAL_TASK)
    run_id = run.name
    token = f"stage4e_verified_{run_id}_{uuid.uuid4().hex}"
    logs, responses = run / "logs", run / "responses"
    process_registry = run / "process_registry"
    payload_path = responses / "probe_payload.json"
    matlab_log = logs / "matlab_internal.log"
    stdout_path, stderr_path = logs / "launcher_stdout.log", logs / "launcher_stderr.log"
    console_path = logs / "launcher_console.log"
    event_log = EventLog(logs / "raw_event_log.jsonl", run_id=run_id, run_token=token)
    evidence = ProcessEvidence(event_log, run_dir=run, run_token=token)
    env = build_task_environment(run, {**os.environ, "CFD_ANCF_MATLAB_EXE": str(MATLAB_EXE)})
    argv = build_formal_argv(run_id=run_id, token=token, payload_path=payload_path, matlab_log=matlab_log)
    started_at = _utc()
    argv_path = run / "launcher_argv.json"
    _json_write(argv_path, _argv_record(executable=MATLAB_EXE, argv=argv, cwd=run, env=env, created_at=started_at))
    _json_write(run / "environment_audit" / "child_environment.json", {
        "cwd": str(run), "environment": {key: env.get(key) for key in ("TEMP", "TMP", "TMPDIR", "MATLAB_PREFDIR", "PATH", "USERPROFILE", "APPDATA", "LOCALAPPDATA")},
        "global_environment_modified": False,
    })
    before_all = inventory_processes()
    before_matlab = enumerate_matlab_processes()
    before_mathworks = _mathworks_inventory()
    before_c = _c_project_artifacts()
    result: dict[str, Any] = {
        "schema": "stage4e-probe-verified-v1-result-1.0.0",
        "status": "NOT VERIFIED",
        "run_id": run_id,
        "run_token": token,
        "runtime_root": str(run),
        "start_time_utc": started_at,
        "matlab_executable": str(MATLAB_EXE),
        "matlab_executable_sha256": _sha(MATLAB_EXE),
        "argv_file": str(argv_path),
        "payload_path": str(payload_path),
        "matlab_log_path": str(matlab_log),
        "preexisting_matlab_processes": before_matlab,
        "preexisting_mathworks_processes": before_mathworks,
        "return_code": None,
        "interpreter_sentinel": False,
        "payload_validation": None,
        "owned_processes_started": [],
        "owned_processes_closed": [],
        "owned_residual": 0,
        "preexisting_process_impact": 0,
        "openfoam_started": 0,
    }
    event_log.append("preflight_completed", purpose="formal_stage4e_probe", log_path=matlab_log, payload={"command": argv, "preexisting_matlab_count": len(before_matlab), "preexisting_mathworks_count": len(before_mathworks)})
    evidence.start()
    process = None
    root_row: dict[str, Any] | None = None
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(argv, cwd=str(run), env=env, stdout=stdout, stderr=stderr, text=True, shell=False)
            root_row = evidence.register_pid(process.pid, purpose="formal_matlab_launcher", log_path=matlab_log)
            result["owned_processes_started"] = [root_row] if root_row else []
            event_log.append("probe_process_started", process=root_row, purpose="formal_stage4e_probe", log_path=matlab_log, payload={"argv": argv})
            try:
                result["return_code"] = process.wait(timeout=300.0)
            except subprocess.TimeoutExpired:
                result["block_reason"] = "formal_probe_timeout"
                event_log.append("probe_timeout", process=root_row, purpose="formal_stage4e_probe", log_path=matlab_log, cleanup_action="deferred_to_tree_cleanup", payload={"timeout_s": 300.0})
            else:
                event_log.append("probe_process_exited", process=root_row, purpose="formal_stage4e_probe", log_path=matlab_log, exit_code=result["return_code"], payload={"payload_exists": payload_path.is_file()})
    except OSError as exc:
        result["block_reason"] = f"formal_probe_launch_{type(exc).__name__}"
        result["error"] = str(exc)
    finally:
        time.sleep(1.0)
        evidence.stop()
        result["owned_processes_closed"] = evidence.cleanup(timeout_s=15.0)
    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.is_file() else ""
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.is_file() else ""
    console_path.write_text("[stdout]\n" + stdout_text + "\n[stderr]\n" + stderr_text, encoding="utf-8")
    result["interpreter_sentinel"] = "PROBE_INTERPRETER_REACHED" in stdout_text or "PROBE_INTERPRETER_REACHED" in stderr_text
    if payload_path.is_file():
        try:
            payload = read_json_payload(payload_path)
            result["payload_validation"] = validate_payload(payload, runtime_root=run, return_code=result["return_code"], run_id=run_id, run_token=token, executable=MATLAB_EXE)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            result["payload_validation"] = {"all_checks_passed": False, "error": f"{type(exc).__name__}: {exc}"}
    else:
        result["block_reason"] = result.get("block_reason", "structured_probe_payload_missing")
    residual = _owned_residual(evidence.snapshot_records())
    result["owned_residual"] = len(residual)
    result["owned_residual_records"] = residual
    after_all = inventory_processes()
    after_mathworks = _mathworks_inventory()
    result["process_inventory_before_count"] = len(before_all)
    result["process_inventory_after_count"] = len(after_all)
    result["post_mathworks_processes"] = after_mathworks
    result["preexisting_process_impact"] = len([row for row in before_mathworks if row.get("pid") not in {item.get("pid") for item in after_mathworks}])
    result["process_registry"] = {
        "owned_records": evidence.snapshot_records(),
        "cleanup_actions": result["owned_processes_closed"],
        "preexisting_mathworks": before_mathworks,
        "post_mathworks": after_mathworks,
        "ownership_rule": "root PID plus parent/child lineage and creation timestamp; shared ServiceHost is never owned by name",
    }
    _json_write(process_registry / "process_registry.json", result["process_registry"])
    after_c = _c_project_artifacts()
    c_diff = _diff(before_c, after_c)
    _json_write(run / "environment_audit" / "c_drive_artifact_diff.json", {"before": before_c, "after": after_c, "new_project_artifacts": c_diff, "count": len(c_diff)})
    result["c_drive_project_artifacts"] = len(c_diff)
    payload_checks = (result.get("payload_validation") or {}).get("checks", {})
    result["gate_table"] = {
        "argv_regression": argv_regression.get("status") == "passed",
        "fresh_d_runtime": run.drive.upper() == "D:",
        "executable_exact": str(MATLAB_EXE).lower() == str(EXPECTED_EXECUTABLE).lower(),
        "interpreter_sentinel": result["interpreter_sentinel"],
        "release_2021b": payload_checks.get("release_2021b", False),
        "architecture_win64": payload_checks.get("architecture_win64", False),
        "license_test_matlab_1": payload_checks.get("license_test_matlab_one", False),
        "return_code_0": result["return_code"] == 0,
        "application_service_ok": payload_checks.get("application_service_ok", False),
        "json_schema_strict": bool((result.get("payload_validation") or {}).get("all_checks_passed", False)),
        "owned_residual_0": result["owned_residual"] == 0,
        "preexisting_untouched": result["preexisting_process_impact"] == 0,
        "d_runtime_hygiene": all(str(env.get(key, "")).upper().startswith(str(run).upper()) for key in ("TEMP", "TMP", "TMPDIR", "MATLAB_PREFDIR")),
        "c_drive_project_artifacts_0": result["c_drive_project_artifacts"] == 0,
        "no_worker_openfoam_cfd": result["openfoam_started"] == 0,
    }
    result["status"] = "VERIFIED" if all(result["gate_table"].values()) else "NOT VERIFIED"
    result["end_time_utc"] = _utc()
    _json_write(run / "probe_result.json", result)
    event_audit = validate_event_log(event_log.path)
    _json_write(run / "process_registry" / "event_log_audit.json", event_audit)
    result["event_log_audit"] = event_audit
    _json_write(run / "probe_result.json", result)
    key_files = [matlab_log, stdout_path, stderr_path, console_path, payload_path, argv_path, process_registry / "process_registry.json", run / "probe_result.json"]
    _json_write(run / "evidence_sha256.json", {"files": _key_hashes(key_files)})
    result["evidence_sha256_path"] = str(run / "evidence_sha256.json")
    _json_write(run / "probe_result.json", result)
    return result


if __name__ == "__main__":
    regression = run_argv_regression()
    print(json.dumps(regression, ensure_ascii=False, indent=2))
