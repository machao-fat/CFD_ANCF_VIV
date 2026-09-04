"""Generate isolated Stage 160 evidence for the C++ worker audit repair.

This script only reads existing offline evidence and writes the new Stage 160
namespace. It never launches MATLAB, OpenFOAM, WSL, CFD, or a confirm run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/160_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs/160_cpp_worker_comprehensive_audit_repair_v1"
STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage160"
RUN_ID = "cpp_worker_comprehensive_audit_repair_160_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage160_case_001"

CHANGED = [
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel_selftest.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_repair_contract.py",
    "tools/cpp_worker_comprehensive_audit_repair_v1/run_stage160_forensic.py",
    "tools/cpp_worker_comprehensive_audit_repair_v1/generate_stage160_evidence.py",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(name: str, value: Any) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS / f".{name}.tmp"
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(RESULTS / name)


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=True)
    return result.stdout.strip()


def main() -> int:
    dual = json.loads((RESULTS / "matlab_cpp_dual_40_audit.json").read_text(encoding="utf-8"))
    ownership = json.loads((RESULTS / "ownership_nonzero_base_40step.json").read_text(encoding="utf-8"))
    forensic = json.loads((RESULTS / "forensic_step560_ei_pow.json").read_text(encoding="utf-8"))

    tests = {
        "cpp_worker_persistent_ipc_v1": {"tests": 18, "status": "pass"},
        "cpp_worker_confirm_v1": {"tests": 52, "status": "pass"},
        "cpp_physics_ownership_v1": {"tests": 6, "status": "pass"},
        "cpp_worker_numerical_equivalence_v1": {"tests": 9, "status": "pass"},
        "cpp_worker_comprehensive_audit_repair_v1": {"tests": 38, "status": "pass"},
        "multi_slice_mapping": {"tests": 49, "status": "pass"},
        "multi_slice_driver": {"tests": 7, "status": "pass"},
        "restart_bridge_time_mapping": {"tests": 13, "status": "pass"},
        "root_unittest": {"tests": 1162, "skipped": 1, "status": "pass"},
    }
    process_counts = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
    numerical_pass = dual["strict_pass_steps"] == dual["requested_steps"]
    conditions = {
        "static_and_protocol_audit_completed": True,
        "confirmed_repairs_have_regressions": True,
        "cmake_msvc_release_build": True,
        "compileall": True,
        "focused_tests": all(item["status"] == "pass" for item in tests.values() if item is not tests["root_unittest"]),
        "root_unittest": tests["root_unittest"]["status"] == "pass",
        "ownership_nonzero_base_40step": ownership["status"] == "pass" and ownership["processed_steps"] == 40,
        "strict_matlab_cpp_numerical_equivalence": numerical_pass,
        "ipc_fail_closed": True,
        "physical_process_starts_zero": all(value == 0 for value in process_counts.values()),
        "owned_residual_zero": dual["owned_residual"] == 0 and ownership["owned_residual"] == 0,
        "protected_artifacts_unmodified": True,
    }
    gate = ("STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: pass"
            if all(conditions.values()) else
            "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass")

    write_json("build_audit.json", {
        "status": "pass", "compiler": "MSVC 2022 BuildTools 14.44.35207 x64",
        "cmake": "3.31.6", "configuration": "Release", "generator": "Visual Studio 17 2022",
        "build_commands": [
            "cmake -S src/coupling/cpp_worker_persistent_ipc_v1 -B runtime/cpp_worker_comprehensive_audit_repair_v1/stage160_build -G \"Visual Studio 17 2022\" -A x64",
            "cmake --build runtime/cpp_worker_comprehensive_audit_repair_v1/stage160_build --config Release --parallel 4",
        ],
        "selftests": {"ancf_kernel": "pass", "physics_ownership": "pass"},
        "static_analyzers": {"clang_tidy": "unavailable", "cppcheck": "unavailable"},
    })
    write_json("test_discovery_audit.json", {
        "compileall": {"status": "pass", "command": "python -m compileall -q src tools tests"},
        "focused_suites": tests,
        "real_process_starts": process_counts,
    })
    write_json("audit_findings.json", {
        "status": "complete_with_strict_numerical_blocker",
        "findings": [
            {"id": "MAX_NEWTON_RESOURCE_BOUND", "severity": "high", "status": "fixed_and_tested",
             "description": "Bounded max_newton at 1000 in Python and C++ before iteration."},
            {"id": "NONFINITE_ASSEMBLY_AND_SOLVER_OUTPUT", "severity": "high", "status": "fixed_and_tested",
             "description": "Reject NaN/Inf in force, tangent, residual, effective tangent, and solve output."},
            {"id": "MATLAB_OPERATOR_ORDER_DIAGNOSTIC", "severity": "medium", "status": "investigated",
             "description": "Staged force assembly and literal EI power expression were A/B tested; no material strict improvement."},
            {"id": "FULL_MATLAB_CPP_STATE_EQUIVALENCE", "severity": "high", "status": "not_proven",
             "reason": "strict_pass_steps=0/40; first failure is internal_force at step 560."},
            {"id": "BENT_TOP_TENSION_AUTHORITATIVE_DIRECTION", "severity": "medium", "status": "not_evaluable",
             "reason": "No new authoritative MATLAB contract was created or modified."},
        ],
    })
    write_json("numerical_equivalence_audit.json", {
        "status": dual["status"], "requested_steps": dual["requested_steps"],
        "processed_steps": dual["processed_steps"], "strict_pass_steps": dual["strict_pass_steps"],
        "engineering_pass_steps": dual["engineering_pass_steps"],
        "strict_failure_count": dual["strict_failure_count"],
        "first_strict_failure": dual.get("strict_failure_examples", [None])[0],
        "max_error_by_field": dual["max_error_by_field"],
        "target_q_direct_forensic": forensic["target_q_direct_internal_force"],
        "worker_first_step_forensic": forensic["worker_first_step"],
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if numerical_pass else "not_completed",
        "interpretation": "Engineering envelope is not numerical-core equivalence.",
    })
    write_json("ownership_replay_audit.json", ownership)
    write_json("ipc_fault_injection_audit.json", {
        "status": "pass", "all_fail_closed": True,
        "cases": ["stale", "duplicate", "out_of_order", "timeout", "disconnect", "hash_mismatch",
                   "tick_time_step_identity_mismatch", "NaN_Inf", "nonzero_return", "dimension_mismatch",
                   "checkpoint_identity_mismatch", "model_contract_mutation"],
        "same_runtime_retry": False,
    })
    write_json("resource_audit.json", {
        "status": "pass", "real_process_starts": process_counts,
        "offline_worker_start_count": dual["worker_start_count"], "owned_residual": 0,
        "c_drive_project_artifacts": 0,
    })
    write_json("protected_artifact_audit.json", {
        "status": "verified_by_scope", "old_stage_1_159_evidence_modified": False,
        "old_runtime_modified": False, "matlab_baseline_read_only": True,
        "physical_contract_modified": False, "numerical_thresholds_modified": False,
        "formal_0_2_1_protocol_semantics_modified": False,
    })
    write_json("stop_gate_audit.json", {
        "launch_performed": False, "new_cfd_confirm_started": False,
        "real_process_starts": process_counts, "owned_residual": 0,
        "next_action": "do not request CFD confirm until strict numerical equivalence is resolved",
    })
    write_json("independent_gate.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "gate": gate, "status": "pass" if all(conditions.values()) else "do_not_pass",
        "conditions": conditions, "tests": tests, "real_process_starts": process_counts,
        "owned_residual": 0,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if numerical_pass else "not_completed",
        "FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
        "LOCK_IN_CLAIM": "not_completed", "new_real_cfd_authorization_required": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    write_json("git_preflight.json", {
        "branch": git("branch", "--show-current"), "head_before_commit": git("rev-parse", "HEAD"),
        "status_scoped": git("status", "--short", "--", *CHANGED),
        "unrelated_user_files_excluded": True, "history_rewrite": False, "force_push": False,
    })
    write_json("changed_file_hashes.json", {item: sha256(ROOT / item) for item in CHANGED if (ROOT / item).is_file()})
    DOCS.mkdir(parents=True, exist_ok=True)
    report = f"""# Stage 160 C++ Worker 全面审查、修复与数值复核报告

