"""D-drive, bounded OpenFOAM execution and ownership evidence for v2."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from src.coupling.process_control.process_limiter import ProcessLimiter

from .identity_v2 import finite, sha256_file
from .case_generator_v2 import case_freshness


def wsl_path(path: Path) -> str:
    resolved = str(path.resolve()).replace("\\", "/")
    if len(resolved) < 2 or resolved[1] != ":":
        raise ValueError(f"expected a Windows drive path: {path}")
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


class OwnedRunner:
    def __init__(self, limiter: ProcessLimiter, registry: list[dict[str, Any]], runtime_root: Path, run_id: str) -> None:
        self.limiter = limiter
        self.registry = registry
        self.runtime_root = runtime_root
        self.run_id = run_id
        self.step_counter = 0

    def _persist_registry(self) -> None:
        """Persist ownership state immediately, including timeout/crash evidence."""
        path = self.runtime_root / "owned_process_registry.json"
        payload = {
            "schema_version": "stage4e-b2-a-v2-owned-process-registry-0.1.0",
            "run_id": self.run_id,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "processes": self.registry,
        }
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(finite(payload), ensure_ascii=False, indent=2) + "\n")

    def execute(self, case_dir: Path, step: str, *, timeout_s: float = 1800.0) -> dict[str, Any]:
        log_dir = self.runtime_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{case_dir.name}__{step}.log"
        case_wsl = shlex.quote(wsl_path(case_dir))
        runtime_wsl = shlex.quote(wsl_path(self.runtime_root))
        command = ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", f"source /opt/openfoam10/etc/bashrc; export TMP={runtime_wsl}/tmp TMPDIR={runtime_wsl}/tmp TEMP={runtime_wsl}/temp; cd {case_wsl}; set -e; {step} -case ."]
        started = datetime.now(timezone.utc).isoformat()
        with log_path.open("w", encoding="utf-8", newline="\n") as log:
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
            record: dict[str, Any] = {"run_id": self.run_id, "pid": pid, "parent_pid": parent_pid, "creation_time_utc": creation, "command_line": actual_cmd, "purpose": f"v2 OpenFOAM {step} for {case_dir.name}", "case_id": case_dir.name, "log_path_relative_to_runtime": str(log_path.relative_to(self.runtime_root)).replace("\\", "/"), "started_utc": started, "close_method": "wait; on timeout terminate/kill only registered PID and exact descendants"}
            self.registry.append(record)
            self._persist_registry()
            try:
                if step == "pimpleFoam":
                    deadline = time.monotonic() + float(timeout_s)
                    code: int | None = None
                    while code is None:
                        code = managed.poll()
                        if code is not None:
                            break
                        if log_path.exists():
                            text = log_path.read_text(encoding="utf-8", errors="replace")
                            matches = re.findall(r"Courant Number mean:\s*[-+0-9.eE]+\s*max:\s*([-+0-9.eE]+)", text)
                            if matches and max(float(value) for value in matches) >= 0.8:
                                record["hard_stop"] = "max_cfl_ge_0.8"
                                record["observed_max_cfl"] = max(float(value) for value in matches)
                                managed.terminate()
                                try:
                                    code = managed.wait(timeout=10.0)
                                except TimeoutError:
                                    managed.kill()
                                    code = managed.wait(timeout=10.0)
                                break
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"process {pid} timed out")
                        time.sleep(0.25)
                    code = int(code)
                else:
                    code = managed.wait(timeout=timeout_s)
            except TimeoutError:
                record["timeout"] = True
                for child_pid in _descendants(pid):
                    try:
                        if psutil is not None:
                            child = psutil.Process(child_pid)
                            child.terminate()
                            child.wait(timeout=3)
                    except Exception:
                        pass
                self._persist_registry()
                raise
            record.update({"return_code": int(code), "closed_utc": datetime.now(timezone.utc).isoformat(), "closed": True, "owned_descendants_at_close": _descendants(pid)})
            self._persist_registry()
            return {"step": step, "return_code": int(code), "pid": pid, "log_path": str(log_path)}


def run_case(case_dir: Path, *, runtime_root: Path, steps: Iterable[str] = ("blockMesh", "checkMesh", "setFields", "pimpleFoam"), timeout_s: float = 1800.0, registry: list[dict[str, Any]] | None = None, limiter: ProcessLimiter | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    owns_limiter = limiter is None
    limiter = limiter or ProcessLimiter(2, run_id=runtime_root.name)
    registry = registry if registry is not None else []
    runner = OwnedRunner(limiter, registry, runtime_root, runtime_root.name)
    results: list[dict[str, Any]] = []
    for step in steps:
        result = runner.execute(case_dir, step, timeout_s=timeout_s)
        results.append(result)
        if result["return_code"] != 0:
            break
    if owns_limiter:
        limiter.shutdown()
    return results, registry


def log_health(paths: Iterable[Path]) -> dict[str, Any]:
    import re
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths if path.exists())
    upper = text.upper()
    bad = [token for token in ("FOAM FATAL", "FATAL ERROR") if token in upper]
    if re.search(r"\b(?:NAN|INF|INFINITY)\b", upper):
        bad.append("NAN_OR_INF")
    if re.search(r"\b(?:SIGFPE|FLOATING POINT EXCEPTION)\b.*(?:RECEIVED|CAUGHT|ABORT|ERROR)", upper):
        bad.append("SIGFPE")
    return {"contains_End": "End" in text, "fatal_tokens": sorted(set(bad)), "finite_log_text": not bad}


def closeout_process_audit(runtime_root: Path, limiter: ProcessLimiter, registry: list[dict[str, Any]], *, blocked: bool = False) -> dict[str, Any]:
    if not limiter._closed:  # noqa: SLF001 - closeout owns this bounded limiter
        limiter.shutdown(force=blocked)
    residual: list[dict[str, Any]] = []
    for item in registry:
        pid = int(item["pid"])
        if psutil is not None:
            try:
                proc = psutil.Process(pid)
                if proc.is_running():
                    residual.append({"pid": pid, "creation_time_utc": datetime.fromtimestamp(proc.create_time(), timezone.utc).isoformat(), "parent_pid": int(proc.ppid())})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    audit = {"schema_version": "stage4e-b2-a-v2-process-lifecycle-0.1.0", "run_id": runtime_root.name, "registry": registry, "limiter_audit": limiter.audit(), "task_owned_residual_process_count": len(residual), "closed_pids": [item["pid"] for item in registry if item.get("closed")], "residual_processes": residual, "process_cleanup_blocked": bool(blocked or residual), "max_concurrent_heavy_processes": limiter.audit().get("interval_peak_active_count"), "permit_leak": limiter.audit().get("permit_leak")}
    for path in (runtime_root / "owned_process_registry.json", runtime_root / "owned_process_cleanup_audit.json"):
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(finite(audit), ensure_ascii=False, indent=2) + "\n")
    return audit


def write_process_inventory(path: Path, *, run_id: str, phase: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(finite({"schema_version": "stage4e-b2-a-v2-process-inventory-0.1.0", "captured_utc": datetime.now(timezone.utc).isoformat(), "run_id": run_id, "phase": phase, "processes": process_snapshot()}), ensure_ascii=False, indent=2) + "\n")
