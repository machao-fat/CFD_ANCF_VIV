"""Create a requirement-by-requirement audit without launching external solvers."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT / "results/111_cpp_worker_objective_coverage_v1"
DOCS = PROJECT / "docs/111_cpp_worker_objective_coverage_v1"


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=False)
    DOCS.mkdir(parents=True, exist_ok=False)
    requirements = [
        {"id": "cpp_worker_build", "status": "pass", "evidence": "results/97_cpp_worker_persistent_ipc_v1/cpp_worker_build_audit.json"},
        {"id": "resident_worker_persistent_ipc", "status": "pass_offline", "evidence": "results/97_cpp_worker_persistent_ipc_v1/mock_40step_audit.json"},
        {"id": "protocol_identity_and_ack", "status": "pass_offline", "evidence": "results/97_cpp_worker_persistent_ipc_v1/cpp_protocol_schema.json"},
        {"id": "fault_injection_fail_closed", "status": "pass_offline", "evidence": "results/97_cpp_worker_persistent_ipc_v1/ipc_fault_injection_audit.json"},
        {"id": "three_slice_barrier_checkpoint", "status": "pass_offline", "evidence": "results/100_cpp_worker_confirm_v1/repair_002/barrier_two_phase_audit.json"},
        {"id": "matlab_baseline_rollback", "status": "pass", "evidence": "results/100_cpp_worker_confirm_v1/matlab_worker_baseline_protection_audit.json"},
        {"id": "matlab_cpp_dual_run_engineering", "status": "pass_40_of_40", "evidence": "results/100_cpp_worker_confirm_v1/repair_005/accepted_source_dual_run_audit.json"},
        {"id": "matlab_cpp_dual_run_strict", "status": "not_completed_0_of_40", "evidence": "results/100_cpp_worker_confirm_v1/repair_005/accepted_source_dual_run_audit.json"},
        {"id": "real_openfoam_library", "status": "not_completed_fresh_build_required", "evidence": "results/110_cpp_worker_library_build_v1/stop_gate_audit.json"},
        {"id": "real_40_step_confirm", "status": "not_executed_authorization_missing", "evidence": "results/100_cpp_worker_confirm_v1/stage4f_d_cpp_worker_persistent_ipc_v1_confirm_gate.json"},
        {"id": "real_performance_comparison", "status": "not_evaluable_until_real_confirm", "evidence": "results/100_cpp_worker_confirm_v1/performance_comparison.json"},
    ]
    missing = [item["id"] for item in requirements if item["status"].startswith("not_")]
    audit = {
        "stage_id": "stage4f_d_cpp_worker_objective_coverage_v1",
        "run_id": "cpp_worker_objective_coverage_001",
        "case_id": "cpp_worker_objective_coverage_case_001",
        "requirements": requirements,
        "offline_requirements_passed": 7,
        "requirements_not_completed": missing,
        "status": "incomplete",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "C++_WORKER_PERSISTENT_IPC_STATUS": "not_completed",
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "old_evidence_modified": False,
    }
    (RESULTS / "objective_coverage_audit.json").write_text(json.dumps(audit, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_OBJECTIVE_COVERAGE_V1_GATE: do_not_pass",
        "status": "do_not_pass",
        "reason": "strict dual-run, fresh OpenFOAM library build, and real 40-step confirm remain incomplete",
        "requirements_not_completed": missing,
        "real_process_starts": audit["real_process_starts"],
        "owned_residual": 0,
    }
    (RESULTS / "stage4f_d_cpp_worker_objective_coverage_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    report = """# C++ Worker Persistent IPC Objective Coverage

离线 C++ worker、持久 IPC、三 slice barrier、故障注入和回退基线已通过。
严格 MATLAB/C++ 双算、fresh OpenFOAM library build 和真实 40-step confirm 尚未完成。

因此不能将 `C++_WORKER_PERSISTENT_IPC_STATUS` 标记为 completed，也不能将 mock 性能当作真实 CFD 加速比。
"""
    (DOCS / "objective_coverage_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(gate, ensure_ascii=True, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
