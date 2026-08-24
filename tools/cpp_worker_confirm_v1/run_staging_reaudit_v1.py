"""Read-only staging re-audit using the discovered deployable library.

This deliberately writes a new stage directory and never rewrites the Stage
101 audit or any protected runtime.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from coupling.cpp_worker_confirm_v1.staging import audit_staging


PROJECT = Path(__file__).resolve().parents[2]
STAGE = "106_cpp_worker_staging_reaudit_v1"
RESULTS = PROJECT / "results" / STAGE
DOCS = PROJECT / "docs" / STAGE


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=False)
    DOCS.mkdir(parents=True, exist_ok=False)
    source = PROJECT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
    baseline = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/matlab_worker_baseline_v1/matlab_worker_baseline_manifest.json"
    cases = PROJECT / "cases/openfoam/cpp_worker_persistent_ipc_v1/real_confirm_001"
    worker = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/build-release/cfd_ancf_ancf_kernel_worker.exe"
    library = PROJECT / "runtime/stage4f_three_slice_bridge_precision_repair_v1/lib/libancfFileMotion.so"
    templates = [PROJECT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/cases" / f"slice_{sid:04d}" for sid in range(3)]
    runtime = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/real_confirm_002"
    confirm_results = RESULTS / "confirm_results"

    raw_library = library.read_bytes() if library.is_file() else b""
    library_audit = {
        "path": str(library),
        "exists": library.is_file(),
        "suffix": library.suffix,
        "elf_magic": raw_library[:4] == b"\x7fELF",
        "size_bytes": len(raw_library),
        "sha256": sha256(library) if library.is_file() else None,
        "source_stage": "stage4f_three_slice_bridge_precision_repair_v1",
        "read_only": True,
        "reuse_allowed": False,
        "reuse_reason": "library resides in a protected legacy runtime; fresh stage-local build required",
    }
    audit = audit_staging(
        project_root=PROJECT,
        source_checkpoint=source,
        source_sha256="341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226",
        baseline_manifest=baseline,
        baseline_manifest_sha256="9b6fcbf48277d07043818cad1e7c2c8cdbc37a80ec71f4c27bd7ab4c8f8331cb",
        template_cases=templates,
        destination_cases=cases,
        runtime=runtime,
        results=confirm_results,
        worker_executable=worker,
        deployable_library_candidates=[library],
        real_authorization_present=False,
    )
    audit["blockers"].append("candidate libancfFileMotion.so is from a protected legacy runtime; a fresh stage-local build is required")
    audit.update({
        "stage_id": "stage4f_d_cpp_worker_persistent_ipc_staging_reaudit_v1",
        "run_id": "cpp_worker_staging_reaudit_001",
        "case_id": "cpp_worker_staging_reaudit_case_001",
        "library_audit": library_audit,
        "old_stage101_evidence_modified": False,
        "launch_performed": False,
    })
    (RESULTS / "staging_reaudit.json").write_text(json.dumps(audit, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    gate_status = "pass" if not audit["blockers"] else "do_not_pass"
    gate = {
        "gate": f"STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_STAGING_REAUDIT_V1_GATE: {gate_status}",
        "status": gate_status,
        "blockers": audit["blockers"],
        "library_audit": library_audit,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "launch_performed": False,
        "old_evidence_modified": False,
        "next_action": "obtain explicit OpenFOAM/WSL/CFD authorization" if audit["blockers"] else "eligible for one bounded confirm",
    }
    (RESULTS / "stage4f_d_cpp_worker_persistent_ipc_staging_reaudit_v1_gate.json").write_text(
        json.dumps(gate, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    report = f"""# C++ worker staging re-audit

- Library exists: {library_audit['exists']}
- ELF magic: {library_audit['elf_magic']}
- Size: {library_audit['size_bytes']} bytes
- SHA-256: `{library_audit['sha256']}`
- MATLAB baseline: protected and hash-verified
- New three-slice case staging: read-only audited
- MATLAB/OpenFOAM/WSL/CFD starts: 0/0/0/0
- owned residual: 0
- blockers: {', '.join(audit['blockers']) if audit['blockers'] else 'none'}

No solver was launched. Stage101 evidence and all old runtimes remain untouched.
"""
    (DOCS / "staging_reaudit_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(gate, ensure_ascii=True, indent=2))
    return 0 if gate_status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
