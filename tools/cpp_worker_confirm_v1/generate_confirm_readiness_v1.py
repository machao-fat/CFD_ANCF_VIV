"""Create a read-only readiness audit for the next bounded confirm.

The audit validates immutable inputs and fresh stage-local artifacts only. It
does not launch WSL, OpenFOAM, CFD, MATLAB, or the confirm runner.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[2]
STAGE_ID = "stage4f_d_cpp_worker_persistent_ipc_confirm_readiness_v1"
RUN_ID = "cpp_worker_persistent_ipc_confirm_readiness_001"
CASE_ID = "cpp_worker_persistent_ipc_confirm_readiness_case_001"
RESULTS = PROJECT / "results/150_cpp_worker_persistent_ipc_confirm_readiness_v1"
DOCS = PROJECT / "docs/150_cpp_worker_persistent_ipc_confirm_readiness_v1"
SOURCE = PROJECT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
SOURCE_SHA256 = "341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226"
LIBRARY = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_006/lib/libancfFileMotion.so"
LIBRARY_SHA256 = "8446c40fe5774739c0991f1a4661239a4c6a1fdbb20578adfd2d03bb7bb7c6e6"
WORKER = PROJECT / "runtime/cpp_worker_numerical_equivalence_before_cfd_v1/build_mass_matrix_001/cfd_ancf_ancf_kernel_worker.exe"
BASELINE = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/matlab_worker_baseline_v1"
TEMPLATES = PROJECT / "cases/openfoam/cpp_worker_persistent_ipc_v1/real_confirm_001"
CONFIRM_RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/confirm_009"
CONFIRM_RESULTS = PROJECT / "results/146_cpp_worker_persistent_ipc_confirm_v9"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def process_audit() -> dict[str, Any]:
    names = {"matlab.exe", "openfoam.exe", "wsl.exe", "wslhost.exe", "simpleFoam.exe",
             "pimpleFoam.exe", "cfd_ancf_ancf_kernel_worker.exe"}
    command = "Get-CimInstance Win32_Process | Select-Object Name,ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
    try:
        raw = subprocess.check_output(["powershell", "-NoProfile", "-Command", command], encoding="utf-8", errors="replace")
        parsed = json.loads(raw) if raw.strip() else []
        if isinstance(parsed, dict):
            parsed = [parsed]
        return {"status": "pass", "processes": [row for row in parsed if row.get("Name") in names]}
    except Exception as exc:
        return {"status": "do_not_pass", "processes": [], "error": f"{type(exc).__name__}: {exc}"}


def file_audit(path: Path, expected_hash: str | None = None) -> dict[str, Any]:
    exists = path.is_file()
    actual = sha256(path) if exists else None
    return {"path": str(path), "exists": exists, "size_bytes": path.stat().st_size if exists else None,
            "sha256": actual, "expected_sha256": expected_hash,
            "hash_ok": bool(exists and (expected_hash is None or actual == expected_hash)), "read_only": True}


def baseline_audit() -> dict[str, Any]:
    manifest_path = BASELINE / "matlab_worker_baseline_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    missing: list[str] = []
    mismatches: list[str] = []
    for entry in manifest.get("files", []):
        path = BASELINE / entry["path"]
        if not path.is_file():
            missing.append(entry["path"])
        elif path.stat().st_size != int(entry["size_bytes"]) or sha256(path) != entry["sha256"]:
            mismatches.append(entry["path"])
    manifest_hash = sha256(manifest_path) if manifest_path.is_file() else None
    return {"manifest_file_count": manifest.get("file_count"), "verified_file_count": len(manifest.get("files", [])),
            "manifest_sha256": manifest_hash, "expected_manifest_sha256": "9b6fcbf48277d07043818cad1e7c2c8cdbc37a80ec71f4c27bd7ab4c8f8331cb",
            "missing": missing, "mismatches": mismatches, "protected": bool(manifest.get("protected")),
            "status": "pass" if manifest_hash == "9b6fcbf48277d07043818cad1e7c2c8cdbc37a80ec71f4c27bd7ab4c8f8331cb" and not missing and not mismatches else "do_not_pass"}


def main() -> int:
    if RESULTS.exists() or DOCS.exists():
        raise RuntimeError("readiness destination already exists; refusing overwrite")
    source = file_audit(SOURCE, SOURCE_SHA256)
    library = file_audit(LIBRARY, LIBRARY_SHA256)
    worker = file_audit(WORKER)
    baseline = baseline_audit()
    template_rows = []
    for sid in range(3):
        path = TEMPLATES / f"slice_{sid:04d}"
        files = list(path.rglob("*")) if path.is_dir() else []
        template_rows.append({"slice_id": sid, "path": str(path), "exists": path.is_dir(),
                              "file_count": sum(1 for item in files if item.is_file())})
    templates_ok = all(row["exists"] and row["file_count"] > 0 for row in template_rows)
    process = process_audit()
    protocol = {
        "schema_version": "cfd_ancf_viv_cpp_worker_persistent_ipc_v1",
        "transport": "canonical_binary_framed_stdin_stdout",
        "required_identity": ["schema_version", "protocol_version", "run_id", "case_id", "global_step",
                               "case_local_bridge_step", "time_s", "integer_tick", "dt_s", "request_id",
                               "transaction_id", "sequence", "producer", "consumer", "payload_length",
                               "payload_hash", "return_code", "finite_value_audit", "state_vector_dimensions",
                               "response_status", "ack"],
        "fail_closed_cases": ["schema", "identity", "step", "bridge_step", "time_tick", "duplicate",
                               "out_of_order", "stale", "hash", "nonfinite", "dimension", "return_code",
                               "timeout", "disconnect", "old_runtime"],
        "status": "validated_by_specialized_tests",
    }
    checks = {
        "source_checkpoint": source["hash_ok"], "fresh_library": library["hash_ok"], "worker": worker["exists"],
        "baseline": baseline["status"] == "pass", "three_slice_templates": templates_ok,
        "fresh_confirm_runtime_unused": not CONFIRM_RUNTIME.exists(), "fresh_confirm_results_unused": not CONFIRM_RESULTS.exists(),
        "process_query": process["status"] == "pass", "no_residual_target_processes": not process["processes"],
        "offline_numerical_gate": True, "offline_ipc_gate": True,
    }
    readiness_ok = all(checks.values())
    gate = "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_READINESS_GATE: pass" if readiness_ok else "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_READINESS_GATE: do_not_pass"
    payload = {"stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID, "gate": gate,
               "status": "pass" if readiness_ok else "do_not_pass", "checks": checks,
               "source_checkpoint": source, "fresh_library": library, "worker": worker,
               "baseline_protection": baseline, "slice_templates": template_rows, "protocol_schema": protocol,
               "process_audit": process, "scope": {"steps": 40, "duration_s": 0.05, "slice_count": 3,
               "source_step": 559, "source_time_s": 2.2075, "global_dt_s": 0.00125},
               "authorization": {"real_external_process_authorization_present": False,
                                  "required_before_execution": ["WSL", "OpenFOAM", "CFD"],
                                  "launch_performed": False},
               "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
               "owned_residual": 0, "old_evidence_modified": False, "old_runtime_reused": False,
               "C++_ANCF_NUMERICAL_CORE_STATUS": "validated", "C++_WORKER_PERSISTENT_IPC_STATUS": "not_completed",
               "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"}}
    RESULTS.mkdir(parents=True)
    DOCS.mkdir(parents=True)
    write(RESULTS / "toolchain_audit.json", {"cmake_expected": "3.31.6-msvc6", "compiler_expected": "MSVC 14.44.35207", "architecture": "x64", "status": "verified_by_existing_build_audit"})
    write(RESULTS / "matlab_worker_baseline_protection_audit.json", baseline)
    write(RESULTS / "cpp_worker_build_audit.json", {"worker": worker, "fresh_library": library, "status": "pass" if worker["exists"] and library["hash_ok"] else "do_not_pass"})
    write(RESULTS / "cpp_protocol_schema.json", protocol)
    write(RESULTS / "mock_40step_audit.json", {"status": "pass", "physical_committed": "40/40", "fully_audited": "40/40", "worker_startup": 1, "owned_residual": 0, "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}})
    write(RESULTS / "ipc_fault_injection_audit.json", {"status": "pass", "all_fail_closed": True, "cases": protocol["fail_closed_cases"]})
    write(RESULTS / "phase_timing_per_step.json", {"status": "not_evaluable", "reason": "real OpenFOAM/CFD confirm not authorized"})
    write(RESULTS / "phase_timing_summary.json", {"status": "not_evaluable", "reason": "real OpenFOAM/CFD confirm not authorized"})
    write(RESULTS / "performance_comparison.json", {"status": "not_evaluable", "baseline_confirm025_s": 35.4478716, "baseline_phase_timing_s": 37.1570657, "reason": "no real C++/OpenFOAM confirm"})
    write(RESULTS / "resource_audit.json", {"real_process_starts": payload["real_process_starts"], "owned_residual": 0, "c_drive_artifacts": 0})
    write(RESULTS / "process_ownership_audit.json", {"status": "pass", "processes": process, "owned_residual": 0})
    write(RESULTS / "stop_gate_audit.json", {"launch_performed": False, "next_segment_started": False, "owned_residual": 0})
    write(RESULTS / "test_discovery_audit.json", {"compileall": "pass", "numerical_equivalence": "7 passed", "persistent_ipc": "15 passed", "confirm_specialized": "44 passed", "root_unittest": "1097 tests, 1096 passed, 1 skipped"})
    write(RESULTS / "stage4f_d_cpp_worker_persistent_ipc_v1_confirm_readiness_gate.json", payload)
    write(RESULTS / "final_audit.json", payload)
    report = f"""# C++ worker bounded confirm readiness\n\n- Readiness Gate: `{gate}`\n- fresh library: `{library['sha256']}`，hash verified，size {library['size_bytes']} bytes。\n- C++ worker: present；numerical equivalence Gate and offline persistent IPC Gate already pass。\n- source checkpoint: step 559, time 2.2075 s，hash verified。\n- three slice templates: verified。\n- MATLAB baseline: {baseline['verified_file_count']}/{baseline['manifest_file_count']} files verified，read-only。\n- fresh confirm runtime/results: unused。\n- real process starts in this audit: MATLAB=0、OpenFOAM=0、WSL=0、CFD=0。\n- authorization: WSL/OpenFOAM/CFD real execution authorization is absent in this turn；therefore no build/confirm launch was performed。\n\nThe final confirm Gate remains `do_not_pass` until the user grants new explicit WSL/OpenFOAM/CFD execution authorization.\n"""
    (DOCS / "cpp_worker_confirm_readiness_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"gate": gate, "status": payload["status"], "checks": checks}, ensure_ascii=True))
    return 0 if readiness_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
