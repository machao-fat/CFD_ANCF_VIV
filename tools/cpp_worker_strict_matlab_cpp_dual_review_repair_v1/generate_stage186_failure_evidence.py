# -*- coding: utf-8 -*-
"""Write fail-closed Stage186 evidence after the bounded MATLAB attempt."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/186_cpp_worker_strict_matlab_cpp_dual_review_repair_v1"
DOCS = ROOT / "docs/186_cpp_worker_strict_matlab_cpp_dual_review_repair_v1"
RUNTIME = ROOT / "runtime/cpp_worker_strict_matlab_cpp_dual_review_repair_v1"
STAGE = "stage4f_d_cpp_worker_strict_matlab_cpp_dual_review_repair_v1"
RUN = "cpp_worker_strict_matlab_cpp_dual_review_001"
CASE = "cpp_worker_strict_matlab_cpp_dual_review_case_001"


def write_json(name: str, value: object) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    source = ROOT / "runtime/cpp_worker_persistent_ipc_v1/matlab_dual_011/accepted_step559_seed.mat"
    source_hash = sha256(source)
    stderr = RUNTIME / "matlab_stderr.log"
    stdout = RUNTIME / "matlab_stdout.log"
    code_review = {
        "stage_id": STAGE,
        "status": "complete_with_strict_numerical_blocker",
        "findings": [
            {"id": "STRICT_NUMERICAL_EQUIVALENCE_NOT_PROVEN", "severity": "high",
             "location": "results/183_cpp_worker_comprehensive_audit_repair_v1/numerical_equivalence_audit.json",
             "evidence": "strict_pass_steps=0/40; first_failed_step=560; internal_force mismatch",
             "impact": "C++ numerical core cannot be validated or connected to CFD",
             "repair": "export same-schema MATLAB trace, locate first intermediate difference, then patch C++",
             "regression": "single-step, 10-step, 40-step strict dual run",
             "status": "open"},
            {"id": "MATLAB_TRACE_OUTPUT_MISSING", "severity": "high",
             "location": "runtime/cpp_worker_strict_matlab_cpp_dual_review_repair_v1/matlab_stderr.log",
             "evidence": "MATLAB exit code 0 but required trace file is absent; Java shutdown exception in stderr",
             "impact": "first real internal-force divergence cannot be located",
             "repair": "stop fail-closed; require a new independent MATLAB authorization/runtime",
             "regression": "trace existence, schema and finite-value audit",
             "status": "open"},
            {"id": "TANGENT_TRACE_INCOMPLETE", "severity": "high",
             "location": "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp:84-105; ancf_forensic_diagnostic.cpp:49-66",
             "evidence": "ForensicPoint and emitted text contain force contributions but no per-Gauss tangent contribution or element tangent",
             "impact": "required tangent-level MATLAB/C++ comparison is not yet possible",
             "repair": "instrument the production assembly path and serialize tangent contributions before numerical repair",
             "regression": "trace schema count and finite tangent comparison",
             "status": "open_not_modified_before_first_difference"},
            {"id": "FORENSIC_TRACE_RECOMPUTES_ASSEMBLY", "severity": "high",
             "location": "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp:254-325",
             "evidence": "diagnostic code duplicates formulas instead of capturing element_force_tangent's production contributions",
             "impact": "a diagnostic trace can diverge from the actual worker path and conceal the first production difference",
             "repair": "share one instrumented assembly path; do not maintain a second numerical implementation",
             "regression": "production-vs-trace force/tangent identity test",
             "status": "open_not_modified_before_first_difference"},
            {"id": "TANGENT_REDUCTION_ORDER_CANDIDATE", "severity": "medium",
             "location": "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp:137-149",
             "evidence": "four tangent terms are fused in one scalar reduction, while MATLAB forms separate matrix products then adds them",
             "impact": "possible ulp-level Newton increment/internal-force drift",
             "repair": "confirm with intermediate trace, then preserve MATLAB operation grouping if proven",
             "regression": "Gauss tangent contribution dual comparison",
             "status": "candidate_unconfirmed"},
            {"id": "WIRE_PREDICTOR_ORDER_CANDIDATE", "severity": "medium",
             "location": "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp:361-367",
             "evidence": "wire predictor recomputes dt_s*dt_s, while advance uses a named dt2 temporary",
             "impact": "reported predictor may differ by ulps even if accepted q is unchanged",
             "repair": "align operation grouping only after trace confirms it; do not use as a threshold workaround",
             "regression": "predictor byte/field dual comparison",
             "status": "candidate_unconfirmed"},
            {"id": "FIXED_DOF_CONTRACT_HARDCODED", "severity": "medium",
             "location": "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp:392-399",
             "evidence": "worker hardcodes bottom and top x/y prescribed values rather than reading boundary fields",
             "impact": "current protected contract matches, but other legal boundary contracts could silently diverge",
             "repair": "only consider a contract-preserving model boundary representation after numerical blocker is isolated",
             "regression": "boundary-contract audit",
             "status": "verified_current_contract_no_change"},
            {"id": "MASS_RULE_CONTRACT_SPECIFIC", "severity": "medium",
             "location": "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp:334-339",
             "evidence": "reference state builds mass with fixed five-point quadrature",
             "impact": "would mismatch a Gauss-3 mass contract, but current MATLAB contract explicitly uses Gauss-5 mass",
             "repair": "retain until a contract mismatch is proven",
             "regression": "mass contract audit",
             "status": "verified_current_contract_no_change"}
        ],
        "protected_contract_modified": False,
        "cpp_numerical_files_modified": [],
    }
    write_json("code_review_findings.json", code_review)
    write_json("numerical_contract_manifest.json", {
        "stage_id": STAGE, "run_id": RUN, "case_id": CASE,
        "source": "runtime/cpp_worker_persistent_ipc_v1/matlab_dual_011/accepted_step559_seed.mat",
        "source_sha256": source_hash, "source_global_step": 559, "target_global_step": 560,
        "source_time_s": 2.2075, "target_time_s": 2.20875,
        "source_integer_tick": 2207500000, "target_integer_tick": 2208750000,
        "global_dt_s": 0.00125, "gauss_order": 5, "max_newton": 50,
        "q_size": 102, "qdot_size": 102, "qddot_size": 102, "base_load_size": 102,
        "slice_force_shape": [3, 3], "contract_match": True,
        "physical_parameters_modified": False, "thresholds_modified": False,
        "matlab_reference_modified": False, "formal_protocol_modified": False,
    })
    write_json("matlab_step560_trace_manifest.json", {
        "stage_id": STAGE, "run_id": RUN, "case_id": CASE,
        "status": "do_not_pass", "matlab_start_count": 1,
        "command_purpose": "single bounded MATLAB intermediate trace export",
        "exit_code": 0, "trace_path": "runtime/cpp_worker_strict_matlab_cpp_dual_review_repair_v1/matlab_step560_trace.json",
        "trace_exists": False, "stdout": "runtime/cpp_worker_strict_matlab_cpp_dual_review_repair_v1/matlab_stdout.log",
        "stderr": "runtime/cpp_worker_strict_matlab_cpp_dual_review_repair_v1/matlab_stderr.log",
        "failure_classification": "required_output_missing_matlab_java_shutdown",
        "raw_stderr_sha256": sha256(stderr), "raw_stdout_sha256": sha256(stdout),
        "retry_performed": False, "same_runtime_retry": False,
        "next_matlab_launch_requires_new_authorization": True,
        "process_cleanup": "completed",
    })
    write_json("cpp_step560_trace_manifest.json", {
        "stage_id": STAGE, "status": "not_started_after_matlab_output_failure",
        "cpp_trace_generated": False, "reason": "verification sequence stopped before C++ trace",
    })
    write_json("step560_first_difference_audit.json", {
        "stage_id": STAGE, "status": "not_evaluable",
        "first_difference": None, "strict_matlab_cpp_steps_passed": 0,
        "strict_matlab_cpp_steps_total": 40,
        "reason": "MATLAB trace output missing; no C++ comparison permitted",
    })
    write_json("internal_force_forensic_comparison.json", {
        "stage_id": STAGE, "status": "not_evaluable", "comparison_performed": False,
        "reason": "same-schema MATLAB intermediate trace unavailable",
        "prior_readonly_observation": {"step": 560, "internal_force_max_abs": 4.866160452365875e-07,
                                        "internal_force_max_relative": 4.891825378743019e-08},
    })
    write_json("numerical_repair_manifest.json", {
        "stage_id": STAGE, "status": "not_started_fail_closed", "first_difference_confirmed": False,
        "cpp_files_modified": [], "physics_parameters_modified": False, "thresholds_modified": False,
    })
    write_json("replay_10step_audit.json", {"stage_id": STAGE, "status": "not_started_after_matlab_failure", "steps_total": 10, "steps_processed": 0})
    write_json("replay_40step_audit.json", {"stage_id": STAGE, "status": "not_started_after_matlab_failure", "steps_total": 40, "steps_processed": 0})
    write_json("ipc_fault_injection_audit.json", {"stage_id": STAGE, "status": "not_started_after_matlab_failure", "same_runtime_retry": False})
    write_json("test_and_build_audit.json", {
        "stage_id": STAGE, "status": "not_started_after_matlab_failure", "cmake_release": "not_run",
        "w4": "not_run", "analyze": "not_run", "compileall": "not_run_after_fail_closed_stop",
        "specialized_tests": "not_run", "root_unittest": "not_run",
    })
    write_json("process_cleanup_audit.json", {
        "stage_id": STAGE, "matlab_start_count": 1, "openfoam_start_count": 0,
        "wsl_start_count": 0, "cfd_start_count": 0, "owned_worker_start_count": 0,
        "owned_residual": 0, "cleanup_status": "pass", "target_processes_after_run": 0,
    })
    protected = [
        ROOT / "results/183_cpp_worker_comprehensive_audit_repair_v1/independent_gate.json",
        ROOT / "results/184_cpp_worker_numerical_forensic_repair_v1/independent_gate.json",
        ROOT / "results/185_cpp_worker_matlab_intermediate_trace_repair_v1/independent_gate.json",
        ROOT / "src/structure_ancf_matlab/ancf_internal_force_tangent.m",
        source,
    ]
    write_json("protected_artifact_hashes.json", {
        "algorithm": "SHA256", "stage_id": STAGE,
        "files": {p.relative_to(ROOT).as_posix(): sha256(p) for p in protected},
        "old_evidence_modified": False, "old_runtime_modified": False,
    })
    gate = {
        "stage_id": STAGE, "run_id": RUN, "case_id": CASE,
        "gate": "STAGE4F_D_CPP_WORKER_STRICT_MATLAB_CPP_DUAL_REVIEW_REPAIR_V1_GATE: do_not_pass",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "reason": "MATLAB required trace output missing after the single authorized launch; strict dual comparison and repair were fail-closed",
        "real_process_starts": {"MATLAB": 1, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0, "old_evidence_modified": False, "old_runtime_reused": False,
        "new_matlab_authorization_required": True,
    }
    write_json("independent_gate.json", gate)
    report = f"""# Stage186 C++ worker 严格 MATLAB/C++ 双算审查报告\n\n## 结论\n\n本阶段 Gate 按 fail-closed 保持 `do_not_pass`。合法 step559 seed 合同已验证，但唯一一次 MATLAB 导出进程返回码为 0 且没有生成要求的 trace 文件；stderr 保存了 MATLAB R2021b Java shutdown 初始化异常。因此没有执行 C++ trace、首个差异比较、C++ 数值修改或后续测试。\n\n## 代码审查 findings\n\n- 严格 MATLAB/C++ 等价仍为 0/40，step560 的 internal_force 差异仍未被中间量证据定位。\n- C++ forensic trace 当前缺少逐 Gauss tangent contribution/element tangent 输出。\n- forensic API 重复实现 internal-force 公式，没有直接捕获生产 assembly 路径。\n- tangent 四项矩阵乘积在 C++ 中合并到一个标量 reduction，是待 MATLAB trace 证实的浮点顺序候选。\n- wire predictor 的 `dt_s*dt_s` 与 advance 的命名 `dt2` 计算路径不同，是待验证的 ulp 候选。\n- 固定 DOF 和质量积分规则与当前保护合同一致，本阶段未修改。\n\n## 本阶段执行\n\n- 合同：step559→560、dt=0.00125、Gauss=5、max_newton=50，合同匹配。\n- MATLAB 启动：1 次；trace：缺失；原始 stdout/stderr 已保存。\n- OpenFOAM=0，WSL=0，CFD=0；owned residual=0；目标进程清理完成。\n- C++ 数值文件、MATLAB 参考实现、物理参数、阈值和正式协议均未修改。\n\n## Gate\n\n`STAGE4F_D_CPP_WORKER_STRICT_MATLAB_CPP_DUAL_REVIEW_REPAIR_V1_GATE: do_not_pass`\n\n`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`\n\n需要新的明确 MATLAB 授权和全新 runtime，才能重做 trace 导出并继续首个分歧定位；在 Gate 通过前不得启动 OpenFOAM、WSL、CFD 或真实 confirm。\n"""
    (DOCS / "report_zh.md").write_text(report, encoding="utf-8")
    # Hash all stage evidence except the hash manifest itself.
    files = sorted(p for p in RESULTS.iterdir() if p.is_file() and p.name not in {"changed_file_hashes.json", "git_manifest.json"})
    files += [DOCS / "report_zh.md", Path(__file__),
              Path(__file__).with_name("export_step560_matlab_intermediate_trace.m")]
    write_json("changed_file_hashes.json", {"algorithm": "SHA256", "stage_id": STAGE,
                                             "files": {p.relative_to(ROOT).as_posix(): sha256(p) for p in files}})
    print(json.dumps(gate, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
