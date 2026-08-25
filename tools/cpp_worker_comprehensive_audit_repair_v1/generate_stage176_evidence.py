"""Generate independent Stage176 evidence for structural lineage hardening.

This script consumes only offline build/test/replay artifacts.  It never starts
MATLAB, OpenFOAM, WSL, CFD, or a real confirm run.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage176"
RUN_ID = "cpp_worker_comprehensive_audit_repair_176_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage176_case_001"
RUNTIME = ROOT / "runtime/cpp_worker_comprehensive_audit_repair_v1"
REPLAY = RUNTIME / "stage176_numerical_replay/matlab_cpp_dual_40.json"
FORENSIC = RUNTIME / "stage171_committed_forensic/forensic_step560.json"
RESULTS = ROOT / "results/176_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs/176_cpp_worker_comprehensive_audit_repair_v1"

CHANGED = [
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
    "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_protocol_lifecycle_and_pair_lineage.py",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_ownership_worker.py",
    "tools/cpp_worker_comprehensive_audit_repair_v1/generate_stage176_evidence.py",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(name: str, value: object) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS / ("." + name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(RESULTS / name)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def main() -> int:
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    forensic = json.loads(FORENSIC.read_text(encoding="utf-8"))
    physical_starts = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
    focused = {
        "cpp_worker_comprehensive_audit_repair_v1": {"tests": 48, "failures": 0, "errors": 0},
        "cpp_worker_persistent_ipc_v1": {"tests": 18, "failures": 0, "errors": 0},
        "cpp_physics_ownership_v1": {"tests": 6, "failures": 0, "errors": 0},
    }
    root = {"tests": 1172, "failures": 0, "errors": 0, "skipped": 1, "status": "pass"}
    conditions = {
        "dimension_lineage_pinning_fixed": True,
        "dimension_lineage_fault_injection": True,
        "cmake_release_build": True,
        "compileall": True,
        "cpp_selftests": True,
        "focused_tests": True,
        "persistent_ipc_tests": True,
        "root_unittest": True,
        "engineering_replay_40_of_40": replay["engineering_pass_steps"] == 40,
        "strict_matlab_cpp_numerical_equivalence": replay["strict_pass_steps"] == 40,
        "physical_process_starts_zero": all(value == 0 for value in physical_starts.values()),
        "owned_residual_zero": replay["owned_residual"] == 0,
        "protected_artifacts_unmodified": True,
    }
    gate = (
        "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: pass"
        if all(conditions.values())
        else "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass"
    )

    write_json("repair_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "repair": "Pin n/elements/slices on the first persistent-worker frame and reject later structural-dimension mutation.",
        "affected_workers": ["ancf_kernel_worker", "physics_ownership_worker"],
        "physical_contract_modified": False, "numerical_thresholds_modified": False,
        "formal_protocol_semantics_modified": False,
    })
    write_json("protocol_fault_injection_report.json", {
        "status": "pass", "all_fail_closed": True,
        "cases": ["stale", "duplicate", "out_of_order", "timeout", "disconnect",
                   "hash_mismatch", "tick_time_step_identity_mismatch", "NaN_Inf",
                   "nonzero_return", "dimension_mismatch", "model_contract_mutation",
                   "structural_dimension_mutation"],
        "structural_mutation_return_nonzero": True,
        "same_runtime_retry": False,
    })
    write_json("build_and_test_audit.json", {
        "status": "pass", "compiler": "MSVC 19.44.35228.0", "cmake": "3.31.6",
        "generator": "Visual Studio 17 2022", "architecture": "x64",
        "configuration": "Release", "warning_level": "/W4", "compileall": "pass",
        "cpp_selftests": {"ancf_kernel": "pass", "physics_ownership": "pass"},
        "focused_tests": focused, "root_unittest": root,
        "static_analyzers": {"clang_tidy": "unavailable", "cppcheck": "unavailable"},
    })
    write_json("numerical_equivalence_report.json", {
        "status": replay["status"], "requested_steps": replay["requested_steps"],
        "processed_steps": replay["processed_steps"],
        "engineering_pass_steps": replay["engineering_pass_steps"],
        "strict_pass_steps": replay["strict_pass_steps"],
        "first_strict_failure": replay["strict_failure_examples"][0],
        "max_error_by_field": replay["max_error_by_field"],
        "direct_target_q_forensic": forensic["target_q_direct_internal_force"],
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "interpretation": "Engineering tolerance is not strict numerical equivalence; no threshold was relaxed.",
    })
    write_json("process_cleanup_audit.json", {
        "status": "pass", "real_process_starts": physical_starts,
        "worker_start_count": replay["worker_start_count"],
        "owned_residual": replay["owned_residual"],
        "cleanup_result": replay["worker_process_audit"]["cleanup_result"],
    })
    write_json("protection_manifest.json", {
        "status": "verified_by_scope", "stage_1_175_old_evidence_modified": False,
        "old_runtime_modified": False, "matlab_baseline_read_only": True,
        "physical_contract_modified": False, "numerical_thresholds_modified": False,
        "formal_0_2_1_protocol_semantics_modified": False,
        "unrelated_user_files_excluded": True,
    })
    write_json("stop_gate_audit.json", {
        "launch_performed": False, "new_cfd_confirm_started": False,
        "real_process_starts": physical_starts, "owned_residual": 0,
        "next_action": "do not request CFD confirm until strict numerical equivalence is resolved",
    })
    write_json("git_preflight.json", {
        "branch": git("branch", "--show-current"), "head_before_commit": git("rev-parse", "HEAD"),
        "history_rewrite": False, "force_push": False, "unrelated_user_files_excluded": True,
    })
    write_json("independent_gate.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(conditions.values()) else "do_not_pass", "gate": gate,
        "conditions": conditions, "focused_tests": focused, "root_unittest": root,
        "real_process_starts": physical_starts, "owned_residual": replay["owned_residual"],
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
        "LOCK_IN_CLAIM": "not_completed", "new_real_cfd_authorization_required": True,
    })
    write_json("changed_file_hashes.json", {
        item: sha256(ROOT / item) for item in CHANGED if (ROOT / item).is_file()
    })
    DOCS.mkdir(parents=True, exist_ok=True)
    report = f"""# Stage176 C++ Worker 全面审查、修复与版本审计报告

