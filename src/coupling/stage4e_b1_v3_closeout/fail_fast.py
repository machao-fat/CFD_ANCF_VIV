from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from src.coupling.runtime_hygiene import build_task_environment, inventory_processes
from src.coupling.runtime_hygiene.runtime import write_json


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(process: Any) -> dict[str, Any]:
    info = process.info
    try:
        cwd = str(process.cwd())
    except Exception:
        cwd = ""
    return {
        "pid": int(info.get("pid") or process.pid),
        "parent_pid": int(info.get("ppid") or 0),
        "creation_time": float(info.get("create_time") or 0.0),
        "name": str(info.get("name") or ""),
        "executable": str(info.get("exe") or ""),
        "command_line": list(info.get("cmdline") or []),
        "cwd": cwd,
    }


def enumerate_matlab_processes() -> list[dict[str, Any]]:
    """Read-only MATLAB process inventory used by the fail-fast gate."""
    if psutil is None:
        return []
    rows: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "create_time"]):
        try:
            info = process.info
            name = Path(str(info.get("name") or "")).name.lower()
            executable = Path(str(info.get("exe") or "")).name.lower()
            if name.startswith("matlab") or executable.startswith("matlab"):
                rows.append(_row(process))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return sorted(rows, key=lambda item: (item["pid"], item["creation_time"]))


def decide_preflight(*, preexisting_matlab_count: int, matlab_executable_exists: bool) -> dict[str, Any]:
    if preexisting_matlab_count:
        return {
            "status": "environment_blocked",
            "block_reason": "preexisting_matlab_processes_blocked",
            "tests_started": 0,
            "version_probe_attempts": 0,
            "smoke_attempts": 0,
            "formal_tests_started": 0,
        }
    if not matlab_executable_exists:
        return {
            "status": "environment_blocked",
            "block_reason": "matlab_executable_missing",
            "tests_started": 0,
            "version_probe_attempts": 0,
            "smoke_attempts": 0,
            "formal_tests_started": 0,
        }
    return {
        "status": "ready_for_single_version_probe",
        "block_reason": None,
        "tests_started": 0,
        "version_probe_attempts": 0,
        "smoke_attempts": 0,
        "formal_tests_started": 0,
    }


def _owned_record(process: subprocess.Popen[str], *, purpose: str, log_path: Path, run_id: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "pid": int(process.pid),
        "parent_pid": int(os.getpid()),
        "creation_time": None,
        "executable": "",
        "command_line": [],
        "cwd": str(process.cwd) if hasattr(process, "cwd") else "",
        "purpose": purpose,
        "run_id": run_id,
        "log_path": str(log_path),
        "close_method": "terminate_then_kill_after_timeout_with_identity_check",
        "status": "owned",
    }
    if psutil is not None:
        try:
            current = psutil.Process(process.pid)
            record.update(
                {
                    "parent_pid": int(current.ppid()),
                    "creation_time": float(current.create_time()),
                    "executable": current.exe(),
                    "command_line": current.cmdline(),
                    "cwd": current.cwd(),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return record


def _close_owned(record: Mapping[str, Any], timeout_s: float = 5.0) -> dict[str, Any]:
    """Close only a recorded process after PID/creation/parent verification."""
    result = {"pid": int(record["pid"]), "action": "not_started"}
    if psutil is None:
        result["action"] = "psutil_unavailable_refused"
        return result
    try:
        process = psutil.Process(int(record["pid"]))
        if record.get("creation_time") is not None and abs(process.create_time() - float(record["creation_time"])) >= 1e-3:
            result["action"] = "refused_creation_time_mismatch"
            return result
        if int(process.ppid()) != int(record.get("parent_pid") or -1):
            result["action"] = "refused_parent_mismatch"
            return result
        if process.is_running():
            process.terminate()
            try:
                process.wait(timeout=timeout_s)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout_s)
                result["action"] = "kill_after_timeout"
            else:
                result["action"] = "terminate"
        else:
            result["action"] = "already_gone"
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        result["action"] = "already_gone"
    except (psutil.AccessDenied, psutil.TimeoutExpired) as exc:
        result["action"] = "cleanup_failed"
        result["error"] = str(exc)
    return result


def run_fail_fast_preflight(*, project_root: str | Path, runtime_dir: str | Path, matlab_exe: str | Path) -> dict[str, Any]:
    """Perform strict preflight and never launch a worker after a block."""
    runtime = Path(runtime_dir).resolve()
    exe = Path(matlab_exe).resolve()
    preexisting = enumerate_matlab_processes()
    decision = decide_preflight(
        preexisting_matlab_count=len(preexisting),
        matlab_executable_exists=exe.is_file(),
    )
    result: dict[str, Any] = {
        "schema_version": "stage4e-b1-v3-environment-preflight-1.0.0",
        "timestamp_utc": utc_now(),
        "project_root": str(Path(project_root).resolve()),
        "runtime_dir": str(runtime),
        "matlab_executable": str(exe),
        "matlab_executable_exists": exe.is_file(),
        "preexisting_matlab_processes": preexisting,
        "preexisting_matlab_process_count": len(preexisting),
        **decision,
        "version_probe": {"status": "not_started", "attempts": 0, "reason": decision["block_reason"]},
        "owned_processes_started": [],
        "owned_processes_closed": [],
        "owned_process_residual_count": 0,
        "unrelated_processes_terminated": 0,
        "read_only_process_enumeration": True,
    }
    if decision["status"] != "ready_for_single_version_probe":
        return result

    # This branch is intentionally one probe only.  In the current environment
    # preexisting MATLAB processes block before this code can execute.
    log_path = runtime / "logs" / "matlab_version_probe.log"
    env = build_task_environment(runtime)
    command = [str(exe), "-batch", "disp(version); disp(tempdir); disp(prefdir); disp(pwd)"]
    record: dict[str, Any] | None = None
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=str(runtime), env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
            record = _owned_record(process, purpose="matlab_version_probe", log_path=log_path, run_id=runtime.name)
            result["owned_processes_started"] = [record]
            result["version_probe"] = {"status": "running", "attempts": 1, "command": command}
            try:
                code = process.wait(timeout=150.0)
            except subprocess.TimeoutExpired:
                action = _close_owned(record)
                result["version_probe"] = {"status": "timeout", "attempts": 1, "cleanup": action}
                result["status"] = "environment_blocked"
                result["block_reason"] = "matlab_version_probe_timeout"
            else:
                result["version_probe"] = {"status": "passed" if code == 0 else "failed", "attempts": 1, "return_code": code}
                if code != 0:
                    result["status"] = "environment_blocked"
                    result["block_reason"] = "matlab_version_probe_failed"
    except OSError as exc:
        result["version_probe"] = {"status": "failed", "attempts": 1, "error": str(exc)}
        result["status"] = "environment_blocked"
        result["block_reason"] = "matlab_version_probe_launch_failed"
    finally:
        if record is not None:
            action = _close_owned(record)
            result["owned_processes_closed"] = [action]
            result["owned_process_residual_count"] = 0 if action.get("action") in {"terminate", "kill_after_timeout", "already_gone"} else 1
    return result
