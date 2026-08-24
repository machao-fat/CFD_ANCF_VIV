"""Write a gate report from the one real probe; never launches workers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_gate_report(result_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    result_file = Path(result_path).resolve()
    result = json.loads(result_file.read_text(encoding="utf-8"))
    passed = result.get("status") == "passed"
    gate = {
        "schema": "stage4f-c-probe-repair-v1-gate-1.0.0",
        "status": "passed" if passed else "environment_blocked",
        "probe_status": result.get("status"),
        "return_code": result.get("return_code"),
        "matlab_executable": result.get("matlab_executable"),
        "payload_validation": result.get("payload_validation"),
        "application_service_startup": result.get("application_service_startup"),
        "launcher_core_servicehost_identity": result.get("owned_process_identity"),
        "owned_processes_closed": result.get("owned_processes_closed"),
        "owned_residual": result.get("owned_residual_count"),
        "c_drive_project_artifacts": result.get("c_drive_project_artifact_count"),
        "openfoam_started": result.get("openfoam_started"),
        "attempt2": {"created": False, "branch_A_started": False, "branch_B_started": False, "branch_C_started": False},
        "stop_condition": None if passed else result.get("block_reason", "probe_failed"),
        "evidence": {
            "result": str(result_file),
            "event_log": result.get("event_log_path"),
            "event_log_sha256": result.get("event_log_sha256"),
            "launcher_console": str(result_file.parent / "logs" / "launcher_console.log"),
            "matlab_internal": str(result_file.parent / "logs" / "matlab_internal.log"),
        },
        "verification_domains": {
            "gui_manual": "confirmed externally; not substituted for this gate",
            "automatic_probe": "passed" if passed else "failed",
            "matlab_worker": "not_started",
            "openfoam_fsi_numeric": "not_started",
        },
    }
    target = Path(output_dir).resolve(); target.mkdir(parents=True, exist_ok=True)
    path = target / "stage4f_c_probe_repair_v1_gate.json"
    path.write_text(json.dumps(gate, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return gate