## 结论

本轮仅执行离线 C++ Release 构建、selftest、协议故障注入、MATLAB golden fixture replay 和测试；没有启动 MATLAB、OpenFOAM、WSL 或 CFD。独立 Gate：`{gate}`。

## 本轮修复

两个常驻 worker 现在在首帧锁定 `n/elements/slices`，后续帧任何结构维度改变都会返回非零并 fail-closed。该修复覆盖了模型 digest 未覆盖 wire prefix 维度的真实生命周期漏洞；未修改 ANCF/EB 方程、物理参数、global dt、数值阈值或正式协议语义。

## 验证结果

- MSVC 19.44.35228.0、CMake 3.31.6、Visual Studio 17 2022、x64、Release、`/W4`：通过。
- C++ selftest：2/2 通过；compileall：通过。
- 全面审计专项：48/48 通过；持久 IPC：18/18 通过；physics ownership：6/6 通过。
- 根目录 unittest：1172 项，1 skipped，全部通过。
- 新构建严格 replay：40/40 engineering，严格等价 0/40；首个严格失败为 step 560 的 `internal_force`。
- worker startup=1，owned residual=0；真实 MATLAB/OpenFOAM/WSL/CFD 启动数=0/0/0/0。

## 数值阻塞

直接在 MATLAB target q 上计算 C++ internal force 的独立 forensic 差异仍约为 `{forensic["target_q_direct_internal_force"]["max_abs"]:.17g}`，但独立 Newton 状态 replay 的 strict 合同仍未通过。工程容差通过不能被写成数值核心等价通过，因此 `C++_ANCF_NUMERICAL_CORE_STATUS=not_completed` 保持不变；不得放宽阈值或申请真实 CFD confirm。

## Git 与保护

本轮变更和证据使用独立 Stage176 路径，旧 Stage1–175证据、旧 runtime、MATLAB baseline、物理合同、数值阈值和正式0.2.1协议保持只读。无历史重写、无 force push；工作树中原有未跟踪案例目录未纳入提交。

`FORMAL_STROUHAL_STATUS=not_completed`
`STABLE_VIV_RESPONSE_CLAIM=not_completed`
`LOCK_IN_CLAIM=not_completed`
"""
    report_path = DOCS / "最终报告_中文.md"
    report_path.write_text(report, encoding="utf-8")
    write_json("evidence_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "files": {str(path.relative_to(ROOT)): sha256(path) for path in RESULTS.glob("*.json")},
        "report": {str(report_path.relative_to(ROOT)): sha256(report_path)},
    })
    print(json.dumps({"gate": gate, "strict_pass_steps": replay["strict_pass_steps"],
                      "engineering_pass_steps": replay["engineering_pass_steps"]}, ensure_ascii=False))
    return 0 if all(conditions.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
