from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .contracts import ContractError, validate_serialized_contract


class SessionRunnerError(RuntimeError):
    """Fail-closed user-session runner error."""


class BenchmarkSessionRunner:
    """Minimal owner for one bounded Stage95 contract.

    The runner is intended to be started by the user in SessionId=1. It does
    not discover or kill unrelated processes, and it never retries a failed
    runtime. OpenFOAM/WSL orchestration remains explicit and is rejected until
    a coordinator command is supplied in a future, audited implementation.
    """

    def __init__(self, *, project_root: Path, runtime: Path,
                 launcher: Callable[..., Any] | None = None,
                 session_id: int = 1, username: str = "Administrator",
                 sessionname: str = "Console") -> None:
        self.project_root = project_root.resolve(); self.runtime = runtime.resolve()
        self.launcher = launcher or subprocess.Popen
        self.session_id, self.username, self.sessionname = int(session_id), username, sessionname
        self.process: Any = None; self.stream: Any = None; self.current: dict[str, Any] | None = None; self.failed = False
        for name in ("inbox", "accepted", "running", "completed", "failed", "status", "logs", "process"):
            (self.runtime / name).mkdir(parents=True, exist_ok=True)
        for name in ("temp", "tmp", "tmpdir", "prefdir"):
            (self.runtime / name).mkdir(parents=True, exist_ok=True)
        self.status_path = self.runtime / "status" / "runner_status.json"
        self.events_path = self.runtime / "logs" / "events.jsonl"
        self.write_status("STARTING", "Stage95 runner created")

    def _atomic(self, path: Path, value: Any) -> None:
        temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def write_status(self, state: str, message: str, error: str | None = None) -> None:
        event = {"timestamp": time.time(), "state": state, "run_id": (self.current or {}).get("run_id"),
                 "contract_sha256": (self.current or {}).get("contract_sha256"), "pid": os.getpid(),
                 "session_id": self.session_id, "username": self.username, "sessionname": self.sessionname,
                 "message": message, "error_classification": error}
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        is_coordinator = bool((self.current or {}).get("coordinator_command"))
        self._atomic(self.status_path, {**event, "runtime": str(self.runtime),
                                        "matlab_pid": getattr(self.process, "pid", None) if not is_coordinator else None,
                                        "coordinator_pid": getattr(self.process, "pid", None) if is_coordinator else None,
                                        "owned_residual": int(self.process is not None)})

    def accept(self, contract_path: Path, *, launch_matlab: bool = False) -> dict[str, Any]:
        if self.process is not None or self.failed:
            raise SessionRunnerError("runner is already busy or terminal")
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            validate_serialized_contract(contract, self.project_root)
            if self.session_id != int(contract["expected_session_id"]): raise ContractError("SessionId mismatch")
            if self.username != contract["expected_username"] or self.sessionname != "Console": raise ContractError("user session mismatch")
            runtime = Path(contract["runtime"]).resolve()
            benchmark_root = (self.runtime / "benchmarks").resolve()
            if benchmark_root not in runtime.parents:
                raise ContractError("contract runtime must be a fresh child of runner benchmarks")
            if runtime == self.runtime:
                raise ContractError("benchmark runtime cannot be the runner control runtime")
            if any((self.runtime / folder / f"{contract['run_id']}.json").exists() for folder in ("accepted", "running", "completed", "failed")):
                raise ContractError("duplicate run_id")
        except (OSError, ValueError, ContractError) as exc:
            self.failed = True; result = {"state": "CONTRACT_REJECTED", "gate": "do_not_pass", "error": str(exc)}
            self._atomic(self.runtime / "failed" / f"rejected_{int(time.time())}.json", result); self.write_status("CONTRACT_REJECTED", str(exc), "contract_validation"); return result
        self.current = contract; accepted = self.runtime / "accepted" / contract_path.name; os.replace(contract_path, accepted)
        self._atomic(self.runtime / "running" / f"{contract['run_id']}.json", contract)
        if not launch_matlab:
            result = {"state": "IDLE_WAITING_FOR_USER_AUTHORIZATION", "gate": "offline_contract_validated", "run_id": contract["run_id"], "external_process_starts": 0, "owned_residual": 0}
            self._atomic(self.runtime / "completed" / f"{contract['run_id']}.json", result); self.write_status(result["state"], "contract validated; launch disabled"); return result
        coordinator = contract.get("coordinator_command")
        executable = contract.get("matlab_executable")
        command = contract.get("matlab_batch_command")
        if coordinator:
            command_line = [str(item) for item in coordinator]
            component = "benchmark_coordinator"
        else:
            if set(contract.get("factors", [])) - {"M"}:
                self.failed = True; result = {"state": "FAILED_TERMINAL", "gate": "do_not_pass", "run_id": contract["run_id"], "error": "O/P factors require an explicit user-session coordinator command"}
                self._atomic(self.runtime / "failed" / f"{contract['run_id']}.json", result); self.write_status("FAILED_TERMINAL", result["error"], "unsupported_external_coordinator"); return result
            if not executable or not command:
                self.failed = True; result = {"state": "FAILED_TERMINAL", "gate": "do_not_pass", "run_id": contract["run_id"], "error": "MATLAB executable/worker command missing"}
                self._atomic(self.runtime / "failed" / f"{contract['run_id']}.json", result); self.write_status("FAILED_TERMINAL", result["error"], "contract_validation"); return result
            command_line = [str(executable), "-batch", str(command)]
            component = "matlab_worker"
        job_runtime = Path(contract["runtime"]).resolve()
        for name in ("logs", "process", "temp", "tmp", "tmpdir", "prefdir"):
            (job_runtime / name).mkdir(parents=True, exist_ok=True)
        log_path = job_runtime / "logs" / f"coordinator_{contract['run_id']}.log"
        env = dict(os.environ); env.update({name.upper(): str(self.runtime / name.lower()) for name in ("TEMP", "TMP", "TMPDIR", "PREFDIR")})
        env.update({name.upper(): str(job_runtime / name.lower()) for name in ("TEMP", "TMP", "TMPDIR", "PREFDIR")})
        env.update({"CFD_ANCF_BENCHMARK_RUNTIME": str(job_runtime), "CFD_ANCF_BENCHMARK_CONTRACT": str(accepted),
                    "CFD_ANCF_BENCHMARK_RUN_ID": str(contract["run_id"]), "CFD_ANCF_BENCHMARK_CASE_ID": str(contract["case_id"])})
        env["PYTHONPATH"] = str(self.project_root / "src") + os.pathsep + env.get("PYTHONPATH", "")
        command_cwd = self.project_root if coordinator else self.runtime
        stream = log_path.open("w", encoding="utf-8"); self.stream = stream
        self.process = self.launcher(command_line, cwd=str(command_cwd), env=env, stdout=stream, stderr=subprocess.STDOUT)
        self._atomic(job_runtime / "process" / f"{contract['run_id']}.json", {"component": component, "pid": self.process.pid, "owned": True, "creation_time_ns": time.time_ns(), "parent_pid": os.getpid(), "command_line": command_line, "cwd": str(command_cwd)})
        state = "BENCHMARK_COORDINATOR_RUNNING" if coordinator else "MATLAB_WORKER_RUNNING"
        self.write_status(state, f"{component} started in user session")
        return {"state": state, "gate": "worker_started", "run_id": contract["run_id"], "matlab_pid": self.process.pid if not coordinator else None, "coordinator_pid": self.process.pid if coordinator else None}

    def stop(self) -> dict[str, Any]:
        if self.process is not None:
            self.process.terminate(); self.process.wait(timeout=30); self.process = None
        if self.stream is not None:
            self.stream.close(); self.stream = None
        self.write_status("CLEANUP_COMPLETE", "owned MATLAB worker closed")
        self.write_status("STOPPED", "Stage95 runner stopped")
        return {"state": "STOPPED", "owned_residual": 0}
