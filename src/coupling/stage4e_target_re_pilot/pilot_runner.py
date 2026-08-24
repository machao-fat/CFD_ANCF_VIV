"""D-drive OpenFOAM-10 runner with explicit process ownership evidence."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import psutil
except ImportError:  # pragma: no cover - production environment has psutil
    psutil = None

from src.coupling.process_control.process_limiter import ProcessLimiter

from .identity import finite


def wsl_path(path: Path) -> str:
    resolved = str(path.resolve()).replace("\\", "/")
    if len(resolved) >= 2 and resolved[1] == ":":
        return "/mnt/" + resolved[0].lower() + resolved[2:]
    raise ValueError(f"expected a Windows drive path: {path}")


def process_snapshot() -> list[dict[str, Any]]:
    if psutil is None:
        return []
    rows: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "create_time", "cmdline"]):
        try:
            info = proc.info
            rows.append({
                "pid": int(info["pid"]), "parent_pid": int(info.get("ppid") or 0),
                "name": info.get("name"), "creation_time_utc": datetime.fromtimestamp(float(info["create_time"]), timezone.utc).isoformat(),
                "command_line": list(info.get("cmdline") or []),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
            continue
    return rows


class OwnedProcessRun:
    """One registered, bounded external process execution."""

    def __init__(self, limiter: ProcessLimiter, registry: list[dict[str, Any]], run_id: str, runtime_root: Path) -> None:
        self.limiter = limiter
        self.registry = registry
        self.run_id = run_id
        self.runtime_root = runtime_root

    def execute(self, case_dir: Path, step: str, script: str, *, timeout_s: float = 3600.0) -> dict[str, Any]:
        log_dir = self.runtime_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{case_dir.name}__{step}.log"
        command = ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", script]
        started = datetime.now(timezone.utc).isoformat()
        with log_path.open("w", encoding="utf-8", newline="\n") as log:
            managed = self.limiter.launch(
                command, slice_id=0, global_step=0, stdout=log, stderr=subprocess.STDOUT
            )
            pid = managed.pid
            parent_pid: int | None = None
            creation_time: str | None = None
            command_line: list[str] = command
            if psutil is not None:
                try:
                    proc = psutil.Process(pid)
                    parent_pid = proc.ppid()
                    creation_time = datetime.fromtimestamp(proc.create_time(), timezone.utc).isoformat()
                    command_line = proc.cmdline() or command
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            record: dict[str, Any] = {
                "run_id": self.run_id, "pid": pid, "parent_pid": parent_pid,
                "creation_time_utc": creation_time, "command_line": command_line,
                "purpose": f"OpenFOAM {step} for {case_dir.name}", "case_relative_hint": case_dir.name,
                "log_path_relative_to_runtime": str(log_path.relative_to(self.runtime_root)).replace("\\", "/"),
                "started_utc": started, "close_method": "ManagedProcess.wait; terminate/kill only this registered PID on timeout",
            }
            self.registry.append(record)
            try:
                code = managed.wait(timeout=timeout_s)
            except TimeoutError:
                record["timeout"] = True
                raise
            record["return_code"] = int(code)
            record["closed_utc"] = datetime.now(timezone.utc).isoformat()
            record["closed"] = True
            return {"step": step, "return_code": int(code), "log_path": str(log_path), "pid": pid}


def run_openfoam_case(
    case_dir: Path,
    *,
    runtime_root: Path,
    run_id: str,
    registry: list[dict[str, Any]],
    limiter: ProcessLimiter,
    steps: Iterable[str] = ("blockMesh", "checkMesh", "pimpleFoam"),
    timeout_s: float = 3600.0,
) -> list[dict[str, Any]]:
    """Run only named OpenFOAM steps; every step is a registered process."""
    runner = OwnedProcessRun(limiter, registry, run_id, runtime_root)
    results: list[dict[str, Any]] = []
    case_wsl = shlex.quote(wsl_path(case_dir))
    for step in steps:
        command = f"source /opt/openfoam10/etc/bashrc; cd {case_wsl}; set -e; {step} -case ."
        result = runner.execute(case_dir, step, command, timeout_s=timeout_s)
        results.append(result)
        if result["return_code"] != 0:
            break
    return results


def case_freshness(case_dir: Path) -> dict[str, Any]:
    if not case_dir.exists() or not case_dir.is_dir():
        return {
            "schema_version": "stage4e-b2-a-case-freshness-0.1.0",
            "case_relative_name": case_dir.name, "fresh_case_created": False,
            "forbidden_existing_before_run": [], "numeric_time_directories_before_run": [],
            "unexpected_symlinks": [], "passed": False, "reason": "case directory is missing",
        }
    forbidden = ["postProcessing", "processor0", "processor1", "log.pimpleFoam", "log.checkMesh", "log.blockMesh"]
    found = [name for name in forbidden if (case_dir / name).exists()]
    numeric_dirs = [p.name for p in case_dir.iterdir() if p.is_dir() and p.name not in {"0", "constant", "system"} and p.name.replace(".", "", 1).isdigit()]
    symlinks = [str(p) for p in case_dir.rglob("*") if p.is_symlink()]
    passed = not found and not numeric_dirs and not symlinks and (case_dir / "0").exists()
    return {
        "schema_version": "stage4e-b2-a-case-freshness-0.1.0",
        "case_relative_name": case_dir.name, "fresh_case_created": True,
        "forbidden_existing_before_run": found, "numeric_time_directories_before_run": numeric_dirs,
        "unexpected_symlinks": symlinks, "passed": passed,
    }


def cfl_from_log(log_path: Path) -> dict[str, float | None]:
    import re
    mean_values: list[float] = []
    max_values: list[float] = []
    pattern = re.compile(r"Courant Number mean:\s*([-+0-9.eE]+)\s*max:\s*([-+0-9.eE]+)")
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.search(line)
        if match:
            mean_values.append(float(match.group(1)))
            max_values.append(float(match.group(2)))
    return {
        "mean_cfl_max": max(mean_values) if mean_values else None,
        "max_cfl": max(max_values) if max_values else None,
        "samples": len(max_values),
    }


def log_health(log_paths: Iterable[Path]) -> dict[str, Any]:
    import re
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in log_paths if path.exists())
    upper = text.upper()
    bad_tokens = [token for token in ("FOAM FATAL", "FATAL ERROR") if token in upper]
    if re.search(r"(?<![A-Z])(?:NAN|INF)(?![A-Z])", upper):
        bad_tokens.append("NAN_OR_INF")
    return {
        "contains_End": "End" in text,
        "fatal_tokens": sorted(set(bad_tokens)),
        "finite_log_text": not bad_tokens,
        "log_paths": [str(path) for path in log_paths],
    }


def closeout_process_audit(limiter: ProcessLimiter, registry: list[dict[str, Any]], runtime_root: Path) -> dict[str, Any]:
    audit = limiter.audit()
    limiter.assert_no_leaks()
    payload = {
        "schema_version": "stage4e-b2-a-process-lifecycle-0.1.0",
        "registry": registry, "limiter_audit": audit,
        "task_owned_residual_process_count": 0,
        "closed_pids": [item["pid"] for item in registry if item.get("closed")],
        "residual_pids": [], "process_cleanup_blocked": False,
    }
    (runtime_root / "owned_process_registry.json").write_text(json.dumps(finite(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (runtime_root / "owned_process_cleanup_audit.json").write_text(json.dumps(finite(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
