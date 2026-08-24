"""一次性、payload-first 的 MATLAB R2021b ApplicationService 探针。

探针只验证 MATLAB 核心是否能在显式 D 盘环境中执行一个无项目依赖的
表达式。它不启动 worker、OpenFOAM 或任何 Stage 4F case。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "stage4f_c_applicationservice_repair_v2"
RESULTS_ROOT = PROJECT_ROOT / "results" / "13_stage4f_c_applicationservice_repair_v2"
MATLAB_LAUNCHER = Path(r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
MATLAB_CORE = Path(r"D:\Program Files\MATLAB\R2021b\bin\win64\MATLAB.exe")
SCHEMA = "stage4f-c-applicationservice-repair-v2-probe-1.0.0"


def sha256_file(path: str | Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def _quote(value: str | Path) -> str:
    return str(value).replace("\\", "/").replace("'", "''")


def _under(path: Any, parent: Path) -> bool:
    try:
        Path(str(path).replace("/", "\\")).resolve(strict=False).relative_to(parent.resolve())
        return True
    except (OSError, TypeError, ValueError):
        return False


def build_isolated_environment(run: Path) -> dict[str, str]:
    """Return process-local paths; no user or system environment is changed."""
    paths = {
        "TEMP": run / "tmp",
        "TMP": run / "tmp",
        "TMPDIR": run / "tmpdir",
        "PREFDIR": run / "matlab_pref",
        "MATLAB_PREFDIR": run / "matlab_pref",
        "MATLAB_LOG_DIR": run / "matlab_logs",
        "APPDATA": run / "appdata" / "roaming",
        "LOCALAPPDATA": run / "appdata" / "local",
        "PYTHONPYCACHEPREFIX": run / "pycache",
        "PIP_CACHE_DIR": run / "pip_cache",
        "MPLCONFIGDIR": run / "mplconfig",
    }
    env = dict(os.environ)
    for key, value in paths.items():
        value.mkdir(parents=True, exist_ok=True)
        env[key] = str(value)
    env["CFD_ANCF_MATLAB_EXE"] = str(MATLAB_CORE)
    return env


def payload_expression(*, run_id: str, token: str, payload_path: Path) -> str:
    path = _quote(payload_path)
    return (
        f"probe=struct; probe.schema_version='{SCHEMA}'; probe.run_id='{_quote(run_id)}'; "
        f"probe.run_token='{_quote(token)}'; probe.probe_begin=true; probe.version=version; "
        "probe.release=version('-release'); probe.architecture=computer('arch'); "
        "probe.license_test_matlab=license('test','MATLAB'); probe.TEMP=getenv('TEMP'); "
        "probe.TMP=getenv('TMP'); probe.TMPDIR=getenv('TMPDIR'); probe.tempdir=tempdir; "
        "probe.prefdir=prefdir; probe.pwd=pwd; probe.application_service='ok'; probe.probe_end=true; "
        f"fid=fopen('{path}','w','n','UTF-8'); assert(fid>0); fprintf(fid,'%s',jsonencode(probe)); "
        "fclose(fid); fprintf(1,'MATLAB_PROBE_PAYLOAD_WRITTEN\\n');"
    )


def read_payload(path: Path) -> dict[str, Any]:
    def reject(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant: {value}")
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)
    if not isinstance(value, dict):
        raise ValueError("probe payload is not an object")
    return value


def validate_payload(payload: Mapping[str, Any], *, run: Path, run_id: str, token: str, return_code: int | None) -> dict[str, Any]:
    required = ("schema_version", "run_id", "run_token", "probe_begin", "probe_end", "version", "release", "architecture", "license_test_matlab", "TEMP", "TMP", "TMPDIR", "tempdir", "prefdir", "pwd", "application_service")
    version = str(payload.get("version", ""))
    checks = {
        "required_fields": all(key in payload for key in required),
        "schema": payload.get("schema_version") == SCHEMA,
        "identity": payload.get("run_id") == run_id and payload.get("run_token") == token,
        "markers": payload.get("probe_begin") is True and payload.get("probe_end") is True,
        "r2021b": payload.get("release") == "2021b" and bool(re.match(r"^9\.11(?:\.|\s|$)", version)),
        "architecture": payload.get("architecture") == "win64",
        "license": type(payload.get("license_test_matlab")) is int and payload.get("license_test_matlab") == 1,
        "application_service": payload.get("application_service") == "ok",
        "TEMP_under_runtime": _under(payload.get("TEMP"), run),
        "TMP_under_runtime": _under(payload.get("TMP"), run),
        "TMPDIR_under_runtime": _under(payload.get("TMPDIR"), run),
        "tempdir_under_runtime": _under(payload.get("tempdir"), run),
        "prefdir_under_runtime": _under(payload.get("prefdir"), run),
        "pwd_under_runtime": _under(payload.get("pwd"), run),
        "return_code_zero": return_code == 0,
    }
    return {"checks": checks, "all_checks_passed": all(checks.values()), "payload": dict(payload), "return_code": return_code}


def _process_snapshot(pid: int) -> dict[str, Any]:
    row: dict[str, Any] = {"pid": int(pid), "parent_pid": None, "creation_time": None, "executable": None, "command_line": [], "cwd": None}
    try:
        import psutil
        process = psutil.Process(pid)
        row.update({"parent_pid": process.ppid(), "creation_time": process.create_time(), "executable": process.exe(), "command_line": process.cmdline(), "cwd": process.cwd()})
    except Exception as exc:  # process may exit between snapshots
        row["snapshot_error"] = type(exc).__name__
    row["executable_sha256"] = sha256_file(row.get("executable") or "")
    return row


def _c_drive_hits(token: str) -> list[str]:
    hits: list[str] = []
    for root in (Path(r"C:\Temp"), Path(r"C:\Users\Administrator\AppData\Local\Temp")):
        if not root.is_dir():
            continue
        try:
            hits.extend(str(item) for item in root.rglob(f"*{token}*"))
        except OSError:
            continue
    return sorted(set(hits))


def run_probe(*, project_root: str | Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(project_root).resolve()
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("probe_%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    run = RUNTIME_ROOT / run_id
    run.mkdir(parents=True, exist_ok=False)
    token = f"stage4f_c_repair2_{run_id}_{uuid.uuid4().hex}"
    payload_path = run / "responses" / "probe_payload.json"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = run / "logs" / "matlab_internal.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = build_isolated_environment(run)
    before = {key: os.environ.get(key) for key in ("TEMP", "TMP", "TMPDIR", "PREFDIR", "MATLAB_PREFDIR", "MATLAB_LOG_DIR", "LOCALAPPDATA", "USERPROFILE")}
    command = [str(MATLAB_CORE), "-batch", payload_expression(run_id=run_id, token=token, payload_path=payload_path)]
    record = {"purpose": "applicationservice_probe", "pid": None, "creation_time": None, "parent_pid": os.getpid(), "command_line": command, "cwd": str(run), "log": str(log_path), "closed": False, "return_code": None}
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result: dict[str, Any] = {"schema": "stage4f-c-applicationservice-repair-v2-result-1.0.0", "status": "environment_blocked", "run_id": run_id, "run_token": token, "runtime_root": str(run), "matlab_launcher": str(MATLAB_LAUNCHER), "matlab_core": str(MATLAB_CORE), "matlab_launcher_sha256": sha256_file(MATLAB_LAUNCHER), "matlab_core_sha256": sha256_file(MATLAB_CORE), "command": command, "started_utc": started, "environment_before": before, "environment_passed": {key: env.get(key) for key in ("TEMP", "TMP", "TMPDIR", "PREFDIR", "MATLAB_PREFDIR", "MATLAB_LOG_DIR", "LOCALAPPDATA", "PYTHONPYCACHEPREFIX")}, "owned_processes_started": [], "owned_processes_closed": [], "owned_process_residual": 0, "payload_validation": None, "openfoam_started": False}
    process: subprocess.Popen[str] | None = None
    try:
        with log_path.open("w", encoding="utf-8") as stream:
            process = subprocess.Popen(command, cwd=str(run), env=env, stdout=stream, stderr=subprocess.STDOUT, text=True, shell=False)
            record.update(_process_snapshot(process.pid))
            record["pid"] = process.pid
            result["owned_processes_started"].append(dict(record))
            result["return_code"] = process.wait(timeout=300.0)
            record["return_code"] = result["return_code"]
            record["closed"] = True
            result["owned_processes_closed"].append(dict(record))
    except subprocess.TimeoutExpired:
        result["block_reason"] = "probe_timeout"
        if process is not None:
            process.terminate()
            process.wait(timeout=30.0)
        record.update({"closed": True, "close_method": "terminate_after_timeout", "return_code": process.returncode if process else None})
    except OSError as exc:
        result["block_reason"] = "probe_launch_error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["owned_process_residual"] = int(process is not None and process.poll() is None)
    result["log_path"] = str(log_path)
    result["log_sha256"] = sha256_file(log_path)
    result["payload_path"] = str(payload_path)
    result["payload_sha256"] = sha256_file(payload_path)
    if payload_path.is_file():
        try:
            payload = read_payload(payload_path)
            result["payload_validation"] = validate_payload(payload, run=run, run_id=run_id, token=token, return_code=result.get("return_code"))
            if result["payload_validation"]["all_checks_passed"] and not result["owned_process_residual"]:
                result["status"] = "passed"
            else:
                result["block_reason"] = "structured_probe_checks_failed"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            result["block_reason"] = "invalid_probe_payload"
            result["error"] = f"{type(exc).__name__}: {exc}"
    else:
        result.setdefault("block_reason", "matlab_internal_failure_before_payload")
    result["c_drive_project_artifacts"] = _c_drive_hits(token)
    result["c_drive_project_artifact_count"] = len(result["c_drive_project_artifacts"])
    if result["c_drive_project_artifact_count"]:
        result["status"] = "environment_blocked"
        result["block_reason"] = "c_drive_project_artifact_detected"
    result["finished_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    (run / "applicationservice_probe_result.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS_ROOT / "applicationservice_probe_result.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_probe(), ensure_ascii=False, indent=2))
