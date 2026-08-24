from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

STATES = {
    "STARTING", "IDLE_WAITING_FOR_CONTRACT", "CONTRACT_REJECTED",
    "PREFLIGHT_RUNNING", "MATLAB_PROBE_RUNNING", "MATLAB_PROBE_FAILED",
    "MATLAB_READY", "TASK_RUNNING", "BLOCK_COMPLETE",
    "AUTHORIZED_WINDOW_COMPLETE", "FAILED_TERMINAL", "CLEANUP_COMPLETE", "STOPPED",
}


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def contract_payload(contract: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in contract.items() if k not in {"contract_sha256", "contract_hash"}}


def contract_hash(contract: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(contract_payload(contract)))


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_bytes(canonical_bytes(value))
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_probe_contract(contract: dict[str, Any], project_root: Path) -> list[str]:
    errors: list[str] = []
    required = {
        "contract_version", "run_id", "case_id", "stage_id", "expected_session_id",
        "expected_username", "expected_matlab_executable", "expected_release",
        "expected_architecture", "expected_license", "runtime", "TEMP", "TMP",
        "TMPDIR", "PREFDIR", "no_cfd", "no_correction", "no_openfoam", "no_wsl",
        "no_retry", "contract_sha256",
    }
    errors.extend(f"missing:{key}" for key in sorted(required - contract.keys()))
    if errors:
        return errors
    if contract.get("contract_sha256") != contract_hash(contract):
        errors.append("contract_hash_mismatch")
    if contract.get("expected_session_id") != 1:
        errors.append("expected_session_id_must_be_1")
    if contract.get("expected_username") != "Administrator":
        errors.append("expected_username_must_be_Administrator")
    for key in ("no_cfd", "no_correction", "no_openfoam", "no_wsl", "no_retry"):
        if contract.get(key) is not True:
            errors.append(f"{key}_must_be_true")
    if contract.get("expected_release") != "2021b":
        errors.append("release_must_be_2021b")
    if contract.get("expected_architecture") != "win64":
        errors.append("architecture_must_be_win64")
    runtime = Path(str(contract["runtime"])).resolve()
    root = project_root.resolve()
    if runtime.drive.upper() != "D:":
        errors.append("runtime_must_be_on_D")
    if not (str(runtime).lower().startswith(str(root).lower())):
        errors.append("runtime_outside_project")
    for key in ("TEMP", "TMP", "TMPDIR", "PREFDIR"):
        if Path(str(contract[key])).drive.upper() != "D:":
            errors.append(f"{key}_must_be_on_D")
    if not str(contract["expected_matlab_executable"]).lower().endswith("matlab.exe"):
        errors.append("invalid_matlab_executable")
    return errors


def session_snapshot() -> dict[str, Any]:
    return {
        "username": os.environ.get("USERNAME", ""),
        "sessionname": os.environ.get("SESSIONNAME", ""),
        "session_id": int(os.environ.get("SESSIONID", "1")) if os.environ.get("SESSIONID", "1").isdigit() else None,
        "platform": platform.platform(),
        "pid": os.getpid(),
    }


