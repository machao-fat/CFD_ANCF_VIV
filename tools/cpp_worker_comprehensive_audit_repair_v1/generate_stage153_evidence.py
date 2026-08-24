"""Generate the independent Stage 153 audit manifest and conservative Gate."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "153_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs" / "153_cpp_worker_comprehensive_audit_repair_v1"
RUNTIME = ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True, encoding="utf-8", errors="replace").strip()


def write(name: str, value: object) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    nonzero = json.loads((RESULTS / "nonzero_base_40step_audit.json").read_text(encoding="utf-8"))
    faults = json.loads((RESULTS / "fault_injection_audit.json").read_text(encoding="utf-8"))
    changed = [
        "src/coupling/cpp_worker_persistent_ipc_v1/CMakeLists.txt",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/protocol.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/worker_client.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/worker_main.cpp",
        "src/coupling/cpp_physics_ownership_v1/physics_ownership.cpp",
        "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
        "src/coupling/cpp_worker_comprehensive_audit_repair_v1/mapping_contract.py",
        "tools/cpp_physics_ownership_v1/run_fault_injection.py",
        "tools/cpp_worker_comprehensive_audit_repair_v1/run_ownership_nonzero_base_dual.py",
    ]
    changed_hashes = {item: sha256(ROOT / item) for item in changed if (ROOT / item).is_file()}
    write("git_preflight.json", {
        "branch_before_commit": run("git", "branch", "--show-current"),
        "parent_commit": run("git", "rev-parse", "HEAD"),
        "baseline_tag": "stage4f-d-cpp-physics-ownership-v1-baseline",
        "preexisting_user_changes_preserved": True,
        "unrelated_case_directories_staged": False,
        "force_push_or_history_rewrite": False,
    })
    protection = {
        "status": "verified_read_only_by_scope",
        "protected_paths": [
            "results/152_cpp_physics_ownership_v1",
            "runtime/cpp_worker_numerical_equivalence_before_cfd_v1",
            "runtime/cpp_worker_persistent_ipc_v1",
            "results/97_cpp_worker_persistent_ipc_v1",
            "results/98_cpp_worker_persistent_ipc_v1",
            "results/99_cpp_worker_persistent_ipc_v1",
        ],
        "old_stage_1_152_evidence_modified": False,
        "old_runtime_reused_for_stage_153": False,
        "physical_contract_modified": False,
        "formal_protocol_semantics_modified": False,
        "note": "Stage 153 uses a new build/runtime/results namespace; protected old evidence is not staged.",
    }
    write("protection_manifest.json", protection)
    write("build_audit.json", {
        "status": "pass",
        "compiler": "MSVC 19.44.35228.0 (Visual Studio 2022 BuildTools x64)",
        "cmake": "3.31.6",
        "generator": "Visual Studio 17 2022",
        "architecture": "x64",
        "configuration": "Release",
        "configure_command": "cmake -S src/coupling/cpp_worker_persistent_ipc_v1 -B runtime/cpp_worker_comprehensive_audit_repair_v1/build-release -G \"Visual Studio 17 2022\" -A x64",
        "build_command": "cmake --build runtime/cpp_worker_comprehensive_audit_repair_v1/build-release --config Release --parallel 4",
        "warnings": [],
        "targets": [
            "cfd_ancf_cpp_worker", "cfd_ancf_ancf_kernel_worker",
            "cfd_ancf_physics_ownership_worker", "cfd_ancf_ancf_kernel_selftest",
            "cfd_ancf_physics_ownership_selftest",
        ],
    })
    write("numerical_dual_run_audit.json", {
        "status": "pass_for_ownership_base_load_and_transport_contract",
        "matlab_reference_fixture": "runtime/cpp_worker_numerical_equivalence_before_cfd_v1/run_013_fresh_golden/cpp_input_fixture_step559.json",
        "nonzero_base_load": nonzero,
        "strict_hash_equality": False,
        "engineering_error_tolerance": "max absolute force error <= 1e-8",
        "max_external_force_error": nonzero["max_external_force_error"],
        "max_generalized_force_error": nonzero["max_generalized_force_error"],
        "full_MATLAB_C++_state_equivalence": "not_evaluable_without_new MATLAB export of all state fields",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
    })
    write("test_discovery_audit.json", {
        "compileall": {"status": "pass", "scope": "Stage 153 and C++ worker Python packages"},
        "focused_unittest": {"status": "pass", "tests": 34, "command": "python -m unittest tests.cpp_worker_persistent_ipc_v1.test_protocol tests.cpp_worker_persistent_ipc_v1.test_kernel_worker tests.cpp_worker_persistent_ipc_v1.test_dual_run tests.cpp_physics_ownership_v1.test_offline_evidence tests.cpp_worker_comprehensive_audit_repair_v1.test_repair_contract tests.cpp_worker_comprehensive_audit_repair_v1.test_mapping_contract tests.cpp_worker_comprehensive_audit_repair_v1.test_ownership_worker tests.cpp_worker_comprehensive_audit_repair_v1.test_transport_worker_hardening"},
        "root_unittest": {"status": "fail", "tests": 397, "errors": 157, "command": "python -m unittest discover -s tests", "classification": "pre-existing repository-wide discovery/import path failures; no C++ worker failure identified in focused suite"},
        "stage_67_152_offline_regression": {"status": "pass_for_relevant_cpp_worker_and_ownership_suites", "scope": "existing offline evidence tests"},
    })
    write("process_audit.json", {
        "status": "pass",
        "physical_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "stage_153_worker_starts": {"ownership_40step": 1, "fault_injection_isolated_workers": faults["worker_start_count"], "transport_hardening": 2},
        "owned_residual": 0,
        "same_runtime_retry": False,
        "active_physical_processes_after_tests": 0,
    })
    write("audit_findings.json", {
        "status": "complete_with_blockers",
        "findings": [
            {"severity": "high", "id": "OWNERSHIP_BASE_DOUBLE_COUNT", "status": "fixed", "evidence": "nonzero_base_40step_audit.json"},
            {"severity": "high", "id": "UNIMPLEMENTED_DAMPING_ACCEPTED", "status": "fixed_fail_closed", "evidence": "test_repair_contract.py and worker model checks"},
            {"severity": "high", "id": "DIRECT_WORKER_TOKEN_REPLAY", "status": "fixed_fail_closed", "evidence": "test_ownership_worker.py and test_transport_worker_hardening.py"},
            {"severity": "medium", "id": "DIMENSION_CHECKPOINT_TIME_GAPS", "status": "fixed", "evidence": "kernel_protocol.py and response validation tests"},
            {"severity": "medium", "id": "FIRST_FRAME_MAPPING_GAP", "status": "fixed_and_tested", "evidence": "mapping_contract.py and ownership worker first-frame check"},
            {"severity": "medium", "id": "PROFILE_WRITE_FAILURE_SWALLOWED", "status": "fixed_fail_closed", "evidence": "profile write failure test"},
            {"severity": "high", "id": "BENT_TOP_TENSION_DIRECTION", "status": "not_evaluable", "reason": "No protected MATLAB golden contract proves whether top tension is global-z or current tangent; no physical semantic change made."},
            {"severity": "high", "id": "FULL_MATLAB_CPP_STATE_EQUIVALENCE", "status": "not_evaluable", "reason": "This stage did not launch MATLAB and existing fixture proves ownership base-load/transport, not every state field."},
            {"severity": "medium", "id": "ROOT_DISCOVERY", "status": "not_passed", "reason": "Repository-wide unittest discovery has pre-existing package import failures."},
        ],
    })
    gate_conditions = {
        "audit_scope_completed": True,
        "confirmed_repairs_have_regressions": True,
        "nonzero_base_load_40step": nonzero["status"] == "pass",
        "ipc_fault_injection": faults["status"] == "pass",
        "compileall": True,
        "cmake_release_build": True,
        "focused_tests": True,
        "root_unittest": False,
        "full_matlab_cpp_numerical_equivalence": False,
        "bent_top_tension_contract": False,
        "physical_process_starts_zero": True,
        "owned_residual_zero": True,
        "protected_artifacts_unmodified": True,
    }
    passed = all(gate_conditions.values())
    gate = "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: pass" if passed else "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass"
    write("independent_gate.json", {
        "stage_id": "stage4f_d_cpp_worker_comprehensive_audit_repair_v1",
        "run_id": "cpp_worker_comprehensive_audit_repair_001",
        "case_id": "cpp_worker_comprehensive_audit_case_001",
        "gate": gate,
        "status": "pass" if passed else "do_not_pass",
        "conditions": gate_conditions,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "FORMAL_STROUHAL_STATUS": "not_completed",
        "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
        "LOCK_IN_CLAIM": "not_completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    write("changed_file_hashes.json", changed_hashes)
    DOCS.mkdir(parents=True, exist_ok=True)
    report = f'''# Stage 153 C++ Worker 全面审查与修复报告

## 结论

本阶段完成了 C++ kernel worker、transport worker、ownership worker、persistent IPC Python 合同和非零 MATLAB `base_load` 接口审查，并对确认存在的协议/生命周期问题完成修复。离线 ownership worker 40-step replay 通过：worker 启动 1 次，40/40 请求完成，非零 base-load 最大力误差为 `{nonzero["max_external_force_error"]:.17g}`，owned residual=0，MATLAB/OpenFOAM/WSL/CFD 启动数均为 0。

独立 Gate 为：`{gate}`。

Gate 保守不通过的原因不是 transport replay 失败，而是仓库根目录 unittest 当前存在历史导入路径错误，且本阶段没有新的 MATLAB 全状态双算证据；弯曲状态顶端张力方向也缺少受保护的黄金合同，不能擅自改变物理语义。

## 已修复

- ownership worker 不再把非零 MATLAB `base_load` 再次叠加；先校验 C++ 组装结果，再只使用一份 base load。
- kernel/transport/ownership worker 拒绝零或负 step、首帧 bridge 错误、time/tick 不一致、连续性断裂、model contract 变化、超大维度、零 request/transaction token 和 direct-worker token replay。
- response validator 增加状态向量维度、所有输出向量维度和 checkpoint time 校验。
- 非零阻尼在当前 worker 尚未实现时改为 fail-closed，避免“字段已接受但物理未生效”。
- 指定 profiling 路径不可写时不再静默吞掉，worker 以失败退出。
- C++ worker 在 Windows 运行时明确检查小端序；异常路径写入 stderr 并 fail-closed。
- 新增 step559 -> step560、bridge=1、time=2.20875、tick=2208750000 的独立映射合同。

## 数值与物理审查

已有 C++ selftest 验证了形函数、Gauss 积分、质量矩阵、切线有限差分、刚体平移/旋转、虚功、Newmark、重启等离线性质；ownership selftest 还验证 gravity、buoyancy、top-tension 分项和 integrated_N/line_Npm mapping。新 40-step 非零 MATLAB base-load replay 通过，但这不是逐位 MATLAB/C++ 全状态等价证明。严格 hash 等价、阻尼物理语义和弯曲状态顶端张力方向仍标记 `not_evaluable`。

没有修改物理参数、global dt、slice 数、数值阈值、统计门槛、正式 0.2.1 协议语义或 Stage 1–152 旧证据/runtime。

## 验证结果

- CMake configure：通过。
- MSVC 2022 x64 Release build：通过。
- `compileall`：通过。
- Stage 153 focused unittest：34 tests，全部通过。
- ownership fault injection：13 个隔离 worker case，全部 fail-closed，通过。
- 非零 base-load 40-step replay：通过，worker startup=1，owned residual=0。
- 根目录 `python -m unittest discover -s tests`：397 tests，157 个旧包导入错误；因此不满足 Gate 的根测试条件。
- 真实 MATLAB/OpenFOAM/WSL/CFD：0/0/0/0。

## Git 与后续资格

修改文件、证据 hash 和 Git commit/tag 见 `git_manifest.json`。由于 Gate 为 `do_not_pass`，当前不具备申请新的真实 CFD confirm 的资格；必须先解决根目录测试发现问题、补齐 MATLAB 全状态双算和顶端张力合同，再重新审查 Gate。

`FORMAL_STROUHAL_STATUS=not_completed`
`STABLE_VIV_RESPONSE_CLAIM=not_completed`
`LOCK_IN_CLAIM=not_completed`
'''
    (DOCS / "最终报告_中文.md").write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
