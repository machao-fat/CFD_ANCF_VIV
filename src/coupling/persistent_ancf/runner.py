from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from src.coupling.runtime_hygiene import build_task_environment, create_runtime_run


class PersistentRunnerError(RuntimeError):
    pass


class WorkerExitedError(PersistentRunnerError):
    pass


class StaleResponseError(PersistentRunnerError):
    pass


def _finite(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _finite(item, f"{name}.{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item, f"{name}[]") for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise PersistentRunnerError(f"{name} contains NaN/Inf")
    return value


class PersistentANCFRunner:
    """Long-lived MATLAB worker for ANCF transaction operations.

    The worker is intentionally fail-closed: a timeout or process exit marks
    the runner unusable and no implicit MATLAB restart is attempted.
    """

    def __init__(
        self,
        *,
        config: Mapping[str, Any],
        matlab_exe: str | Path | None = None,
        request_dir: str | Path | None = None,
        timeout_s: float = 120.0,
        launch_command: Sequence[str] | None = None,
        process_environment: Mapping[str, str] | None = None,
        console_log_path: str | Path | None = None,
    ) -> None:
        self.config = dict(_finite(dict(config), "config"))
        self.matlab_exe = Path(
            matlab_exe
            if matlab_exe is not None
            else os.environ.get(
                "CFD_ANCF_MATLAB_EXE",
                r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe",
            )
        )
        if request_dir is None:
            project_root = Path(__file__).resolve().parents[3]
            run_dir = create_runtime_run(project_root, "persistent_ancf")
            request_dir = run_dir
        self.request_dir = Path(request_dir).resolve()
        if os.name == "nt" and self.request_dir.drive.upper() != "D:":
            raise PersistentRunnerError(f"request_dir must be on D:, got {self.request_dir}")
        self.request_root = self.request_dir / "requests"
        self.response_root = self.request_dir / "responses"
        self.process_registry_root = self.request_dir / "process_registry"
        self.process_registry_root.mkdir(parents=True, exist_ok=True)
        self._owned_registry_path = self.process_registry_root / "owned_process_registry.json"
        self._diagnostics_path = self.process_registry_root / "runner_diagnostics.json"
        for path in (self.request_root, self.response_root):
            path.mkdir(parents=True, exist_ok=True)
        self.process: subprocess.Popen[str] | None = None
        self._log_stream = None
        self.timeout_s = float(timeout_s)
        self._command_counter = 0
        self._operation_counter = 0
        self._last_state: dict[str, Any] | None = None
        self._last_response: dict[str, Any] | None = None
        self._failed = False
        self.start_count = 0
        self.command_history: list[dict[str, Any]] = []
        self.launch_command = tuple(str(item) for item in launch_command) if launch_command is not None else None
        self.process_environment = dict(process_environment) if process_environment is not None else None
        self.console_log_path = Path(console_log_path).resolve() if console_log_path is not None else self.request_dir / "matlab_persistent_worker.log"
        self._owned_registry: list[dict[str, Any]] = []
        self._last_cleanup_audit: dict[str, Any] = {"owned_pid_count_after": 0, "records": []}
        self._diagnostics: list[dict[str, Any]] = []
        self._write_owned_registry()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _write_owned_registry(self) -> None:
        payload = {
            "run_id": self.request_dir.name,
            "request_dir": str(self.request_dir),
            "registry_path": str(self._owned_registry_path),
            "records": self._owned_registry,
            "started_count": len(self._owned_registry),
            "started_pids": [int(item["pid"]) for item in self._owned_registry],
            "closed_count": sum(1 for item in self._owned_registry if item.get("status") == "closed"),
            "closed_pids": [int(item["pid"]) for item in self._owned_registry if item.get("status") == "closed"],
            "task_owned_residual_process_count": sum(1 for item in self._owned_registry if item.get("status") == "live"),
            "close_method": "terminate_then_kill_after_timeout",
        }
        self._owned_registry_path.write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _log_tail(self, limit: int = 4000) -> str:
        path = self.console_log_path
        try:
            return path.read_text(encoding="utf-8", errors="replace")[-limit:]
        except OSError:
            return ""

    def _record_diagnostic(self, *, action: str, status: str, error: BaseException | None = None) -> None:
        return_code = None
        owned_pid = self.worker_pid
        if self.process is not None:
            return_code = self.process.poll()
        event = {
            "timestamp_utc": self._utc_now(),
            "action": action,
            "status": status,
            "error_type": type(error).__name__ if error is not None else None,
            "error_message": str(error) if error is not None else None,
            "owned_pid": owned_pid,
            "owned_pids": [int(item["pid"]) for item in self._owned_registry],
            "return_code": return_code,
            "timeout_s": self.timeout_s,
            "matlab_executable": str(self.matlab_exe),
            "request_dir": str(self.request_dir),
            "log_path": str(self.console_log_path),
            "log_tail": self._log_tail(),
        }
        self._diagnostics.append(event)
        self._diagnostics_path.write_text(
            json.dumps({"run_id": self.request_dir.name, "events": self._diagnostics}, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _diagnostic_status(error: BaseException) -> str:
        if isinstance(error, TimeoutError):
            return "initialize_timeout"
        if isinstance(error, WorkerExitedError):
            return "worker_exited"
        if isinstance(error, StaleResponseError):
            return "stale_response"
        if isinstance(error, PersistentRunnerError):
            return "protocol_error"
        if isinstance(error, OSError):
            return "environment_unavailable"
        return "startup_error"

    @property
    def worker_pid(self) -> int | None:
        return None if self.process is None else int(self.process.pid)

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None and not self._failed

    def start(self) -> dict[str, Any]:
        if self._failed:
            error = PersistentRunnerError("runner is failed and cannot be restarted")
            self._record_diagnostic(action="start", status="protocol_error", error=error)
            raise error
        if self.process is not None:
            error = PersistentRunnerError("runner has already been started")
            self._record_diagnostic(action="start", status="protocol_error", error=error)
            raise error
        if not self.matlab_exe.is_file():
            error = PersistentRunnerError(f"MATLAB executable not found: {self.matlab_exe}")
            self._record_diagnostic(action="start", status="environment_unavailable", error=error)
            raise error
        if any(self.request_root.iterdir()) or any(self.response_root.iterdir()):
            error = StaleResponseError("request directory contains stale messages")
            self._record_diagnostic(action="start", status="stale_response", error=error)
            raise error
        root = Path(__file__).resolve().parents[3]
        worker_root = root / "src" / "coupling" / "persistent_ancf_matlab"
        ancf_root = root / "src" / "structure_ancf_matlab"
        self.request_dir.mkdir(parents=True, exist_ok=True)
        self.console_log_path.parent.mkdir(parents=True, exist_ok=True)
        log_stream = self.console_log_path.open("w", encoding="utf-8")
        self._log_stream = log_stream
        command = (
            f"persistent_ancf_worker('{self._matlab_quote(self.request_dir)}',"
            f"'{self._matlab_quote(ancf_root)}','{self._matlab_quote(worker_root)}')"
        )
        argv = list(self.launch_command) if self.launch_command is not None else [
            str(self.matlab_exe), "-batch", f"addpath(genpath('{self._matlab_quote(worker_root)}')); {command}"
        ]
        # Always enforce task-scoped D-drive directories, including when a
        # caller supplies additional environment entries for a fake worker.
        env = build_task_environment(self.request_dir, dict(self.process_environment or os.environ))
        initialized_successfully = False
        try:
            self.process = subprocess.Popen(
                argv, cwd=str(self.request_dir), stdout=log_stream, stderr=subprocess.STDOUT,
                text=True, env=env,
            )
            self._register_process(self.process.pid, purpose="matlab_worker_launcher")
            self.start_count += 1
            self._refresh_owned_registry()
            response = self._call("initialize", config=self.config)
            initialized_successfully = True
            self._record_diagnostic(action="initialize", status="success")
            return response
        except Exception as error:
            # Ordinary startup failures are recorded and re-raised.  The
            # finally block below owns cleanup for every exception class.
            self._failed = True
            self._record_diagnostic(action="initialize", status=self._diagnostic_status(error), error=error)
            raise
        finally:
            if not initialized_successfully:
                self._failed = True
                # Do not let cleanup mask the original exception, especially
                # KeyboardInterrupt/SystemExit.  The original exception is
                # re-raised by Python after this finally block completes.
                try:
                    self._cleanup_owned_process_tree()
                except Exception as cleanup_error:
                    self._record_diagnostic(
                        action="initialize_cleanup",
                        status="cleanup_error",
                        error=cleanup_error,
                    )
                finally:
                    self._close_log_stream()
                    self.process = None

    def _close_log_stream(self) -> None:
        if self._log_stream is not None:
            try:
                self._log_stream.close()
            finally:
                self._log_stream = None

    def _process_record(self, pid: int, purpose: str = "matlab_worker_child") -> dict[str, Any] | None:
        if psutil is None:
            return {"pid": int(pid), "creation_time": None, "parent_pid": None, "purpose": purpose}
        try:
            process = psutil.Process(int(pid))
            try:
                cwd = process.cwd()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
                cwd = ""
            return {
                "pid": int(process.pid),
                "creation_time": float(process.create_time()),
                "parent_pid": int(process.ppid()),
                "executable": process.exe() if process.is_running() else "",
                "command_line": process.cmdline() if process.is_running() else [],
                "cwd": cwd,
                "purpose": purpose,
                "status": "owned",
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None

    def _register_process(self, pid: int, *, purpose: str) -> None:
        record = self._process_record(pid, purpose)
        if record is not None and not any(item.get("pid") == record.get("pid") for item in self._owned_registry):
            record.update(
                {
                    "run_id": self.request_dir.name,
                    "registered_at_utc": self._utc_now(),
                    "log_path": str(self.console_log_path),
                    "close_method": "terminate_then_kill_after_timeout",
                }
            )
            self._owned_registry.append(record)
            self._write_owned_registry()

    def _refresh_owned_registry(self) -> None:
        if self.process is None or psutil is None:
            return
        try:
            root = psutil.Process(self.process.pid)
            for child in root.children(recursive=True):
                self._register_process(child.pid, purpose="matlab_worker_child")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return

    @staticmethod
    def _same_identity(record: Mapping[str, Any]) -> bool:
        if psutil is None or record.get("creation_time") is None:
            return True
        try:
            process = psutil.Process(int(record["pid"]))
            return abs(float(process.create_time()) - float(record["creation_time"])) < 1e-3
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def _safe_to_cleanup(self, record: Mapping[str, Any], owned_pids: set[int]) -> bool:
        if not self._same_identity(record):
            return False
        if psutil is None:
            return True
        try:
            process = psutil.Process(int(record["pid"]))
            recorded_parent = record.get("parent_pid")
            current_parent = int(process.ppid())
            # The launcher is the tree root. Children may be reparented by the
            # OS after the launcher exits, but they remain owned if their
            # recorded parent was in this registry.
            if self.process is not None and int(record["pid"]) == int(self.process.pid):
                return True
            return current_parent == int(recorded_parent or -1) or current_parent in owned_pids
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, TypeError, ValueError):
            return False

    def _cleanup_owned_process_tree(self) -> dict[str, Any]:
        # A worker can fork its owned helper immediately before a bounded
        # initialize timeout.  Give the already-owned launcher a short,
        # deterministic discovery window before terminating it; this avoids
        # losing a child to OS reparenting without scanning or killing any
        # unrelated process.
        discovery_deadline = time.monotonic() + 0.25
        while True:
            self._refresh_owned_registry()
            if self.process is None or self.process.poll() is not None or time.monotonic() >= discovery_deadline:
                break
            time.sleep(0.01)
        records = list(self._owned_registry)
        actions: list[dict[str, Any]] = []
        owned_pids = {int(item["pid"]) for item in records}
        if psutil is not None:
            eligible = []
            for record in records:
                try:
                    process = psutil.Process(int(record["pid"]))
                except psutil.NoSuchProcess:
                    actions.append({"pid": record["pid"], "action": "already_exited"})
                    continue
                except psutil.AccessDenied as exc:
                    actions.append({"pid": record["pid"], "action": "cleanup_blocked_access_denied", "detail": str(exc)})
                    continue
                except psutil.ZombieProcess:
                    actions.append({"pid": record["pid"], "action": "already_exited"})
                    continue
                try:
                    if abs(float(process.create_time()) - float(record.get("creation_time"))) >= 1e-3:
                        actions.append({"pid": record["pid"], "action": "refused_identity_mismatch"})
                        continue
                except psutil.AccessDenied as exc:
                    actions.append({"pid": record["pid"], "action": "cleanup_blocked_access_denied", "detail": str(exc)})
                    continue
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    actions.append({"pid": record["pid"], "action": "already_exited"})
                    continue
                if not self._safe_to_cleanup(record, owned_pids):
                    actions.append({"pid": record["pid"], "action": "refused_identity_mismatch"})
                    continue
                eligible.append(record)
            # Children first: terminating the launcher can otherwise reparent
            # them before the owned identity check is complete.
            for record in reversed(eligible):
                try:
                    process = psutil.Process(int(record["pid"]))
                    if process.is_running():
                        process.terminate()
                        actions.append({"pid": record["pid"], "action": "terminate"})
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
                    actions.append({"pid": record["pid"], "action": "already_gone", "detail": str(exc)})
            live = []
            for record in eligible:
                try:
                    process = psutil.Process(int(record["pid"]))
                    process.wait(timeout=2.0)
                except psutil.TimeoutExpired:
                    try:
                        process.kill()
                        process.wait(timeout=2.0)
                        actions.append({"pid": record["pid"], "action": "kill_after_timeout"})
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired) as exc:
                        actions.append({"pid": record["pid"], "action": "kill_failed", "detail": str(exc)})
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
                try:
                    if psutil.Process(int(record["pid"])).is_running():
                        live.append(int(record["pid"]))
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        elif self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5.0)
            live = []
        else:
            live = []
        for record in self._owned_registry:
            record["status"] = "live" if record.get("pid") in live else "closed"
        if self.process is not None:
            try:
                self.process.wait(timeout=0.1)
            except (subprocess.TimeoutExpired, ChildProcessError):
                pass
        self._last_cleanup_audit = {
            "records": records,
            "actions": actions,
            "owned_pid_count_after": len(live),
            "owned_pids_after": live,
        }
        self._write_owned_registry()
        return dict(self._last_cleanup_audit)

    @property
    def owned_process_records(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._owned_registry]

    @property
    def cleanup_audit(self) -> dict[str, Any]:
        return dict(self._last_cleanup_audit)

    @staticmethod
    def _matlab_quote(path: Path) -> str:
        return str(path.resolve()).replace("\\", "/").replace("'", "''")

    def _require_alive(self) -> None:
        if self.process is None:
            raise PersistentRunnerError("runner has not been started")
        if self.process.poll() is not None:
            self._failed = True
            raise WorkerExitedError(f"MATLAB worker exited with code {self.process.returncode}")
        if self._failed:
            raise PersistentRunnerError("runner is failed and cannot be reused")

    def _call(self, action: str, *, command_id: str | None = None, operation_id: str | None = None, raise_on_error: bool = True, **payload: Any) -> dict[str, Any]:
        self._require_alive()
        if command_id is None:
            self._command_counter += 1
            command_id = f"cmd_{self._command_counter:08d}_{uuid.uuid4().hex[:8]}"
        if operation_id is None:
            self._operation_counter += 1
            operation_id = f"op_{self._operation_counter:08d}"
        response_path = self.response_root / f"response_{command_id}.json"
        if response_path.exists():
            raise StaleResponseError(f"response already exists for command_id {command_id}")
        request = {"command_id": command_id, "operation_id": operation_id, "action": action, **_finite(payload, action)}
        request_path = self.request_root / f"request_{command_id}.json"
        if request_path.exists():
            raise PersistentRunnerError(f"duplicate pending command_id {command_id}")
        temporary = request_path.with_name(f".{request_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        temporary.write_text(json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, request_path)
        self.command_history.append({"command_id": command_id, "operation_id": operation_id, "action": action, "sent_ns": time.time_ns()})
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() <= deadline:
            if response_path.is_file():
                try:
                    response = json.loads(response_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    time.sleep(0.01)
                    continue
                if str(response.get("command_id")) != command_id or str(response.get("operation_id")) != operation_id:
                    self._failed = True
                    raise StaleResponseError(f"response identity mismatch for {command_id}")
                response["worker_pid"] = int(self.process.pid) if self.process is not None else response.get("worker_pid")
                response["command_id"] = command_id
                response["operation_id"] = operation_id
                self._last_response = response
                self._refresh_owned_registry()
                if response.get("status") == "error" and raise_on_error:
                    raise PersistentRunnerError(f"{response.get('error_code','worker_error')}: {response.get('message','')}")
                if response.get("status") == "complete":
                    self._cache_state(response)
                return response
            if self.process is not None and self.process.poll() is not None:
                self._failed = True
                raise WorkerExitedError(f"MATLAB worker exited with code {self.process.returncode}")
            self._refresh_owned_registry()
            time.sleep(0.01)
        self._failed = True
        raise TimeoutError(f"timeout waiting for persistent ANCF action {action}")

    def _cache_state(self, response: Mapping[str, Any]) -> None:
        if all(key in response for key in ("q", "qdot", "qddot", "time_s")):
            state = {key: list(map(float, response[key])) for key in ("q", "qdot", "qddot")}
            state["t"] = float(response["time_s"])
            state["step"] = int(response.get("global_step", response.get("step", -1)))
            for key in ("newton_iterations", "newton_residual", "min_tension_N", "max_tension_N", "converged"):
                if key in response:
                    state[key] = response[key]
            self._last_state = state

    def state_view(self) -> dict[str, list[float]]:
        if self._last_state is None:
            raise PersistentRunnerError("worker has not returned a state")
        return {key: list(self._last_state[key]) for key in ("q", "qdot", "qddot")}

    def predict(self, step: int, time_s: float, load: Sequence[Sequence[float]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        response = self._call("predict", step=int(step), time_s=float(time_s), load=load)
        return response, list(response.get("motion", []))

    def correct(self, step: int, time_s: float, load: Sequence[Sequence[float]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        response = self._call("correct", step=int(step), time_s=float(time_s), load=load)
        return response, list(response.get("motion", []))

    def get_state(self, view: str = "committed") -> dict[str, Any]:
        return self._call("get_state", view=view)

    def heartbeat(self) -> dict[str, Any]:
        return self._call("heartbeat")

    def prepare_checkpoint(self, path: str | Path) -> dict[str, Any]:
        return self._call("prepare_checkpoint", path=str(Path(path).resolve()))

    def save_checkpoint(self, path: str | Path) -> dict[str, Any]:
        return self._call("save_checkpoint", path=str(Path(path).resolve()))

    def finalize_commit(self, checkpoint_token: str | None = None) -> dict[str, Any]:
        token = checkpoint_token or str((self._last_response or {}).get("checkpoint_token", ""))
        return self._call("finalize_commit", checkpoint_token=token)

    def discard_staged(self) -> dict[str, Any]:
        return self._call("discard_staged")

    def load_checkpoint(self, path: str | Path) -> dict[str, Any]:
        return self._call("load_checkpoint", path=str(Path(path).resolve()))

    def shutdown(self) -> None:
        try:
            if self.process is not None and self.process.poll() is None and not self._failed:
                self._call("shutdown")
        except (TimeoutError, WorkerExitedError, PersistentRunnerError, subprocess.TimeoutExpired):
            pass
        finally:
            self._cleanup_owned_process_tree()
            self.process = None
            self._close_log_stream()

    def __enter__(self) -> "PersistentANCFRunner":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown()
