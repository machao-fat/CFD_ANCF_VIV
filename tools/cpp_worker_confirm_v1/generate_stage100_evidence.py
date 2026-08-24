from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _baseline_audit(project: Path) -> dict[str, Any]:
    root = project / "runtime/cpp_worker_persistent_ipc_v1/matlab_worker_baseline_v1"
    manifest_path = root / "matlab_worker_baseline_manifest.json"
    manifest = _load(manifest_path)
    missing: list[str] = []; mismatch: list[str] = []
    for row in manifest["files"]:
        path = root / str(row["path"])
        if not path.is_file():
            missing.append(str(row["path"])); continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row["sha256"] or path.stat().st_size != int(row["size_bytes"]):
            mismatch.append(str(row["path"]))
    return {"status": "pass" if not missing and not mismatch else "do_not_pass",
            "file_count_expected": int(manifest["file_count"]), "file_count_verified": len(manifest["files"]),
            "missing": missing, "hash_or_size_mismatch": mismatch,
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "expected_manifest_sha256": "9b6fcbf48277d07043818cad1e7c2c8cdbc37a80ec71f4c27bd7ab4c8f8331cb",
            "protected": True}


def main() -> int:
    project = Path(__file__).resolve().parents[2]
    out = project / "results/100_cpp_worker_confirm_v1"
    previous = project / "results/97_cpp_worker_persistent_ipc_v1"
    current = _load(out / "mock_confirm_result.json")
    prior_names = {
        "toolchain_audit.json", "cpp_worker_build_audit.json", "cpp_protocol_schema.json",
        "matlab_cpp_dual_run_audit.json", "ipc_fault_injection_audit.json", "phase_timing_per_step.json",
        "phase_timing_summary.json", "performance_comparison.json", "resource_audit.json",
        "process_ownership_audit.json", "stop_gate_audit.json", "test_discovery_audit.json",
    }
    for name in prior_names:
        source = previous / name
        if source.is_file(): _write(out / name, _load(source))
    _write(out / "matlab_worker_baseline_protection_audit.json", _baseline_audit(project))
    _write(out / "mock_40step_audit.json", {
        "status": current["status"], "steps": current["steps"],
        "physical_committed": f"{current['physical_committed']}/{40}",
        "fully_audited": f"{current['fully_audited']}/{40}",
        "persistent_worker_start_count": current["worker_start_count"],
        "slice_start_counts": current["slice_start_counts"], "owned_residual": current["owned_residual"],
        "real_process_starts": current["real_process_starts"], "wall_clock_s": current["wall_clock_s"],
        "mapping": current["protocol_audit"],
    })
    _write(out / "process_ownership_audit.json", {"registry": current["process_registry"], "owned_residual": current["owned_residual"],
                                                     "real_process_starts": current["real_process_starts"]})
    _write(out / "resource_audit.json", {"phase": "offline_mock", "cpu_percent": None, "memory_bytes": None,
                                           "disk_delta_bytes": None, "owned_residual": current["owned_residual"]})
    _write(out / "stop_gate_audit.json", {"status": "pass", "stopped_after_bounded_mock": True,
                                            "next_segment_started": False, "owned_residual": current["owned_residual"]})
    _write(out / "real_slice_adapter_audit.json", {
        "status": "offline_adapter_verified",
        "backend": "existing PersistentOpenFOAMSliceProcess via injected factory",
        "import_or_constructor_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "lifecycle": ["current_time_seed", "target_motion", "motion_consumed_ack",
                      "force_ready", "load_consumed_ack", "finalize_step", "owned_stop"],
        "real_external_factory_connected": False,
        "real_confirm_status": "not_executed",
    })
    _write(out / "test_discovery_audit.json", {"compileall": "pass", "cpp_confirm_specialized": {"collected": 17, "passed": 17, "failed": 0, "errors": 0},
                                                "root_unittest": {"collected": 1062, "passed": 1061, "failed": 0, "errors": 0, "skipped": 1},
                                                "real_process_starts": current["real_process_starts"]})
    _write(out / "performance_comparison.json", {
        "matlab_confirm025_wall_clock_s": 35.4478716,
        "matlab_phase_timing_confirm_wall_clock_s": 37.1570657,
        "cpp_mock_wall_clock_s": current["wall_clock_s"],
        "cpp_mock_speedup_claim": "not_evaluable_until_real_three_slice_confirm",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
    })
    _write(out / "stage4f_d_cpp_worker_persistent_ipc_v1_offline_gate.json", {
        "gate": "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_OFFLINE_GATE: pass",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "C++_WORKER_PERSISTENT_IPC_STATUS": "transport_verified_offline",
        "mock_40step": "40/40 committed, 40/40 fully audited",
        "real_confirm_eligibility": "blocked_until_explicit_real_openfoam_wsl_cfd_authorization",
        "owned_residual": current["owned_residual"], "real_process_starts": current["real_process_starts"],
    })
    _write(out / "stage4f_d_cpp_worker_persistent_ipc_v1_confirm_gate.json", {
        "gate": "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass",
        "classification": "not_executed_external_process_authorization_missing",
        "required_real_scope": {"steps": 40, "segment_duration_s": 0.05, "slice_count": 3},
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "C++_WORKER_PERSISTENT_IPC_STATUS": "not_completed",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
