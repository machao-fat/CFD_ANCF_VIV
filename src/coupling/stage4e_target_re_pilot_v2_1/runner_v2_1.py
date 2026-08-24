"""Owned OpenFOAM runner with incremental online CFL hard stopping."""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from src.coupling.process_control.process_limiter import ProcessLimiter

from src.coupling.stage4e_target_re_pilot_v2.identity_v2 import finite
from .online_cfl_monitor import IncrementalCFLMonitor


def wsl_path(path: Path) -> str:
    resolved = str(path.resolve()).replace("\\", "/")
    if len(resolved) < 2 or resolved[1] != ":":
        raise ValueError(f"expected Windows drive path: {path}")
    return "/mnt/" + resolved[0].lower() + resolved[2:]


def process_snapshot() -> list[dict[str, Any]]:
    if psutil is None:
        return []
    rows: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "create_time", "cmdline"]):
        try:
            info = proc.info
            rows.append({"pid": int(info["pid"]), "parent_pid": int(info.get("ppid") or 0), "creation_time_utc": datetime.fromtimestamp(float(info["create_time"]), timezone.utc).isoformat(), "name": info.get("name"), "command_line": list(info.get("cmdline") or [])})
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
            continue
    return rows


def _descendants(pid: int) -> list[int]:
    if psutil is None:
        return []
    try:
        return [int(child.pid) for child in psutil.Process(pid).children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


class OwnedRunnerV21:
    def __init__(self, limiter: ProcessLimiter, registry: list[dict[str, Any]], runtime_root: Path, run_id: str) -> None:
        self.limiter = limiter
        self.registry = registry
        self.runtime_root = runtime_root
        self.run_id = run_id
        self.step_counter = 0

    def _persist_registry(self) -> None:
        payload = {"schema_version": "stage4e-b2-a-v2.1-owned-process-registry-0.1.0", "run_id": self.run_id, "updated_utc": datetime.now(timezone.utc).isoformat(), "processes": self.registry}
        (self.runtime_root / "owned_process_registry.json").write_text(json.dumps(finite(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _kill_exact_tree(self, pid: int, managed: Any, *, hard_stop: bool = False) -> None:
        descendants = _descendants(pid)
        managed.terminate()
        if psutil is not None:
            for child_pid in descendants:
                try:
                    child = psutil.Process(child_pid)
                    if child.is_running():
                        child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        try:
            managed.wait(timeout=10.0)
        except TimeoutError:
            managed.kill()
            try:
                managed.wait(timeout=10.0)
            except TimeoutError:
                pass

    def execute(self, case_dir: Path, executable: str, *, label: str | None = None, extra_args: str = "", timeout_s: float = 3600.0, monitor_cfl: bool = False) -> dict[str, Any]:
        log_dir = self.runtime_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        label = label or executable
        log_path = log_dir / f"{case_dir.name}__{label}.log"
        case_wsl = shlex.quote(wsl_path(case_dir))
        runtime_wsl = shlex.quote(wsl_path(self.runtime_root))
        command_text = f"source /opt/openfoam10/etc/bashrc; export TMP={runtime_wsl}/tmp TMPDIR={runtime_wsl}/tmp TEMP={runtime_wsl}/temp; cd {case_wsl}; set -e; {executable} {extra_args} -case ."
        command = ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", command_text]
        with log_path.open("w", encoding="utf-8", newline="") as log:
            managed = self.limiter.launch(command, slice_id=0, global_step=self.step_counter, stdout=log, stderr=subprocess.STDOUT)
            self.step_counter += 1
            pid = managed.pid
            parent_pid = None
            creation = None
            actual_cmd: list[str] = command
            if psutil is not None:
                try:
                    proc = psutil.Process(pid)
                    parent_pid = int(proc.ppid())
                    creation = datetime.fromtimestamp(proc.create_time(), timezone.utc).isoformat()
                    actual_cmd = proc.cmdline() or command
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            record: dict[str, Any] = {"run_id": self.run_id, "pid": pid, "parent_pid": parent_pid, "creation_time_utc": creation, "command_line": actual_cmd, "purpose": f"v2.1 OpenFOAM {executable} for {case_dir.name}", "case_id": case_dir.name, "label": label, "log_path_relative_to_runtime": str(log_path.relative_to(self.runtime_root)).replace("\\", "/"), "started_utc": datetime.now(timezone.utc).isoformat(), "close_method": "exact registered PID and exact descendants only"}
            self.registry.append(record)
            self._persist_registry()
            monitor = IncrementalCFLMonitor() if monitor_cfl else None
            deadline = time.monotonic() + float(timeout_s)
            stop_event: dict[str, Any] | None = None
            try:
                while True:
                    code = managed.poll()
                    if monitor is not None and log_path.exists():
                        with log_path.open("r", encoding="utf-8", errors="replace") as stream:
                            stream.seek(monitor._offset)
                            chunk = stream.read()
                            monitor._offset = stream.tell()
                        if chunk:
                            stop_event = monitor.feed(chunk)
                            if stop_event is not None:
                                record["online_cfl_stop"] = stop_event
                                record["hard_stop"] = stop_event["reason"]
                                self._kill_exact_tree(pid, managed, hard_stop=True)
                                code = managed.poll()
                                break
                    if code is not None:
                        break
                    if time.monotonic() >= deadline:
                        record["timeout"] = True
                        self._kill_exact_tree(pid, managed)
                        raise TimeoutError(f"process {pid} timed out")
                    time.sleep(0.1 if monitor is not None else 0.2)
                code = managed.wait(timeout=10.0) if managed.poll() is None else int(managed.poll())
            except TimeoutError:
                record["closed"] = True
                record["return_code"] = -9
                record["closed_utc"] = datetime.now(timezone.utc).isoformat()
                record["owned_descendants_at_close"] = _descendants(pid)
                self._persist_registry()
                raise
            finally:
                if monitor is not None:
                    monitor.flush()
                    record["online_cfl_summary"] = monitor.summary()
            record.update({"return_code": int(code), "closed_utc": datetime.now(timezone.utc).isoformat(), "closed": True, "owned_descendants_at_close": _descendants(pid)})
            self._persist_registry()
            return {"step": executable, "label": label, "return_code": int(code), "pid": pid, "log_path": str(log_path), "online_cfl": monitor.summary() if monitor is not None else None}


def closeout_process_audit(runtime_root: Path, limiter: ProcessLimiter, registry: list[dict[str, Any]]) -> dict[str, Any]:
    if not limiter._closed:  # noqa: SLF001
        limiter.shutdown(force=True)
    residual: list[dict[str, Any]] = []
    if psutil is not None:
        for item in registry:
            try:
                proc = psutil.Process(int(item["pid"]))
                if proc.is_running():
                    residual.append({"pid": int(item["pid"]), "parent_pid": int(proc.ppid()), "creation_time_utc": datetime.fromtimestamp(proc.create_time(), timezone.utc).isoformat()})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    audit = {"schema_version": "stage4e-b2-a-v2.1-process-cleanup-0.1.0", "run_id": runtime_root.name, "registry_count": len(registry), "registry": registry, "closed_pids": [int(item["pid"]) for item in registry if item.get("closed")], "residual_processes": residual, "task_owned_residual_process_count": len(residual), "process_cleanup_blocked": bool(residual), "limiter_audit": limiter.audit(), "max_concurrent_heavy_processes": limiter.audit().get("interval_peak_active_count"), "permit_leak": limiter.audit().get("permit_leak")}
    (runtime_root / "owned_process_registry.json").write_text(json.dumps(finite({"schema_version": "stage4e-b2-a-v2.1-owned-process-registry-0.1.0", "run_id": runtime_root.name, "processes": registry}), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (runtime_root / "owned_process_cleanup_audit.json").write_text(json.dumps(finite(audit), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return finite(audit)

