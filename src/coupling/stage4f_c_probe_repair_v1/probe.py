"""One-shot real MATLAB probe with isolated logs and auditable process evidence."""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

from src.coupling.runtime_hygiene import build_task_environment, create_runtime_run, inventory_processes
from src.coupling.stage4e_b1_v3_1_closeout.evidence import (
    EventLog, ProcessEvidence, enumerate_matlab_processes, file_sha256,
    process_snapshot, validate_event_log,
)
from .contract import EXPECTED_EXECUTABLE, SCHEMA, read_json_payload, validate_payload

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MATLAB = EXPECTED_EXECUTABLE


def _quote(value: str | Path) -> str:
    return str(value).replace("\\", "/").replace("'", "''")


def payload_expression(*, run_id: str, token: str, payload_path: Path) -> str:
    p = _quote(payload_path)
    # The file is the only authoritative channel. Console output is a separate
    # diagnostic channel and never participates in field extraction.
    return (
        f"probe=struct; probe.schema_version='{SCHEMA}'; probe.run_id='{_quote(run_id)}'; "
        f"probe.run_token='{_quote(token)}'; probe.probe_begin=true; probe.version=version; "
        "probe.release=version('-release'); probe.architecture=computer('arch'); "
        "probe.license_test_matlab=license('test','MATLAB'); probe.TEMP=getenv('TEMP'); "
        "probe.TMP=getenv('TMP'); probe.TMPDIR=getenv('TMPDIR'); probe.tempdir=tempdir; "
        "probe.prefdir=prefdir; probe.pwd=pwd; probe.application_service='ok'; probe.probe_end=true; "
        f"payload=jsonencode(probe); fid=fopen('{p}','w','n','UTF-8'); assert(fid>0); "
        "fprintf(fid,'%s',payload); fclose(fid); fprintf('MATLAB_PROBE_PAYLOAD_WRITTEN\\n');"
    )


def _c_drive_project_artifacts(token: str) -> list[str]:
    hits: list[str] = []
    for base in (Path(r"C:\Temp"), Path(r"C:\Users\Administrator\AppData\Local\Temp")):
        if not base.is_dir():
            continue
        try:
            hits.extend(str(path) for path in base.rglob(f"*{token}*"))
        except OSError:
            continue
    return hits


def _identity_records(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {"launcher": [], "matlab_core": [], "servicehost": [], "other_owned": []}
    for row in records:
        exe = Path(str(row.get("executable") or "")).name.lower()
        if exe == "matlab.exe" and "\\bin\\win64\\" not in str(row.get("executable") or "").lower():
            groups["launcher"].append(row)
        elif exe == "matlab.exe":
            groups["matlab_core"].append(row)
        elif exe == "mathworksservicehost.exe":
            groups["servicehost"].append(row)
        else:
            groups["other_owned"].append(row)
    return groups


def run_probe(*, project_root: str | Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(project_root).resolve()
    run = create_runtime_run(root, "stage4f_c_probe_repair_v1")
    run_id = run.name
    token = f"r2021b_stage4f_c_{run_id}_{uuid.uuid4().hex}"
    logs, responses = run / "logs", run / "responses"
    payload_path = responses / "probe_payload.json"
    matlab_log, launcher_log = logs / "matlab_internal.log", logs / "launcher_console.log"
    event_log = EventLog(logs / "raw_event_log.jsonl", run_id=run_id, run_token=token)
    evidence = ProcessEvidence(event_log, run_dir=run, run_token=token)
    env = build_task_environment(run, {**os.environ, "CFD_ANCF_MATLAB_EXE": str(MATLAB)})
    before, before_matlab = inventory_processes(), enumerate_matlab_processes()
    command = [str(MATLAB), "-wait", "-logfile", str(matlab_log), "-batch", payload_expression(run_id=run_id, token=token, payload_path=payload_path)]
    result: dict[str, Any] = {
        "schema": "stage4f-c-probe-repair-v1-result-1.0.0", "status": "environment_blocked",
        "run_id": run_id, "run_token": token, "runtime_root": str(run), "command": command,
        "matlab_executable": str(MATLAB), "matlab_executable_sha256": file_sha256(MATLAB),
        "environment": {key: env.get(key) for key in ("TEMP", "TMP", "TMPDIR", "MATLAB_PREFDIR", "CFD_ANCF_MATLAB_EXE")},
        "preexisting_matlab_processes": before_matlab, "return_code": None,
        "payload_validation": None, "owned_processes_started": [], "owned_processes_closed": [],
        "owned_residual_count": 0, "c_drive_project_artifacts": [], "openfoam_started": False,
        "application_service_startup": False,
    }
    event_log.append("preflight_completed", purpose="probe_repair", log_path=matlab_log,
                     payload={"preexisting_matlab_count": len(before_matlab), "command": command})
    evidence.start()
    process = None
    try:
        with launcher_log.open("w", encoding="utf-8") as console:
            process = subprocess.Popen(command, cwd=str(run), env=env, stdout=console, stderr=subprocess.STDOUT, text=True, shell=False)
            row = evidence.register_pid(process.pid, purpose="matlab_probe_launcher", log_path=matlab_log)
            if row:
                result["owned_processes_started"].append(row)
            event_log.append("probe_process_started", process=row, purpose="probe_repair", log_path=matlab_log, payload={"command": command})
            result["return_code"] = process.wait(timeout=300.0)
            event_log.append("probe_process_exited", process=row, purpose="probe_repair", log_path=matlab_log,
                             exit_code=result["return_code"], payload={"payload_exists": payload_path.is_file()})
            console_text = launcher_log.read_text(encoding="utf-8", errors="replace")
            if payload_path.is_file():
                payload = read_json_payload(payload_path)
                result["payload_validation"] = validate_payload(payload, runtime_root=run, return_code=result["return_code"],
                    run_id=run_id, run_token=token, executable=MATLAB, console_text=console_text)
                result["application_service_startup"] = payload.get("application_service") == "ok"
                if result["payload_validation"]["all_checks_passed"]:
                    result["status"] = "passed"
                else:
                    result["block_reason"] = "structured_probe_payload_checks_failed"
            else:
                result["block_reason"] = "matlab_internal_failure_before_payload"
                result["matlab_internal_failure"] = matlab_log.read_text(encoding="utf-8", errors="replace") if matlab_log.is_file() else ""
    except subprocess.TimeoutExpired:
        result["block_reason"] = "probe_timeout"
        if process is not None:
            process.terminate()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result["block_reason"] = f"probe_error_{type(exc).__name__}"
        result["error"] = str(exc)
    finally:
        evidence.stop()
        result["owned_processes_closed"] = evidence.cleanup(timeout_s=15.0)
        records = evidence.snapshot_records()
        result["owned_process_tree_records"] = records
        result["owned_process_identity"] = _identity_records(records)
        result["owned_residual_count"] = sum(1 for row in records if process_snapshot(int(row["pid"]), purpose="residual") is not None)
    result["event_log_path"] = str(event_log.path)
    result["event_log_sha256"] = event_log.sha256()
    result["event_log_audit"] = validate_event_log(event_log.path)
    result["process_inventory_before_count"] = len(before)
    result["process_inventory_after_count"] = len(inventory_processes())
    result["c_drive_project_artifacts"] = _c_drive_project_artifacts(token)
    result["c_drive_project_artifact_count"] = len(result["c_drive_project_artifacts"])
    result["owned_residual"] = result["owned_residual_count"]
    (run / "probe_repair_result.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_probe(), ensure_ascii=False, indent=2))
