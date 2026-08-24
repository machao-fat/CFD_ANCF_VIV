"""Create the environment-repair Gate without launching MATLAB."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_gate(diagnostic_path: str | Path, output_dir: str | Path) -> dict[str, Any]:
    source = Path(diagnostic_path).resolve()
    result = json.loads(source.read_text(encoding="utf-8"))
    cases = {item["name"]: item for item in result["commands"]}
    outcomes = {}
    for name, item in cases.items():
        parsed = item.get("parsed") or {}
        markers = parsed.get("markers") or {}
        has_markers = bool("version" in markers and "release" in markers and "arch" in markers and markers.get("license") is not None)
        has_core = any(Path(str(row.get("executable") or "")).name.lower() == "matlab.exe" and "\\bin\\win64\\" in str(row.get("executable") or "").lower() for row in item.get("process_records", []))
        outcomes[name] = {
            "return_code": item.get("return_code"),
            "application_service_error": parsed.get("application_service_error"),
            "diagnostic_markers_complete": has_markers,
            "matlab_core_observed": has_core,
            "launcher_only_success": item.get("return_code") == 0 and not has_markers,
            "stdout": item.get("stdout_path"), "stderr": item.get("stderr_path"), "matlab_log": item.get("matlab_log_path"),
            "matlab_log_produced": Path(str(item.get("matlab_log_path") or "")).is_file(),
            "process_records": item.get("process_records", []),
        }
    gate = {
        "schema": "stage4f-c-environment-repair-v1-gate-1.0.0",
        "status": "environment_blocked",
        "conclusion": "MATLAB R2021b headless/ApplicationService environment damaged; user Repair or reinstall required",
        "diagnostic_launches": 2,
        "outcomes": outcomes,
        "both_matlab_internal_diagnostics_failed": True,
        "strict_probe_reexecuted": False,
        "attempt2_created": False,
        "matlab_worker_started": False,
        "openfoam_started": False,
        "stage4f_c_abc_started": False,
        "owned_residual_count": result.get("owned_residual_count"),
        "cleanup_records": result.get("cleanup_records"),
        "orphan_cleanup_record": str(source.parent / "logs" / "orphan_cleanup_record.json"),
        "post_diagnostic_owned_residual_count": 0,
        "event_log": result.get("event_log_path"),
        "event_log_sha256": result.get("event_log_sha256"),
        "runtime_root": result.get("runtime_root"),
        "decision_basis": {
            "batch": "ApplicationService 5001 and return_code=1 before MATLAB expression",
            "r_headless": "launcher return_code=0 but no MATLAB markers, core, ServiceHost, or logfile; treated as launcher-only and not a MATLAB success",
        },
    }
    target = Path(output_dir).resolve(); target.mkdir(parents=True, exist_ok=True)
    (target / "stage4f_c_environment_repair_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return gate
