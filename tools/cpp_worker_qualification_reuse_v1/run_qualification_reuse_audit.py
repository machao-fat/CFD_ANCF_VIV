"""Audit whether Stage204 may reuse prior C++ numerical qualification."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))

from coupling.cpp_worker_qualification_reuse_v1 import assess_reuse

RESULTS = PROJECT / "results" / "205_cpp_worker_numerical_qualification_reuse_v1"
DOCS = PROJECT / "docs" / "205_cpp_worker_numerical_qualification_reuse_v1"
STAGE186 = PROJECT / "results" / "186_cpp_worker_strict_matlab_cpp_dual_review_repair_v1"
STAGE196 = PROJECT / "results" / "196_cpp_worker_persistent_ipc_confirm_v12"
STAGE204 = PROJECT / "results" / "204_cpp_worker_persistent_ipc_confirm_v17"
WORKER = PROJECT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1_continuation" / "build_release_003" / "cfd_ancf_ancf_kernel_worker.exe"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    gate186 = load(STAGE186 / "independent_gate.json")
    contract186 = load(STAGE186 / "numerical_contract_manifest.json")
    summary196 = load(STAGE196 / "confirm_summary.json")
    summary204 = load(STAGE204 / "confirm_summary.json")
    gate204 = load(STAGE204 / "stage4f_d_cpp_worker_persistent_ipc_v1_confirm_gate.json")
    worker_stat = WORKER.stat()

    worker_identity = {
        "worker_path": str(WORKER),
        "worker_sha256": sha256(WORKER),
        "worker_size_bytes": worker_stat.st_size,
        "worker_mtime_ns": worker_stat.st_mtime_ns,
    }
    candidate = {
        **worker_identity,
        "library_sha256": summary204["fresh_library"]["sha256"],
        "model_contract_sha256": summary204["process_registry"][0]["expected_model_contract_sha256"],
        "gauss_order": summary204["ancf_numerical_contract"]["gauss_order"],
        "max_newton": summary204["ancf_numerical_contract"]["max_newton"],
        "global_dt_s": 0.00125,
        "formal_protocol": "0.2.1",
    }
    # Stage186 is the only strict MATLAB/C++ proof.  It intentionally lacks
    # fields that were not recorded then; missing identities are fail-closed.
    qualification = {
        "dual_run_status": "pass" if gate186.get("strict_pass_steps") == 40 else "do_not_pass",
        "numerical_core_status": gate186.get("C++_ANCF_NUMERICAL_CORE_STATUS"),
        "library_sha256": None,
        "model_contract_sha256": None,
        "gauss_order": contract186.get("gauss_order"),
        "max_newton": contract186.get("max_newton"),
        "global_dt_s": contract186.get("global_dt"),
        "formal_protocol": None,
        "worker_sha256": None,
        "worker_size_bytes": None,
        "worker_mtime_ns": None,
        "evidence": str(STAGE186 / "independent_gate.json"),
    }
    reuse = assess_reuse(qualification, candidate)
    continuity = {
        "stage196_stage204_same_worker_path": (
            summary196["process_registry"][0]["command_line"] == summary204["process_registry"][0]["command_line"]
        ),
        "stage196_stage204_same_library_sha256": (
            summary196["fresh_library"]["sha256"] == summary204["fresh_library"]["sha256"]
        ),
        "stage196_stage204_same_model_contract_sha256": (
            summary196["process_registry"][0]["expected_model_contract_sha256"]
            == summary204["process_registry"][0]["expected_model_contract_sha256"]
        ),
        "stage196_stage204_same_gauss_order": (
            summary196["ancf_numerical_contract"]["gauss_order"]
            == summary204["ancf_numerical_contract"]["gauss_order"]
        ),
        "stage196_stage204_same_max_newton": (
            summary196["ancf_numerical_contract"]["max_newton"]
            == summary204["ancf_numerical_contract"]["max_newton"]
        ),
        "stage196_executable_hash_recorded": False,
        "stage196_strict_dual_run_reference_recorded": False,
    }
    process_counts = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
    audit = {
        "stage_id": "stage4f_d_cpp_worker_numerical_qualification_reuse_v1",
        "run_id": "cpp_worker_numerical_qualification_reuse_205_001",
        "case_id": "cpp_worker_numerical_qualification_reuse_case_205_001",
        "operation": "offline_readonly_evidence_audit",
        "candidate": candidate,
        "qualification": qualification,
        "reuse": reuse,
        "stage196_to_stage204_continuity": continuity,
        "stage204_transport_gate": gate204["gate"],
        "old_evidence_modified": False,
        "old_runtime_reused": False,
        "real_process_starts": process_counts,
        "owned_residual": 0,
        "required_next_evidence": (
            "A strict MATLAB/C++ dual-run golden generated with gauss_order=3, "
            "max_newton=40, formal protocol 0.2.1, and a pinned worker SHA-256."
        ),
    }
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_NUMERICAL_QUALIFICATION_REUSE_V1_GATE: " + ("pass" if reuse["reuse_eligible"] else "do_not_pass"),
        "status": "pass" if reuse["reuse_eligible"] else "do_not_pass",
        "C++_ANCF_NUMERICAL_CORE_STATUS": reuse["C++_ANCF_NUMERICAL_CORE_STATUS"],
        "reason": reuse["errors"],
        "old_evidence_modified": False,
        "real_process_starts": process_counts,
        "owned_residual": 0,
        "next_real_cfd_authorization_eligible": bool(reuse["reuse_eligible"]),
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
    }
    write(RESULTS / "qualification_reuse_audit.json", audit)
    write(RESULTS / "stage4f_d_cpp_worker_numerical_qualification_reuse_v1_gate.json", gate)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "cpp_worker_numerical_qualification_reuse_report.md").write_text(
        "# Stage205 C++ numerical qualification reuse audit\n\n"
        "Stage204 transport confirmation remains pass, but numerical qualification reuse is fail-closed. "
        "The only strict MATLAB/C++ proof is Stage186 (Gauss=5, max_newton=50); "
        "the Stage204 production contract is Gauss=3, max_newton=40. Stage196 and Stage204 share "
        "worker path, library hash and model-contract hash, but Stage196 did not record a worker content hash "
        "or a formal strict dual-run reference. No MATLAB, OpenFOAM, WSL or CFD was started.\n",
        encoding="utf-8",
    )
    print(json.dumps(gate, ensure_ascii=False))
    return 0 if reuse["reuse_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
