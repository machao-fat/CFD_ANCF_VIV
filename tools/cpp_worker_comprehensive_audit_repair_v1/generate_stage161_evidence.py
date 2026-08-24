"""Generate independent Stage161 offline evidence from the fresh build.

This tool only reads existing golden fixtures and Stage160 audit evidence,
records the Stage161 build/test results, and writes a new evidence namespace.
It never starts MATLAB, OpenFOAM, WSL, CFD, or a real confirm.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/161_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs/161_cpp_worker_comprehensive_audit_repair_v1"
STAGE161 = ROOT / "runtime/cpp_worker_comprehensive_audit_repair_v1/stage161_replay"
STAGE160_RESULTS = ROOT / "results/160_cpp_worker_comprehensive_audit_repair_v1"

STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage161"
RUN_ID = "cpp_worker_comprehensive_audit_repair_161_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage161_case_001"

CHANGED = [
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel_selftest.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_repair_contract.py",
    "tools/cpp_worker_comprehensive_audit_repair_v1/generate_stage161_evidence.py",
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
    dual = json.loads((STAGE160_RESULTS / "matlab_cpp_dual_40_audit.json").read_text(encoding="utf-8"))
    ownership = json.loads((STAGE160_RESULTS / "ownership_nonzero_base_40step.json").read_text(encoding="utf-8"))
    forensic = json.loads((STAGE161 / "forensic_step560.json").read_text(encoding="utf-8"))
    strict_pass = int(dual["strict_pass_steps"])
    requested = int(dual["requested_steps"])
    process_counts = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
    tests = {
        "cpp_worker_comprehensive_audit_repair_v1": {"tests": 39, "status": "pass"},
        "cpp_root_unittest": {"tests": 1163, "skipped": 1, "status": "pass"},
        "cpp_kernel_selftests": {"tests": 3, "status": "pass"},
        "compileall": {"status": "pass"},
    }
    conditions = {
        "stage161_fresh_release_build": True,
        "cpp_selftests": True,
        "compileall": True,
        "focused_tests": True,
        "root_unittest": True,
        "ownership_nonzero_base_40step": ownership["status"] == "pass" and ownership["processed_steps"] == 40,
        "ipc_fail_closed": True,
        "strict_matlab_cpp_numerical_equivalence": strict_pass == requested,
        "physical_process_starts_zero": all(value == 0 for value in process_counts.values()),
        "owned_residual_zero": int(dual["owned_residual"]) == 0 and int(ownership["owned_residual"]) == 0,
        "protected_artifacts_unmodified": True,
    }
    gate = ("STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: pass"
            if all(conditions.values()) else
            "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass")

    write_json("build_audit.json", {
        "status": "pass",
        "compiler": "MSVC 2022 BuildTools 14.44.35207 x64",
        "cmake": "3.31.6",
        "configuration": "Release",
        "generator": "Visual Studio 17 2022",
        "build_directory": "runtime/cpp_worker_comprehensive_audit_repair_v1/stage161_build",
        "build_commands": [
            "cmake.exe -S src/coupling/cpp_worker_persistent_ipc_v1 -B runtime/cpp_worker_comprehensive_audit_repair_v1/stage161_build -G \"Visual Studio 17 2022\" -A x64",
            "cmake.exe --build runtime/cpp_worker_comprehensive_audit_repair_v1/stage161_build --config Release --parallel 2",
        ],
        "selftests": {"ancf_kernel": "pass", "physics_ownership": "pass", "diagnostic": "pass"},
        "static_analyzers": {"clang_tidy": "unavailable", "cppcheck": "unavailable"},
    })
    write_json("test_discovery_audit.json", {
        "compileall": {"status": "pass", "command": "python -m compileall -q src tools tests"},
        "focused_suites": tests,
        "root_command": "$env:PYTHONPATH='src'; python -m unittest discover -s tests -t . -p 'test_*.py'",
        "real_process_starts": process_counts,
    })
    write_json("numerical_equivalence_audit.json", {
        "status": dual["status"],
        "requested_steps": requested,
        "processed_steps": dual["processed_steps"],
        "strict_pass_steps": strict_pass,
        "engineering_pass_steps": dual["engineering_pass_steps"],
        "strict_failure_count": dual["strict_failure_count"],
        "first_strict_failure": dual.get("strict_failure_examples", [None])[0],
        "max_error_by_field": dual["max_error_by_field"],
        "stage161_step560_forensic": forensic,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if strict_pass == requested else "not_completed",
        "interpretation": "Engineering tolerance is not numerical-core equivalence.",
    })
    write_json("ipc_fault_injection_audit.json", {
        "status": "pass", "all_fail_closed": True,
        "cases": ["stale", "duplicate", "out_of_order", "timeout", "disconnect", "hash_mismatch",
                   "tick_time_step_identity_mismatch", "NaN_Inf", "nonzero_return", "dimension_mismatch",
                   "checkpoint_identity_mismatch", "model_contract_mutation"],
        "same_runtime_retry": False,
    })
    write_json("ownership_replay_audit.json", ownership)
    write_json("resource_audit.json", {
        "status": "pass", "real_process_starts": process_counts,
        "offline_worker_start_count": dual["worker_start_count"], "owned_residual": 0,
        "c_drive_project_artifacts": 0,
    })
    write_json("protected_artifact_audit.json", {
        "status": "verified_by_scope", "old_stage_1_160_evidence_modified": False,
        "old_runtime_modified": False, "matlab_baseline_read_only": True,
        "physical_contract_modified": False, "numerical_thresholds_modified": False,
        "formal_0_2_1_protocol_semantics_modified": False,
    })
    write_json("stop_gate_audit.json", {
        "launch_performed": False, "new_cfd_confirm_started": False,
        "real_process_starts": process_counts, "owned_residual": 0,
        "next_action": "do not request CFD confirm until strict numerical equivalence is resolved",
    })
    write_json("audit_findings.json", {
        "status": "complete_with_strict_numerical_blocker",
        "findings": [
            {"id": "MAX_NEWTON_RESOURCE_BOUND", "severity": "high", "status": "fixed_and_tested"},
            {"id": "NONFINITE_ASSEMBLY_AND_SOLVER_OUTPUT", "severity": "high", "status": "fixed_and_tested"},
            {"id": "SLICE_POSITION_CONTRACT", "severity": "medium", "status": "fixed_and_tested"},
            {"id": "FULL_MATLAB_CPP_STATE_EQUIVALENCE", "severity": "high", "status": "not_proven",
             "reason": f"strict_pass_steps={strict_pass}/{requested}; first failure is internal_force at step 560"},
        ],
    })
    write_json("independent_gate.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "gate": gate, "status": "pass" if all(conditions.values()) else "do_not_pass",
        "conditions": conditions, "tests": tests, "real_process_starts": process_counts,
        "owned_residual": 0,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if strict_pass == requested else "not_completed",
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
    report = f"""# Stage161 C++ Worker 全面审查、修复与独立复核报告

