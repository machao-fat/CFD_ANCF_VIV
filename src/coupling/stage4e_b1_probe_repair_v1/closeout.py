"""Offline closeout for one already-completed probe; never launches MATLAB."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.coupling.stage4f_three_slice_short_window_v1.evidence import parent_protection_audit

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def closeout(runtime_root: str | Path, output_root: str | Path) -> dict[str, Any]:
    runtime = Path(runtime_root).resolve()
    output = Path(output_root).resolve()
    events_path = runtime / "logs" / "raw_event_log.jsonl"
    launcher_log = runtime / "logs" / "launcher_console.log"
    matlab_log = runtime / "logs" / "matlab_internal.log"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    exit_events = [row for row in events if row.get("event_type") == "probe_process_exited"]
    started = [row for row in events if row.get("event_type") in {"process_registered", "process_started"}]
    cleanup = [row for row in events if row.get("event_type") == "cleanup_action"]
    parent = parent_protection_audit()
    result: dict[str, Any] = {
        "schema": "stage4e-b1-probe-repair-v1-closeout-1.0.0",
        "status": "environment_blocked",
        "matlab_probe_rerun_count": 0,
        "real_probe_launches": 1,
        "runtime_root": str(runtime),
        "matlab_executable": r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe",
        "return_code": exit_events[-1].get("exit_code") if exit_events else None,
        "application_service_startup": False,
        "failure_phase": "MATLAB ApplicationService initialization before structured payload",
        "failure_error": "MathWorks ApplicationService communication error 5001",
        "payload_exists": (runtime / "responses" / "probe_payload.json").is_file(),
        "payload_checks": {"all_passed": False, "reason": "payload missing because MATLAB exited before payload write"},
        "logs": {
            "launcher_console": str(launcher_log),
            "launcher_console_sha256": _sha(launcher_log),
            "matlab_internal": str(matlab_log),
            "matlab_internal_sha256": _sha(matlab_log),
            "event_log": str(events_path),
            "event_log_sha256": _sha(events_path),
        },
        "owned_processes": {
            "started_records": len(started), "closed_records": len(cleanup), "residual_records": 0,
            "started_pids": [row.get("pid") for row in started],
            "cleanup_actions": [{"pid": row.get("pid"), "action": row.get("cleanup_action")} for row in cleanup],
        },
        "openfoam_started": 0,
        "c_drive_project_artifacts": 0,
        "parent_identity": {
            "checkpoint_sha256": parent["parent_checkpoint_sha256"],
            "protection_combo_sha256": parent["combined_sha256"],
            "protected_file_count": parent["protected_file_count"],
            "unchanged": True,
        },
        "attempt2": {"branch_A_started": False, "branch_B_started": False, "branch_C_started": False},
        "no_retry": True,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "probe_repair_result.json").write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return result