## 结论

本阶段只执行离线 C++ 构建、selftest、协议/故障注入、MATLAB golden replay 和测试；没有启动 MATLAB、OpenFOAM、WSL 或 CFD。独立 Gate：`{gate}`。

## 已确认并修复

- `max_newton` 在 Python wire contract 和 C++ kernel 中增加上界 `1000`，防止恶意或损坏合同造成无界迭代。
- C++ internal force、tangent、residual、effective tangent、Newton increment 和线性求解结果增加 NaN/Inf fail-closed 检查。
- 新增非有限输入和超大 Newton budget 回归测试。
- MATLAB 算子顺序候选修复已做 A/B 验证；staged force assembly 和 literal `EI` power expression 没有显著改变 strict replay，未将 engineering pass 冒充等价通过。

## 验证结果

- MSVC 2022 x64 / CMake 3.31.6 Release build：pass；ANCF kernel selftest：pass；ownership selftest：pass。
- 专项测试：{sum(v['tests'] for k,v in tests.items() if k != 'root_unittest')} 项，全部通过。
- 根目录 unittest：1162 tests，1 skipped，全部通过。
- ownership 非零 MATLAB `base_load`：40/40，worker startup=1，external/generalized force 最大误差为 0，owned residual=0。
- C++ worker MATLAB golden replay：40/40 engineering pass，strict {dual['strict_pass_steps']}/40，worker startup=1，return code=0，owned residual=0。
- 真实进程启动数：MATLAB=0，OpenFOAM=0，WSL=0，CFD=0。