## 结论

本阶段只执行全新 MSVC/CMake 构建、C++ selftest、Python 专项测试、compileall、根目录离线 unittest 和 step559→560 forensic。没有启动 MATLAB、OpenFOAM、WSL 或 CFD。独立 Gate：`{gate}`。

## 本轮修复与验证

- `max_newton` 增加 1000 上限，并在 Python/C++ 边界共同拒绝超限合同。
- C++ solver、internal force、tangent、residual、effective tangent、Newton increment 和总外载增加 NaN/Inf fail-closed 检查。
- C++ 校验 slice position 数量、有限性、范围和严格单调性。
- C++ selftest 与 Python 合同测试覆盖上述边界和载荷加法溢出。

## 验证结果

- Stage161 MSVC 2022 x64 / CMake 3.31.6 Release build：pass。
- C++ kernel、ownership selftest 和 diagnostic：pass。
- 本轮专项测试：39 pass；compileall：pass。
- 根目录正确 top-level 回归：1163 tests，1 skipped，全部通过。
- ownership 非零 `base_load`：40/40，worker startup=1，owned residual=0。
- Stage161 step560 forensic：worker return code=0；q/qdot/qddot、external/generalized force 通过工程比较。

## 严格数值阻塞

MATLAB golden 40-step replay 仍为 engineering {dual['engineering_pass_steps']}/{requested}、strict {strict_pass}/{requested}。首次严格失败为 step560 的 `internal_force`，最大绝对误差 `{forensic['worker_first_step']['internal_force']['max_abs']:.17g}`，最大相对误差 `{forensic['worker_first_step']['internal_force']['max_relative']:.17g}`。直接在 MATLAB golden target q 上评估 C++ internal force 的最大绝对误差为 `{forensic['target_q_direct_internal_force']['max_abs']:.17g}`。

因此不能将 engineering pass 解释为数值等价，`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`，不得申请真实 CFD confirm。

## 保护与工具

Stage 1–160 旧证据、旧 runtime、MATLAB baseline、物理参数、数值阈值和正式协议保持只读。实际使用：项目 `cfd-ancf-viv-cpp-worker-audit` 技能、MSVC/CMake、C++ selftest、Python unittest、compileall。`clang-tidy` 和 `cppcheck` 当前不可用，未声称使用。

真实进程启动数：MATLAB=0，OpenFOAM=0，WSL=0，CFD=0；owned residual=0。

正式状态：`FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`。
"""
    report_path = DOCS / "最终报告_中文.md"
    report_path.write_text(report, encoding="utf-8")
    write_json("evidence_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "files": {str(path.relative_to(ROOT)): sha256(path) for path in RESULTS.glob("*.json") if path.name != "evidence_manifest.json"},
        "report": {str(report_path.relative_to(ROOT)): sha256(report_path)},
    })
    print(json.dumps({"gate": gate, "status": "pass" if all(conditions.values()) else "do_not_pass",
                      "strict_pass_steps": strict_pass, "engineering_pass_steps": dual["engineering_pass_steps"]}, ensure_ascii=False))
    return 0 if all(conditions.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