class SessionRunner:
    def __init__(self, project_root: Path, runtime: Path):
        self.project_root = project_root.resolve()
        self.runtime = runtime.resolve()
        self.runtime.mkdir(parents=True, exist_ok=True)
        for name in ("inbox", "accepted", "running", "completed", "failed", "status", "logs", "process"):
            (self.runtime / name).mkdir(exist_ok=True)
        self.status_path = self.runtime / "status" / "runner_status.json"
        self.events_path = self.runtime / "logs" / "events.jsonl"
        self.stop_path = self.runtime / "status" / "stop.request"
        self.state = "STARTING"
        self.current_contract: dict[str, Any] | None = None
        self.current_result: dict[str, Any] | None = None
        self._write_status()

    def _event(self, state: str, message: str, error_classification: str | None = None) -> None:
        self.state = state
        event = {"timestamp": time.time(), "state": state, "run_id": (self.current_contract or {}).get("run_id"), "contract_hash": (self.current_contract or {}).get("contract_sha256"), "pid": os.getpid(), "message": message, "error_classification": error_classification}
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        self._write_status()

    def _write_status(self) -> None:
        atomic_write_json(self.status_path, {"state": self.state, "pid": os.getpid(), "session": session_snapshot(), "start_time": getattr(self, "start_time", time.time()), "current_contract": self.current_contract, "current_run_id": (self.current_contract or {}).get("run_id"), "matlab_pid": None, "openfoam_pid": None, "wsl_pid": None, "last_event": self.state, "last_error": None, "residual_count": 0, "runtime": str(self.runtime)})

    def _result(self, result: dict[str, Any], failed: bool = False) -> None:
        folder = self.runtime / ("failed" if failed else "completed")
        atomic_write_json(folder / f"{result['run_id']}.json", result)
        atomic_write_json(self.runtime / "status" / "last_result.json", result)
        self.current_result = result

    def process_contract(self, path: Path) -> None:
        self._event("PREFLIGHT_RUNNING", "contract discovered")
        try:
            contract = read_json(path)
            errors = validate_probe_contract(contract, self.project_root)
            if errors:
                result = {"run_id": contract.get("run_id", "unknown"), "gate": "do_not_pass", "state": "CONTRACT_REJECTED", "errors": errors}
                self._result(result, failed=True)
                self._event("CONTRACT_REJECTED", ";".join(errors), "contract_validation")
                return
            self.current_contract = contract
            accepted = self.runtime / "accepted" / path.name
            os.replace(path, accepted)
            self._event("MATLAB_PROBE_RUNNING", "probe-only contract accepted")
            result = self._run_probe(contract)
            self._result(result, failed=result["gate"] != "pass")
            self._event("MATLAB_READY" if result["gate"] == "pass" else "MATLAB_PROBE_FAILED", result.get("message", "probe complete"), None if result["gate"] == "pass" else "matlab_probe")
        except Exception as exc:
            result = {"run_id": (self.current_contract or {}).get("run_id", "unknown"), "gate": "do_not_pass", "state": "FAILED_TERMINAL", "error": repr(exc)}
            self._result(result, failed=True)
            self._event("FAILED_TERMINAL", repr(exc), "runner_exception")

    def _run_probe(self, contract: dict[str, Any]) -> dict[str, Any]:
        exe = str(contract["expected_matlab_executable"])
        result: dict[str, Any] = {"run_id": contract["run_id"], "stage_id": contract["stage_id"], "contract_sha256": contract["contract_sha256"], "no_cfd": True, "no_correction": True, "no_openfoam": True, "no_wsl": True, "started_processes": 0, "owned_residual": 0, "applicationservice_evidence": "not_collected"}
        if not Path(exe).exists():
            result.update({"gate": "do_not_pass", "state": "MATLAB_PROBE_FAILED", "message": "MATLAB executable not found", "return_code": None})
            return result
        env = os.environ.copy()
        for key in ("TEMP", "TMP", "TMPDIR", "PREFDIR"):
            env[key] = str(contract[key])
        log = self.runtime / "logs" / f"matlab_probe_{contract['run_id']}.log"
        # Probe is intentionally the only subprocess this runner may launch in this phase.
        command = [exe, "-batch", "disp(version('-release')); disp(computer('arch')); disp(license('test','MATLAB')); exit"]
        try:
            start_ns = time.time_ns()
            proc = subprocess.Popen(command, cwd=str(self.runtime), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            result["started_processes"] = 1
            result["matlab_pid"] = proc.pid
            result["matlab_creation_time_ns"] = start_ns
            result["matlab_parent_pid"] = os.getpid()
            result["matlab_command_line"] = command
            result["matlab_cwd"] = str(self.runtime)
            result["probe_environment"] = {key: env[key] for key in ("TEMP", "TMP", "TMPDIR", "PREFDIR")}
            try:
                stdout, stderr = proc.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                result.update({"return_code": None, "timeout": True, "gate": "do_not_pass", "state": "MATLAB_PROBE_FAILED", "message": "MATLAB probe timeout", "stderr": stderr or "", "stdout": stdout or "", "log": str(log), "owned_residual": 0})
                log.write_text((stdout or "") + "\n--- STDERR ---\n" + (stderr or ""), encoding="utf-8")
                return result
            end_ns = time.time_ns()
            log.write_text((stdout or "") + "\n--- STDERR ---\n" + (stderr or ""), encoding="utf-8")
            license_ok = any(line.strip() == "1" for line in stdout.splitlines())
            result.update({"return_code": proc.returncode, "end_time_ns": end_ns, "stdout": stdout or "", "stderr": stderr or "", "log": str(log), "release": "2021b" if "2021b" in stdout else None, "architecture": "win64" if "win64" in stdout else None, "license": 1 if license_ok else 0})
            good = proc.returncode == 0 and result["release"] == "2021b" and result["architecture"] == "win64" and result["license"] == 1
            result.update({"gate": "pass" if good else "do_not_pass", "state": "MATLAB_READY" if good else "MATLAB_PROBE_FAILED", "message": "probe passed" if good else "probe validation failed"})
        except Exception as exc:
            result.update({"gate": "do_not_pass", "state": "MATLAB_PROBE_FAILED", "message": repr(exc), "return_code": None})
        return result

    def run(self) -> None:
        self.start_time = time.time()
        self._event("IDLE_WAITING_FOR_CONTRACT", "runner ready; no CFD commands are accepted")
        while not self.stop_path.exists():
            contracts = sorted((self.runtime / "inbox").glob("*.json"))
            for path in contracts:
                self.process_contract(path)
            time.sleep(0.5)
        self._event("CLEANUP_COMPLETE", "no owned child processes")
        self._event("STOPPED", "runner stopped")


def make_probe_contract(project_root: Path, runtime: Path) -> dict[str, Any]:
    payload = {"contract_version": "user-session-runner.1", "run_id": f"probe_only_{int(time.time())}", "case_id": "probe_only", "stage_id": "stage4f_d_user_session_runner_v1", "expected_session_id": 1, "expected_username": "Administrator", "expected_matlab_executable": r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe", "expected_release": "2021b", "expected_architecture": "win64", "expected_license": 1, "runtime": str(runtime), "TEMP": str(runtime / "temp"), "TMP": str(runtime / "tmp"), "TMPDIR": str(runtime / "tmpdir"), "PREFDIR": str(runtime / "prefdir"), "no_cfd": True, "no_correction": True, "no_openfoam": True, "no_wsl": True, "no_retry": True}
    payload["contract_sha256"] = contract_hash(payload)
    return payload
