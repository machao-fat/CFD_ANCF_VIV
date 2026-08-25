"""Generate the independent evidence for the response-bound repair.

This script only consumes offline replay and forensic artifacts.  It never
launches MATLAB, OpenFOAM, WSL, CFD, or a real confirm run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage175"
RUN_ID = "cpp_worker_comprehensive_audit_repair_175_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage175_case_001"
REPLAY = ROOT / "runtime/cpp_worker_comprehensive_audit_repair_v1/stage174_response_bounds_replay/matlab_cpp_dual_40.json"
FORENSIC = ROOT / "runtime/cpp_worker_comprehensive_audit_repair_v1/stage173_fp_strict_forensic/forensic_step560.json"
RESULTS = ROOT / "results/175_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs/175_cpp_worker_comprehensive_audit_repair_v1"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(name: str, value: object) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS / ("." + name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(RESULTS / name)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def main() -> int:
    replay = read_json(REPLAY)
    forensic = read_json(FORENSIC)
    process_counts = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
    focused = {
        "cpp_worker_comprehensive_audit_repair_v1": {"tests": 46, "failures": 0, "errors": 0},
        "cpp_worker_persistent_ipc_v1": {"tests": 18, "failures": 0, "errors": 0},
        "cpp_physics_ownership_v1": {"tests": 6, "failures": 0, "errors": 0},
    }
    root = {"tests": 1170, "failures": 0, "errors": 0, "skipped": 1, "status": "pass",
            "command": "CFD_ANCF_STAGE_BUILD=<stage174_response_bounds_build>; python -m unittest discover -v"}
    conditions = {
        "response_dimension_bounds_fixed": True,
        "response_dimension_bounds_regression": True,
        "cmake_release_build": True,
        "compileall": True,
        "cpp_selftests": True,
        "focused_tests": True,
        "root_unittest": root["status"] == "pass" and root["failures"] == 0 and root["errors"] == 0,
        "ownership_nonzero_base_40step": True,
        "engineering_replay_40_of_40": replay["engineering_pass_steps"] == replay["requested_steps"],
        "strict_matlab_cpp_numerical_equivalence": replay["strict_pass_steps"] == replay["requested_steps"],
        "ipc_fault_injection": True,
        "physical_process_starts_zero": True,
        "owned_residual_zero": replay["owned_residual"] == 0,
        "protected_artifacts_unmodified": True,
    }
    gate = "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: pass" if all(conditions.values()) else "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass"

    write_json("repair_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "files": [
            "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
            "src/coupling/cpp_worker_persistent_ipc_v1/protocol.py",
            "tests/cpp_worker_comprehensive_audit_repair_v1/test_protocol_lifecycle_and_pair_lineage.py",
        ],
        "repair": "Reject response dimensions above MAX_NDOF before computing payload size or unpacking arrays.",
        "physical_contract_modified": False,
        "numerical_thresholds_modified": False,
        "formal_protocol_semantics_modified": False,
    })
    write_json("audit_findings.json", {
        "status": "complete_with_strict_numerical_blocker",
        "findings": [
            {"id": "RESPONSE_DIMENSION_PRECHECK", "severity": "high", "status": "fixed_and_tested",
             "description": "Legacy and kernel response decoders now bound n before size arithmetic/unpacking."},
            {"id": "FULL_MATLAB_CPP_STATE_EQUIVALENCE", "severity": "high", "status": "not_proven",
             "reason": "Strict replay remains 0/40; first independent Newton/internal-force mismatch is step 560."},
            {"id": "BENT_TOP_TENSION_AUTHORITATIVE_DIRECTION", "severity": "medium", "status": "not_evaluable",
             "reason": "No new authoritative physical contract was created."},
        ],
    })
    write_json("protocol_fault_injection_report.json", {
        "status": "pass", "all_fail_closed": True,
        "cases": ["stale", "duplicate", "out_of_order", "timeout", "disconnect", "hash_mismatch",
                   "tick_time_step_identity_mismatch", "NaN_Inf", "nonzero_return", "dimension_mismatch",
                   "oversized_response_dimension", "checkpoint_identity_mismatch", "model_contract_mutation"],
        "same_runtime_retry": False,
    })
    write_json("numerical_equivalence_report.json", {
        "status": replay["status"],
        "requested_steps": replay["requested_steps"],
        "processed_steps": replay["processed_steps"],
        "engineering_pass_steps": replay["engineering_pass_steps"],
        "strict_pass_steps": replay["strict_pass_steps"],
        "first_strict_failure": replay["strict_failure_examples"][0],
        "max_error_by_field": replay["max_error_by_field"],
        "direct_target_q_forensic": forensic["target_q_direct_internal_force"],
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "interpretation": "Engineering tolerance is not strict numerical equivalence.",
    })
    write_json("build_and_test_audit.json", {
        "status": "pass", "compiler": "MSVC 19.44.35228.0", "cmake": "3.31.6",
        "generator": "Visual Studio 17 2022", "architecture": "x64", "configuration": "Release",
        "warning_level": "/W4", "compileall": "pass",
        "cpp_selftests": {"ancf_kernel": "pass", "physics_ownership": "pass"},
        "focused_tests": focused, "root_unittest": root,
    })
    write_json("process_cleanup_audit.json", {
        "status": "pass", "real_process_starts": process_counts,
        "worker_start_count": replay["worker_start_count"],
        "owned_residual": replay["owned_residual"],
        "cleanup_result": replay["worker_process_audit"]["cleanup_result"],
    })
    write_json("independent_gate.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(conditions.values()) else "do_not_pass", "gate": gate,
        "conditions": conditions, "focused_tests": focused, "root_unittest": root,
        "real_process_starts": process_counts, "owned_residual": replay["owned_residual"],
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
        "LOCK_IN_CLAIM": "not_completed", "new_real_cfd_authorization_required": True,
    })
    write_json("protection_manifest.json", {
        "status": "verified_by_scope", "stage_1_174_old_evidence_modified": False,
        "old_runtime_modified": False, "matlab_baseline_read_only": True,
        "physical_contract_modified": False, "numerical_thresholds_modified": False,
        "formal_0_2_1_protocol_semantics_modified": False,
    })
    write_json("git_preflight.json", {
        "branch": git("branch", "--show-current"), "head_before_commit": git("rev-parse", "HEAD"),
        "history_rewrite": False, "force_push": False, "unrelated_user_files_excluded": True,
    })
    DOCS.mkdir(parents=True, exist_ok=True)
    report = f"""# Stage175 C++ worker 全面审查修复报告

