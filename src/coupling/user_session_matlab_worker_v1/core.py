from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable


class WorkerContractError(RuntimeError):
    """Fail-closed worker contract or lifecycle error."""


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def contract_hash(contract: dict[str, Any]) -> str:
    payload = {key: value for key, value in contract.items() if key not in {"contract_sha256", "contract_hash"}}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_bytes(canonical_bytes(value)); os.replace(temporary, path)


def validate_worker_contract(contract: dict[str, Any], project_root: Path) -> list[str]:
    required = {"contract_version", "run_id", "case_id", "stage_id", "contract_sha256", "expected_session_id",
                "expected_username", "matlab_executable", "expected_release", "expected_architecture", "runtime",
                "request_dir", "response_dir", "no_cfd", "no_openfoam", "no_wsl", "no_retry", "worker_only"}
    errors = [f"missing:{key}" for key in sorted(required - contract.keys())]
    if errors:
        return errors
    if contract.get("contract_sha256") != contract_hash(contract): errors.append("contract_hash_mismatch")
    if contract.get("expected_session_id") != 1: errors.append("session_id_must_be_1")
    if contract.get("expected_username") != "Administrator": errors.append("username_must_be_Administrator")
    for key in ("no_cfd", "no_openfoam", "no_wsl", "no_retry", "worker_only"):
        if contract.get(key) is not True: errors.append(f"{key}_must_be_true")
    if contract.get("expected_release") != "2021b": errors.append("release_must_be_2021b")
    if contract.get("expected_architecture") != "win64": errors.append("architecture_must_be_win64")
    root = project_root.resolve()
    runtime = Path(str(contract["runtime"])).resolve()
    if runtime.drive.upper() != "D:": errors.append("runtime_must_be_on_D")
    if root not in runtime.parents and runtime != root: errors.append("runtime_outside_project")
    for key in ("request_dir", "response_dir"):
        path = Path(str(contract[key])).resolve()
        if path.drive.upper() != "D:": errors.append(f"{key}_must_be_on_D")
        if root not in path.parents and path != root: errors.append(f"{key}_outside_project")
    if not str(contract["matlab_executable"]).lower().endswith("matlab.exe"): errors.append("invalid_matlab_executable")
    return errors


class UserSessionWorker:
    """Contract processor for a MATLAB worker owned by the interactive user session."""

    def __init__(self, *, project_root: Path, runtime: Path,
                 launcher: Callable[..., Any] | None = None) -> None:
        self.project_root = project_root.resolve(); self.runtime = runtime.resolve(); self.launcher = launcher or subprocess.Popen
        for name in ("inbox", "accepted", "running", "completed", "failed", "status", "logs", "process"):
            (self.runtime / name).mkdir(parents=True, exist_ok=True)
        self.status_path = self.runtime / "status" / "runner_status.json"
        self.events_path = self.runtime / "logs" / "events.jsonl"
        self.process: Any = None; self.current: dict[str, Any] | None = None; self.state = "STARTING"
        self._event("STARTING", "worker contract runner created")

    def _event(self, state: str, message: str, error: str | None = None) -> None:
        self.state = state
        event = {"timestamp": time.time(), "state": state, "run_id": (self.current or {}).get("run_id"),
                 "contract_hash": (self.current or {}).get("contract_sha256"), "pid": os.getpid(),
                 "message": message, "error_classification": error}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        atomic_json(self.status_path, {"state": self.state, "pid": os.getpid(), "run_id": (self.current or {}).get("run_id"),
                                       "contract_sha256": (self.current or {}).get("contract_sha256"),
                                       "matlab_pid": getattr(self.process, "pid", None), "owned_residual": int(self.process is not None),
                                       "runtime": str(self.runtime)})

    def accept(self, path: Path, *, launch: bool = False) -> dict[str, Any]:
        contract = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_worker_contract(contract, self.project_root)
        if errors:
            result = {"run_id": contract.get("run_id", "unknown"), "gate": "do_not_pass", "state": "CONTRACT_REJECTED", "errors": errors}
            atomic_json(self.runtime / "failed" / f"{result['run_id']}.json", result); self._event("CONTRACT_REJECTED", ";".join(errors), "contract_validation"); return result
        if any((self.runtime / folder / f"{contract['run_id']}.json").exists() for folder in ("accepted", "running", "completed", "failed")):
            raise WorkerContractError("duplicate run_id")
        self.current = contract; accepted = self.runtime / "accepted" / path.name; os.replace(path, accepted)
        if not launch:
            result = {"run_id": contract["run_id"], "gate": "offline_contract_validated", "state": "IDLE_WAITING_FOR_USER_LAUNCH", "external_process_starts": 0, "owned_residual": 0}
            atomic_json(self.runtime / "completed" / f"{contract['run_id']}.json", result); self._event("IDLE_WAITING_FOR_USER_LAUNCH", "contract validated; launch disabled"); return result
        self._event("MATLAB_WORKER_STARTING", "launching MATLAB in user session")
        request_dir = Path(contract["request_dir"]); request_dir.mkdir(parents=True, exist_ok=True)
        log = self.runtime / "logs" / f"matlab_worker_{contract['run_id']}.log"
        command = [str(contract["matlab_executable"]), "-batch", str(contract.get("matlab_batch_command", "exit"))]
        self.process = self.launcher(command, cwd=str(self.runtime), stdout=log.open("w", encoding="utf-8"), stderr=subprocess.STDOUT)
        atomic_json(self.runtime / "process" / f"{contract['run_id']}.json", {"pid": self.process.pid, "owned": True, "command_line": command, "cwd": str(self.runtime), "start_time_ns": time.time_ns()})
        self._event("MATLAB_WORKER_RUNNING", "MATLAB worker started")
        return {"run_id": contract["run_id"], "gate": "worker_started", "state": "MATLAB_WORKER_RUNNING", "matlab_pid": self.process.pid, "external_process_starts": 1}

    def stop(self) -> dict[str, Any]:
        if self.process is not None:
            self.process.terminate(); self.process.wait(timeout=30); self.process = None
        self._event("CLEANUP_COMPLETE", "owned MATLAB worker closed")
        self._event("STOPPED", "worker runner stopped")
        return {"state": "STOPPED", "owned_residual": 0}
