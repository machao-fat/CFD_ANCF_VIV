"""Run each MATLAB headless launch form once and preserve complete evidence."""
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
    EventLog, ProcessEvidence, enumerate_matlab_processes, file_sha256,
    process_snapshot, validate_event_log,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MATLAB = Path(r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")


def _quote(path: str | Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def _expression(mode: str, run_id: str, token: str) -> str:
    # Keep both expressions diagnostic-only. No worker, payload, or project code
    # is loaded; every value is printed with an unambiguous marker.
    body = (
        f"fprintf(1,'ENV_DIAG_BEGIN mode={mode} run_id={run_id} token={token}\\n'); "
        "fprintf(1,'ENV_VERSION=%s\\n',version); "
        "fprintf(1,'ENV_RELEASE=%s\\n',version('-release')); "
        "fprintf(1,'ENV_ARCH=%s\\n',computer('arch')); "
        "fprintf(1,'ENV_LICENSE=%d\\n',license('test','MATLAB')); "
        "fprintf(1,'ENV_TEMP=%s\\n',getenv('TEMP')); "
        "fprintf(1,'ENV_TMP=%s\\n',getenv('TMP')); "
        "fprintf(1,'ENV_TMPDIR=%s\\n',getenv('TMPDIR')); "
        "fprintf(1,'ENV_PREFDIR=%s\\n',prefdir); "
        "fprintf(1,'ENV_PWD=%s\\n',pwd); "
        "fprintf(1,'ENV_DIAG_END\\n');"
    )
    return body + (" exit;" if mode == "r" else "")


def _parse_markers(stdout: str, stderr: str, internal: str) -> dict[str, Any]:
    combined = "\n".join((stdout, stderr, internal))
    values: dict[str, Any] = {}
    for key in ("VERSION", "RELEASE", "ARCH", "TEMP", "TMP", "TMPDIR", "PREFDIR", "PWD"):
        match = re.findall(rf"^ENV_{key}=(.*)$", stdout, flags=re.MULTILINE)
        if match:
            values[key.lower()] = match[-1].strip()
    license_match = re.findall(r"^ENV_LICENSE=(-?\d+)$", stdout, flags=re.MULTILINE)
    values["license"] = int(license_match[-1]) if license_match else None
    return {
        "markers": values,
        "application_service_error": bool(re.search(r"ApplicationService|服务通信|error\s*5001|错误\s*5001", combined, re.I)),
        "stdout": stdout,
        "stderr": stderr,
        "matlab_log": internal,
    }


def run_diagnostic(*, project_root: str | Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(project_root).resolve()
    run = create_runtime_run(root, "stage4f_c_environment_repair_v1")
    token = f"r2021b_envdiag_{run.name}_{uuid.uuid4().hex}"
    event_log = EventLog(run / "logs" / "raw_event_log.jsonl", run_id=run.name, run_token=token)
    evidence = ProcessEvidence(event_log, run_dir=run, run_token=token)
    base = {**os.environ, "CFD_ANCF_MATLAB_EXE": str(MATLAB), "PREFDIR": str(run / "matlab_pref")}
    env = build_task_environment(run, base)
    before = inventory_processes()
    before_matlab = enumerate_matlab_processes()
    event_log.append("diagnostic_preflight_completed", purpose="environment_repair", payload={"commands": 2, "matlab": str(MATLAB)})
    cases = (
        ("batch", [str(MATLAB), "-batch", _expression("batch", run.name, token)]),
        ("r_headless", [str(MATLAB), "-nosplash", "-nodesktop", "-nodisplay", "-r", _expression("r", run.name, token)]),
    )
    results: list[dict[str, Any]] = []
    evidence.start()
    try:
        for name, command in cases:
            case_dir = run / name
            case_dir.mkdir()
            stdout_path, stderr_path, internal_path = case_dir / "stdout.log", case_dir / "stderr.log", case_dir / "matlab_internal.log"
            event_log.append("diagnostic_launch_requested", purpose=name, log_path=internal_path, payload={"command": command, "env": {k: env.get(k) for k in ("TEMP", "TMP", "TMPDIR", "PREFDIR", "MATLAB_PREFDIR")}})
            started = time.monotonic()
            process = None
            row = None
            exit_code: int | None = None
            timeout = False
            try:
                with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
                    process = subprocess.Popen(command, cwd=str(case_dir), env=env, stdout=out, stderr=err, text=True, shell=False)
                    row = evidence.register_pid(process.pid, purpose=f"{name}_launcher", log_path=internal_path)
                    exit_code = process.wait(timeout=180.0)
            except subprocess.TimeoutExpired:
                timeout = True
                if process is not None:
                    process.terminate()
                    try:
                        process.wait(timeout=15.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=15.0)
                exit_code = None
            event_log.append("diagnostic_process_exited", process=row, purpose=name, log_path=internal_path, exit_code=exit_code, payload={"timeout": timeout, "elapsed_s": time.monotonic() - started})
            stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.is_file() else ""
            stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.is_file() else ""
            internal = internal_path.read_text(encoding="utf-8", errors="replace") if internal_path.is_file() else ""
            parsed = _parse_markers(stdout, stderr, internal)
            records = [r for r in evidence.snapshot_records() if r.get("cwd", "").lower().startswith(str(case_dir).lower())]
            results.append({
                "name": name, "command": command, "return_code": exit_code, "timed_out": timeout,
                "stdout_path": str(stdout_path), "stderr_path": str(stderr_path), "matlab_log_path": str(internal_path),
                "stdout_sha256": file_sha256(stdout_path), "stderr_sha256": file_sha256(stderr_path), "matlab_log_sha256": file_sha256(internal_path),
                "parsed": parsed, "process_records": records,
            })
    finally:
        evidence.stop()
        cleanup = evidence.cleanup(timeout_s=15.0)
    records = evidence.snapshot_records()
    residual = [row for row in records if process_snapshot(int(row["pid"]), purpose="residual") is not None]
    result = {
        "schema": "stage4f-c-environment-repair-v1-diagnostic-1.0.0",
        "status": "environment_blocked" if not all(item["return_code"] == 0 and not item["parsed"]["application_service_error"] for item in results) else "diagnostic_success",
        "conclusion": "MATLAB R2021b headless/ApplicationService environment damaged; user Repair or reinstall required" if all(item["return_code"] != 0 or item["parsed"]["application_service_error"] for item in results) else "one launch shape succeeded; strict probe repair is required before any worker authorization",
        "runtime_root": str(run), "run_id": run.name, "run_token": token,
        "matlab_executable": str(MATLAB), "matlab_executable_sha256": file_sha256(MATLAB),
        "environment": {key: env.get(key) for key in ("TEMP", "TMP", "TMPDIR", "PREFDIR", "MATLAB_PREFDIR")},
        "preexisting_matlab_processes": before_matlab, "commands": results,
        "owned_process_tree_records": records, "cleanup_records": cleanup,
        "owned_residual_count": len(residual), "owned_residual": residual,
        "event_log_path": str(event_log.path), "event_log_sha256": event_log.sha256(),
        "event_log_audit": validate_event_log(event_log.path),
        "process_inventory_before_count": len(before), "process_inventory_after_count": len(inventory_processes()),
        "attempt2_created": False, "matlab_worker_started": False, "openfoam_started": False,
    }
    (run / "environment_repair_diagnostic.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_diagnostic(), ensure_ascii=False, indent=2))