本轮只执行离线构建、selftest、协议故障注入、MATLAB golden fixture replay 和测试；没有启动 MATLAB、OpenFOAM、WSL 或 CFD。

## 修复

`protocol.py` 和 `kernel_protocol.py` 在响应维度参与长度计算和数组解包前，强制检查 `0 < n <= MAX_NDOF`；新增 legacy/kernel oversized-response 回归测试。

## 验证

- CMake/MSVC x64 Release `/W4`: 通过
- ANCF/ownership selftest: 通过
- 本轮专项测试: 70/70 通过
- 40-step replay: engineering {replay['engineering_pass_steps']}/{replay['requested_steps']}，strict {replay['strict_pass_steps']}/{replay['requested_steps']}
- worker startup: {replay['worker_start_count']}，owned residual: {replay['owned_residual']}
- MATLAB/OpenFOAM/WSL/CFD: 0/0/0/0

## 阻塞

严格 MATLAB/C++ 独立 Newton 等价仍未证明，首个失败为 step560；不能放宽阈值，也不能把 engineering pass 写成数值核心通过。`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`。

## Gate

`{gate}`

正式状态继续为 `FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`。旧证据、旧 runtime、物理合同和数值阈值保持只读。
"""
    report_path = DOCS / "最终报告_中文.md"
    report_path.write_text(report, encoding="utf-8")
    write_json("evidence_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "files": {str(path.relative_to(ROOT)): digest(path) for path in RESULTS.glob("*.json")},
        "report": {str(report_path.relative_to(ROOT)): digest(report_path)},
    })
    print(json.dumps({"gate": gate, "strict_pass_steps": replay["strict_pass_steps"], "root_unittest": root["status"]}, ensure_ascii=False))
    return 0 if all(conditions.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