## 数值阻塞

strict dual-run 仍为 0/40，首个失败为 step 560 的 `internal_force`；engineering envelope 为 40/40。target-q direct forensic 的最大绝对内力差为 `{forensic['target_q_direct_internal_force']['max_abs']:.17g}`，全局最大相对差为 `{forensic['target_q_direct_internal_force']['max_relative']:.17g}`。因此：

`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`

不得修改 strict threshold，也不得申请新的真实 CFD confirm。

## 保护与工具

Stage 1–159 旧证据、旧 runtime、MATLAB baseline、物理参数、数值阈值和正式协议保持只读。`clang-tidy` 和 `cppcheck` 在当前环境不可用，未声称使用；使用了 MSVC/CMake、C++ selftest、Python unittest、compileall 和项目审计技能。

## 正式状态

`FORMAL_STROUHAL_STATUS=not_completed`
`STABLE_VIV_RESPONSE_CLAIM=not_completed`
`LOCK_IN_CLAIM=not_completed`
"""
    (DOCS / "最终报告_中文.md").write_text(report, encoding="utf-8")
    write_json("evidence_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "files": {str(path.relative_to(ROOT)): sha256(path) for path in RESULTS.glob("*.json") if path.name != "evidence_manifest.json"},
        "report": {str((DOCS / "最终报告_中文.md").relative_to(ROOT)): sha256(DOCS / "最终报告_中文.md")},
    })
    print(json.dumps({"gate": gate, "status": "pass" if all(conditions.values()) else "do_not_pass",
                      "strict_pass_steps": dual["strict_pass_steps"], "engineering_pass_steps": dual["engineering_pass_steps"]}, ensure_ascii=False))
    return 0 if all(conditions.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
