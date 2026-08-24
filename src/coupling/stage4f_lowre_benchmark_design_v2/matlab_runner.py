"""Launch exactly one owned MATLAB process and audit its descendants."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path

import psutil

from .benchmark import write_json


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _existing(pids: set[int]) -> list[int]:
    return sorted(pid for pid in pids if psutil.pid_exists(pid))


def run_matlab(root: Path, matlab: Path) -> int:
    runtime = root / "runtime" / "stage4f_lowre_benchmark_design_v2"
    result = root / "results" / "11_stage4f_lowre_benchmark_design_v2"
    runtime.mkdir(parents=True, exist_ok=True)
    result.mkdir(parents=True, exist_ok=True)
    log_path = result / "matlab_execution.log"
    audit_path = result / "matlab_execution_audit.json"
    previous_audit = None
    previous_count = 0
    if audit_path.is_file():
        try:
            previous_audit = json.loads(audit_path.read_text(encoding="utf-8"))
            previous_count = int(previous_audit.get("matlab_launch_count", 1))
        except (OSError, ValueError, TypeError):
            previous_audit = None
            previous_count = 0
    attempt = previous_count + 1
    if attempt > 1:
        log_path = result / f"matlab_execution_attempt{attempt}.log"
    command = [
        str(matlab),
        "-batch",
        "addpath(fullfile(pwd,'src','structure_ancf_matlab','stage4f_design_v2')); run_stage4f_design_v2",
    ]
    started = _utc_now()
    owned: set[int] = set()
    observed_children: set[int] = set()
    return_code: int | None = None
    cleanup_actions: list[dict[str, object]] = []
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        process = subprocess.Popen(
            command,
            cwd=str(root),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "TEMP": str(runtime), "TMP": str(runtime)},
        )
        owned.add(process.pid)
        while process.poll() is None:
            try:
                parent = psutil.Process(process.pid)
                for child in parent.children(recursive=True):
                    observed_children.add(child.pid)
                    owned.add(child.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            time.sleep(0.25)
        return_code = process.returncode

    # Only exact descendants observed from this launch are eligible for cleanup.
    residual_before = _existing(owned)
    for pid in residual_before:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            cleanup_actions.append({"pid": pid, "action": "terminate_owned_pid"})
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            cleanup_actions.append({"pid": pid, "action": "terminate_failed", "reason": str(exc)})
    _, alive = psutil.wait_procs(
        [psutil.Process(pid) for pid in _existing(owned)], timeout=5.0
    ) if _existing(owned) else ([], [])
    for proc in alive:
        try:
            proc.kill()
            cleanup_actions.append({"pid": proc.pid, "action": "kill_owned_pid_after_timeout"})
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            cleanup_actions.append({"pid": proc.pid, "action": "kill_failed", "reason": str(exc)})
    if alive:
        psutil.wait_procs(alive, timeout=5.0)
    residual_after = _existing(owned)
    prior_history = []
    if previous_audit is not None:
        prior_history = list(previous_audit.get("launch_history", []))
        if not prior_history:
            prior_history = [{
                "attempt": previous_count,
                "launcher_pid": previous_audit.get("launcher_pid"),
                "core_or_child_pids": previous_audit.get("core_or_child_pids", []),
                "return_code": previous_audit.get("return_code"),
                "status": previous_audit.get("status"),
                "log_path": previous_audit.get("log_path"),
                "owned_residual": previous_audit.get("owned_residual"),
            }]
    current_history = {
        "attempt": attempt,
        "launcher_pid": process.pid,
        "core_or_child_pids": sorted(observed_children),
        "return_code": return_code,
        "status": "passed" if return_code == 0 and not residual_after else "failed",
        "log_path": log_path.as_posix(),
        "owned_residual": len(residual_after),
    }
    audit = {
        "status": "passed" if return_code == 0 and not residual_after else "failed",
        "single_matlab_launch": attempt == 1,
        "matlab_launch_count": attempt,
        "launch_history": prior_history + [current_history],
        "command": command,
        "started_utc": started,
        "finished_utc": _utc_now(),
        "launcher_pid": process.pid,
        "core_or_child_pids": sorted(observed_children),
        "return_code": return_code,
        "runtime_path": runtime.as_posix(),
        "runtime_on_D_drive": runtime.drive.upper() == "D:",
        "log_path": log_path.as_posix(),
        "cleanup_by_process_name": False,
        "cleanup_actions": cleanup_actions,
        "owned_residual_before_cleanup": residual_before,
        "owned_residual_after_cleanup": residual_after,
        "owned_residual": len(residual_after),
        "openfoam_started": False,
    }
    write_json(audit_path, audit)
    write_json(
        result / "process_cleanup_audit.json",
        {
            "status": audit["status"],
            "launcher_pid": process.pid,
            "core_or_child_pids": sorted(observed_children),
            "owned_residual": len(residual_after),
            "cleanup_by_process_name": False,
            "cleanup_actions": cleanup_actions,
            "openfoam_pids_started": [],
        },
    )
    return int(return_code or 0) if not residual_after else 97


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--matlab", type=Path, required=True)
    args = parser.parse_args()
    return run_matlab(args.root.resolve(), args.matlab.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
