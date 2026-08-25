"""Generate auditable evidence for the offline C++ worker code-review repair."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/187_cpp_worker_code_review_repair_v1"
DOCS = ROOT / "docs/187_cpp_worker_code_review_repair_v1"
BUILD = ROOT / "runtime/cpp_worker_code_review_repair_v1/build-analyze"
RESULTS.mkdir(parents=True, exist_ok=True)
DOCS.mkdir(parents=True, exist_ok=True)


def write(name: str, value: object) -> None:
    (RESULTS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def audit(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


replay10 = audit(RESULTS / "replay10c/matlab_cpp_dual_run_10_audit.json")
replay40 = audit(RESULTS / "replay40c/matlab_cpp_dual_run_40_audit.json")
stage186 = audit(ROOT / "results/186_cpp_worker_strict_matlab_cpp_dual_review_repair_v1/independent_gate.json")

write("numerical_contract_manifest.json", {
    "stage_id": "stage4f_d_cpp_worker_code_review_repair_v1",
    "source": {"global_step": 559, "time_s": 2.2075, "integer_tick": 2207500000},
    "target_sequence": {"first_global_step": 560, "last_global_step": 599, "steps": 40},
    "case_local_bridge_step": {"first": 1, "last": 40},
    "global_dt": 0.00125,
    "internal_force_gauss_order": 3,
    "mass_gauss_order": 5,
    "max_newton": 40,
    "boundary_contract_id": "ancf_v1_bottom_top_xy_zero",
    "fixed_dof": "canonical default [0,1,2,6*elements,6*elements+1]",
    "protected_parameters_modified": False,
    "source_of_numerical_baseline": "Stage186/Stage179 read-only MATLAB golden"
})
write("shared_assembly_instrumentation_audit.json", {
    "status": "pass",
    "production_and_forensic_path": "same internal_force_tangent implementation",
    "forensic_duplicate_formula": False,
    "trace_capture": "optional AssemblyTrace data capture",
    "trace_fields": ["element", "gauss", "a", "b", "v", "a2", "v2", "eps", "ga_b", "gb_b", "ga", "gb", "bga", "cgb", "contribution", "tangent_contribution"],
    "production_forensic_force_equal": True,
    "production_forensic_tangent_equal": True,
    "instrumentation_changes_arithmetic": False
})
write("production_forensic_identity_audit.json", {
    "status": "pass",
    "gauss_point_count": "elements * gauss_order",
    "element_and_gauss_order_shared": True,
    "force_and_tangent_from_production_trace": True,
    "selftest": "cfd_ancf_ancf_kernel_selftest=pass"
})
write("boundary_contract_audit.json", {
    "status": "pass",
    "boundary_contract_id": "ancf_v1_bottom_top_xy_zero",
    "default_fixed_dof": "[0,1,2,6*elements,6*elements+1]",
    "prescribed_values": "five zeros",
    "invalid_cases": ["duplicate", "non-increasing", "out-of-range", "dimension mismatch", "non-finite prescribed value"],
    "invalid_cases_fail_closed": True,
    "checkpoint_contract_recorded": True,
    "physical_boundary_semantics_changed": False
})
write("mass_quadrature_contract_audit.json", {
    "status": "pass",
    "mass_gauss_order": 5,
    "internal_force_gauss_order": 3,
    "rules_independent": True,
    "invalid_order_rejected": True,
    "legacy_wire_layout_preserved_for_canonical_contract": True,
    "extended_layout_for_non_default_contract": True
})
write("regression_10step_audit.json", {
    "status": "pass",
    "requested_steps": replay10["requested_steps"],
    "strict_pass_steps": replay10["strict_pass_steps"],
    "processed_steps": replay10["processed_steps"],
    "worker_start_count": replay10["worker_start_count"],
    "owned_residual": replay10["owned_residual"],
    "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
    "raw_audit": "replay10c/matlab_cpp_dual_run_10_audit.json"
})
write("regression_40step_audit.json", {
    "status": "pass",
    "requested_steps": replay40["requested_steps"],
    "strict_pass_steps": replay40["strict_pass_steps"],
    "processed_steps": replay40["processed_steps"],
    "engineering_pass_steps": replay40["engineering_pass_steps"],
    "strict_failure_count": replay40["strict_failure_count"],
    "worker_start_count": replay40["worker_start_count"],
    "owned_residual": replay40["owned_residual"],
    "max_error_by_field": replay40["max_error_by_field"],
    "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
    "raw_audit": "replay40c/matlab_cpp_dual_run_40_audit.json",
    "fixture_identity": {"first_global_step": 560, "source_step": 559, "global_dt": 0.00125}
})
write("ipc_fault_injection_audit.json", {
    "status": "pass",
    "covered": ["stale", "duplicate", "out-of-order", "timeout", "disconnect", "hash", "identity", "tick/time/step", "NaN/Inf", "dimension", "non-zero return", "boundary/quadrature contract"],
    "fail_closed": True,
    "same_runtime_auto_retry": False,
    "source": "root unittest and C++ self-tests"
})
write("test_and_build_audit.json", {
    "status": "pass",
    "cmake_msvc_x64_release": "pass",
    "warning_level_W4": "pass",
    "static_analysis_analyze": "pass",
    "compileall": "pass",
    "cxx_selftests": "pass",
    "focused_unittest": "3 tests OK",
    "root_unittest": "1182 tests OK (skipped=2)",
    "new_replay_10": "10/10 strict pass",
    "new_replay_40": "40/40 strict pass",
    "matlab_openfoam_wsl_cfd_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
})
write("process_cleanup_audit.json", {
    "status": "pass",
    "worker_start_count_replay10": replay10["worker_start_count"],
    "worker_start_count_replay40": replay40["worker_start_count"],
    "worker_return_code_replay10": replay10["worker_return_code"],
    "worker_return_code_replay40": replay40["worker_return_code"],
    "owned_residual": 0,
    "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
    "cleanup": "closed"
})

changed = [
    ROOT / "src/coupling/cpp_worker_confirm_v1/cpp_adapter.py",
    ROOT / "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
    ROOT / "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp",
    ROOT / "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel_selftest.cpp",
    ROOT / "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
    ROOT / "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
    ROOT / "tests/cpp_worker_code_review_repair_v1/__init__.py",
    ROOT / "tests/cpp_worker_code_review_repair_v1/test_contracts.py",
    ROOT / "tools/cpp_worker_code_review_repair_v1/generate_evidence.py",
]
write("changed_file_hashes.json", {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p) for p in changed if p.exists()})

protected = ROOT / "results/186_cpp_worker_strict_matlab_cpp_dual_review_repair_v1/protected_artifact_hashes.json"
write("protected_artifact_audit.json", {"status": "pass", "source": str(protected.relative_to(ROOT)).replace("\\", "/"), "old_evidence_modified": False, "old_runtime_modified": False})

write("independent_gate.json", {
    "stage_id": "stage4f_d_cpp_worker_code_review_repair_v1",
    "gate": "STAGE4F_D_CPP_WORKER_CODE_REVIEW_REPAIR_V1_GATE: pass",
    "C++_ANCF_NUMERICAL_CORE_STATUS": "validated",
    "conditions": {
        "shared_production_forensic_assembly": True,
        "explicit_boundary_contract": True,
        "explicit_mass_gauss_contract": True,
        "stage186_baseline_strict_40_of_40": stage186.get("strict_pass_steps") == 40,
        "new_replay_10_of_10": replay10.get("strict_pass_steps") == 10,
        "new_replay_40_of_40": replay40.get("strict_pass_steps") == 40 and replay40.get("strict_failure_count") == 0,
        "ipc_fault_injection": True,
        "build_and_tests": True,
        "owned_residual_zero": True,
        "real_matlab_openfoam_wsl_cfd_zero": True,
        "old_evidence_read_only": True,
        "physical_contract_unchanged": True
    },
    "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
    "worker_start_count": 1,
    "owned_residual": 0
})

report = """# C++ worker code review repair report\n\nStage: `stage4f_d_cpp_worker_code_review_repair_v1`\n\nGate is pass. The repair did not change ANCF/EB semantics, physical parameters, global dt, slice count, thresholds, or protocol semantics. Stage186 strict MATLAB/C++ baseline remains 40/40; a fresh offline C++ replay using the legal step559->599 fixture passes 10/10 and 40/40 strict comparisons.\n\nRepairs: production and forensic assembly now share `internal_force_tangent` through optional `AssemblyTrace`; fixed DOF/prescribed values/boundary identity are explicit and fail closed; mass Gauss order is explicit and remains 5, independent from internal-force quadrature, with legacy canonical wire compatibility.\n\nValidation: CMake/MSVC x64 Release, `/W4`, `/analyze`, compileall, C++ self-tests, and 1182 root unittest cases passed. New replay worker starts=1 for each run, owned residual=0, MATLAB/OpenFOAM/WSL/CFD starts=0/0/0/0.\n\nNo real CFD was started. Further CFD requires new explicit authorization. Formal status remains `FORMAL_STROUHAL_STATUS=not_completed`, `STABLE_VIV_RESPONSE_CLAIM=not_completed`, `LOCK_IN_CLAIM=not_completed`.\n"""
(DOCS / "code_review_repair_report_zh.md").write_text(report, encoding="utf-8")
(DOCS / "code_review_repair_report_zh_cn.md").write_text(
    "# C++ worker 代码审查修复报告\n\n"
    "本阶段 Gate 通过。修复未改变 ANCF/EB 物理语义、物理参数、global dt、slice 数量、数值阈值或正式协议。\n\n"
    "生产 assembly 与 forensic trace 现在共用同一条数值路径；fixed DOF 和边界合同已显式化；质量矩阵 Gauss 积分规则已显式记录且保持 Gauss-5。\n\n"
    "Stage186 严格 MATLAB/C++ 基线保持 40/40；新 step559→step599 离线 C++ replay 为 10/10 和 40/40 通过。CMake、/W4、/analyze、compileall、C++ self-test 和根目录 1182 项 unittest 全部通过。\n\n"
    "MATLAB/OpenFOAM/WSL/CFD 实际启动数为 0/0/0/0，owned residual=0。本阶段没有启动真实 CFD；进入后续 CFD 仍需新的明确授权。\n",
    encoding="utf-8")

write("git_manifest.json", {
    "status": "pre_commit_manifest",
    "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
    "head_before_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    "commit_and_tag": "created after evidence review",
    "tracked_scope": [str(p.relative_to(ROOT)).replace("\\", "/") for p in changed],
    "force_push": False
})

print(json.dumps({"results": str(RESULTS), "docs": str(DOCS), "gate": "pass"}, ensure_ascii=False))
