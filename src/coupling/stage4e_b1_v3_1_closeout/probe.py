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
from .evidence import EventLog, ProcessEvidence, enumerate_matlab_processes, file_sha256, validate_event_log
from .real_runner import matlab_worker_command


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MATLAB_EXE = Path(os.environ.get("CFD_ANCF_MATLAB_EXE", r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")).resolve()
MATLAB_CORE = MATLAB_EXE.parent / "win64" / "MATLAB.exe"


def _clean_output(text: str) -> str:
    # Preserve probe markers and diagnostics, but never persist license IDs or
    # usernames if MATLAB happens to print them.
    lines = []
    for line in text.splitlines():
        if re.search(r"license|username|user(name)?|serial|activation", line, re.IGNORECASE) and "license('test'" not in line:
            continue
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def _process_tree_rows(root_pid: int) -> list[dict[str, Any]]:
    rows = []
    import psutil
    try:
        root = psutil.Process(root_pid)
        for process in [root, *root.children(recursive=True)]:
            try:
                rows.append({"pid": process.pid, "parent_pid": process.ppid(), "creation_time": process.create_time(), "executable": process.exe(), "command_line": process.cmdline(), "cwd": process.cwd()})
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
    return rows


def run_probe(*, project_root: str | Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(project_root).resolve()
    run = create_runtime_run(root, "stage4e_b1_v3_1_probe")
    run_id = run.name
    token = f"r2021b_probe_{run_id}_{uuid.uuid4().hex}"
    event_path = run / "logs" / "raw_event_log.jsonl"
    log_path = run / "logs" / "matlab_version_license_probe.log"
    event_log = EventLog(event_path, run_id=run_id, run_token=token)
    evidence = ProcessEvidence(event_log, run_dir=run, run_token=token)
    env = build_task_environment(run, {**os.environ, "CFD_ANCF_MATLAB_EXE": str(MATLAB_EXE)})
    before = inventory_processes()
    preexisting = enumerate_matlab_processes()
    launch_identity = {
        "launcher_path": str(MATLAB_EXE),
        "launcher_sha256": file_sha256(MATLAB_EXE),
        "launcher_version": None,
        "core_path": str(MATLAB_CORE),
        "core_sha256": file_sha256(MATLAB_CORE),
        "core_version": None,
        "install_directory": str(MATLAB_EXE.parents[1]),
        "old_path": r"D:\Matlab\bin\matlab.exe",
        "old_path_exists": Path(r"D:\Matlab\bin\matlab.exe").is_file(),
        "selected_path": str(MATLAB_EXE),
    }
    if MATLAB_EXE.is_file():
        import subprocess as _subprocess
        launcher_version = _subprocess.run(["powershell", "-NoProfile", "-Command", f"[System.Diagnostics.FileVersionInfo]::GetVersionInfo('{MATLAB_EXE}').FileVersion"], capture_output=True, text=True, timeout=10)
        launch_identity["launcher_version"] = launcher_version.stdout.strip()
    if MATLAB_CORE.is_file():
        import subprocess as _subprocess
        core_version = _subprocess.run(["powershell", "-NoProfile", "-Command", f"[System.Diagnostics.FileVersionInfo]::GetVersionInfo('{MATLAB_CORE}').FileVersion"], capture_output=True, text=True, timeout=10)
        launch_identity["core_version"] = core_version.stdout.strip()
    event_log.append("preflight_completed", purpose="version_license_probe", log_path=log_path, payload={"preexisting_matlab_count": len(preexisting), "selected_path": str(MATLAB_EXE)})
    result: dict[str, Any] = {
        "schema_version": "stage4e-b1-v3.1-r2021b-probe-1.0.0",
        "status": "environment_blocked",
        "run_id": run_id,
        "run_token": token,
        "runtime_root": str(run),
        "matlab_installation_identity": launch_identity,
        "preexisting_matlab_process_count": len(preexisting),
        "preexisting_matlab_processes": preexisting,
        "probe_attempts": 0,
        "command": None,
        "return_code": None,
        "log_path": str(log_path),
        "probe_output": None,
        "checks": {},
        "owned_processes_started": [],
        "owned_processes_closed": [],
        "owned_residual_count": 0,
        "unrelated_terminated": 0,
    }
    if preexisting:
        result["block_reason"] = "preexisting_matlab_processes_blocked"
        result["status"] = "environment_blocked"
    elif not MATLAB_EXE.is_file() or not MATLAB_CORE.is_file():
        result["block_reason"] = "r2021b_installation_missing"
    else:
        expression = (
            f"fprintf('MATLAB_PROBE_BEGIN\\n'); "
            f"fprintf('RUN_TOKEN={token}\\n'); "
            f"disp(version); disp(version('-release')); disp(computer('arch')); "
            f"disp(license('test','MATLAB')); disp(tempdir); disp(prefdir); disp(pwd); "
            f"fprintf('MATLAB_PROBE_END\\n');"
        )
        command = [str(MATLAB_EXE), "-wait", "-logfile", str(log_path), "-batch", expression]
        result["command"] = command
        result["probe_attempts"] = 1
        event_log.append("probe_launch_requested", purpose="version_license_probe", log_path=log_path, payload={"command": command})
        evidence.start()
        started = time.monotonic()
        try:
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(command, cwd=str(run), env=env, stdout=log, stderr=subprocess.STDOUT, text=True, shell=False)
                root_row = evidence.register_pid(process.pid, purpose="matlab_probe_launcher", log_path=log_path)
                result["owned_processes_started"] = [root_row] if root_row else []
                event_log.append("probe_process_started", process=root_row, purpose="matlab_probe_launcher", log_path=log_path, payload={"command": command})
                try:
                    code = process.wait(timeout=300.0)
                except subprocess.TimeoutExpired:
                    result["block_reason"] = "matlab_version_license_probe_timeout"
                    result["status"] = "environment_blocked"
                    event_log.append("probe_timeout", process=root_row, purpose="matlab_probe_launcher", log_path=log_path, cleanup_action="deferred_to_tree_cleanup", payload={"elapsed_s": time.monotonic() - started})
                else:
                    result["return_code"] = code
                    event_log.append("probe_process_exited", process=root_row, purpose="matlab_probe_launcher", log_path=log_path, exit_code=code, payload={"elapsed_s": time.monotonic() - started})
                    output = _clean_output(log_path.read_text(encoding="utf-8", errors="replace")) if log_path.is_file() else ""
                    result["probe_output"] = output
                    checks = {
                        "return_code_zero": code == 0,
                        "log_nonempty": bool(output.strip()),
                        "begin_marker": "MATLAB_PROBE_BEGIN" in output,
                        "end_marker": "MATLAB_PROBE_END" in output,
                        "release_2021b": "R2021b" in output or "2021b" in output,
                        "version_9_11_series": bool(re.search(r"9\.11", output)),
                        "architecture_win64": "win64" in output.lower(),
                        "license_test_one": bool(re.search(r"(?m)^\s*1\s*$", output)),
                        "temp_on_d_drive_runtime": str(run).lower() in output.lower(),
                        "pref_on_d_drive_runtime": str(run).lower() in output.lower(),
                    }
                    result["checks"] = checks
                    result["status"] = "passed" if all(checks.values()) else "environment_blocked"
                    result["block_reason"] = None if result["status"] == "passed" else "matlab_version_license_probe_checks_failed"
        except OSError as exc:
            result["block_reason"] = "matlab_version_license_probe_launch_failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            evidence.stop()
            actions = evidence.cleanup(timeout_s=15.0)
            result["owned_processes_closed"] = actions
            result["owned_residual_count"] = sum(1 for row in evidence.snapshot_records() if row.get("pid") and process_snapshot_alive(int(row["pid"])))
    result["event_log_path"] = str(event_path)
    result["event_log_sha256"] = event_log.sha256()
    result["event_log_audit"] = validate_event_log(event_path)
    result["owned_process_tree_records"] = evidence.snapshot_records()
    result["process_inventory_before_count"] = len(before)
    result["process_inventory_after_count"] = len(inventory_processes())
    (run / "process_registry" / "probe_summary.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return result


def process_snapshot_alive(pid: int) -> bool:
    import psutil
    try:
        return psutil.Process(pid).is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(run_probe(), ensure_ascii=False, indent=2))
