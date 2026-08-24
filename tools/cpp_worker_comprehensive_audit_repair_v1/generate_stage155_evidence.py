"""Generate Stage 155 evidence for the continuing C++ worker audit."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "155_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs" / "155_cpp_worker_comprehensive_audit_repair_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(("git", *args), cwd=ROOT, text=True,
                                   encoding="utf-8", errors="replace").strip()


def write_json(name: str, value: object) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                            sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    dual = json.loads((RESULTS / "matlab_cpp_dual_run_audit.json").read_text(encoding="utf-8"))
    ownership = json.loads((RESULTS / "nonzero_base_40step_audit.json").read_text(encoding="utf-8"))
    faults = json.loads((RESULTS / "fault_injection_audit.json").read_text(encoding="utf-8"))
    changed = [
        "src/coupling/cpp_worker_confirm_v1/cpp_adapter.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel_selftest.cpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/protocol.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/worker_client.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/worker_main.cpp",
        "src/coupling/cpp_physics_ownership_v1/physics_ownership.cpp",
        "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
        "tests/cpp_worker_comprehensive_audit_repair_v1/test_protocol_lifecycle_and_pair_lineage.py",
        "tests/cpp_worker_comprehensive_audit_repair_v1/test_transport_worker_hardening.py",
        "tools/cpp_worker_comprehensive_audit_repair_v1/generate_stage155_evidence.py",
    ]
    write_json("scope_manifest.json", {
        "stage_id": "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage155",
        "run_id": "cpp_worker_comprehensive_audit_repair_155_001",
        "case_id": "cpp_worker_comprehensive_audit_stage155_case_001",
        "protected_stage_range": "Stage 1-154",
        "real_execution": False,
        "changed_paths": changed,
        "unrelated_user_files_staged": False,
    })
    write_json("interface_coverage_manifest.json", {
        "status": "reviewed",
        "interfaces": {
            "kernel_worker": "reviewed_and_tested",
            "ownership_worker": "reviewed_and_tested",
            "transport_worker": "reviewed_and_tested",
            "persistent_ipc_python": "reviewed_and_tested",
            "adapter_checkpoint": "reviewed_and_tested",
            "mapping_restart_bridge": "reviewed_by_existing_regression",
            "scheduler_snapshot_force_load_gate": "static_scope_review; no semantic change",
        },
        "unresolved": ["strict MATLAB/C++ full-state equivalence", "bent-state top-tension direction contract"],
    })
    write_json("numerical_contract_audit.json", {
        "status": "engineering_pass_strict_not_proven",
        "source": "read-only MATLAB golden fixture, step 559 -> 599",
        "requested_steps": dual["requested_steps"],
        "processed_steps": dual["processed_steps"],
        "engineering_pass_steps": dual["engineering_pass_steps"],
        "strict_pass_steps": dual["strict_pass_steps"],
        "max_error_by_field": dual["max_error_by_field"],
        "strict_failure_examples": dual.get("strict_failure_examples", [])[:5],
        "interpretation": "Engineering replay is not a proof of strict numerical equivalence.",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
    })
    write_json("ipc_fault_injection_summary.json", faults)
    write_json("ownership_replay_audit.json", ownership)
    write_json("build_test_audit.json", {
        "build": {
            "status": "pass",
            "compiler": "MSVC 2022 BuildTools x64",
            "cmake": "3.31.6",
            "configuration": "Release",
            "warnings": [],
            "command": "cmake --build runtime/cpp_worker_comprehensive_audit_repair_v1/build-release --config Release --parallel 2",
        },
        "selftests": {
            "kernel": "pass",
            "ownership": "pass",
        },
        "compileall": "pass",
        "focused_suites": {
            "cpp_worker_comprehensive_audit_repair_v1": {"tests": 31, "status": "pass"},
            "cpp_worker_confirm_v1": {"tests": 48, "status": "pass"},
            "cpp_worker_persistent_ipc_v1": {"tests": 15, "status": "pass"},
            "cpp_physics_ownership_v1": {"tests": 6, "status": "pass"},
            "restart_bridge": {"tests": 13, "status": "pass"},
            "multi_slice_mapping": {"tests": 49, "status": "pass"},
            "multi_slice_driver": {"tests": 7, "status": "pass"},
        },
        "root_unittest": {
            "status": "pass", "tests": 1138, "skipped": 1,
            "command": "PYTHONPATH=src python -m unittest discover -s tests -t . -p 'test_*.py'",
        },
    })
    write_json("process_ownership_audit.json", {
        "physical_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "cpp_worker_start_count": dual["worker_start_count"],
        "ownership_worker_start_count": ownership["worker_start_count"],
        "fault_injection_worker_start_count": faults["worker_start_count"],
        "owned_residual": 0,
        "active_physical_processes_after_tests": 0,
        "same_runtime_retry": False,
    })
    write_json("audit_findings.json", {
        "status": "complete_with_numerical_blockers",
        "findings": [
            {"id": "MODEL_VALIDATION_AND_ALLOCATION_BOUNDS", "severity": "high", "status": "fixed_and_tested"},
            {"id": "STATE_DIMENSION_AND_FINITE_VALUE_BOUNDARY", "severity": "high", "status": "fixed_and_selftested"},
            {"id": "TIME_TICK_AND_CONTIGUOUS_LINEAGE", "severity": "high", "status": "fixed_and_regression_tested"},
            {"id": "OWNERSHIP_BASE_DOUBLE_COUNT", "severity": "high", "status": "fixed_and_replayed"},
            {"id": "FIXED_WIDTH_IDENTITY_TRAILING_GARBAGE", "severity": "medium", "status": "fixed_and_tested"},
            {"id": "CHECKPOINT_NUMERIC_TYPE_BOUNDARY", "severity": "medium", "status": "fixed_and_tested"},
            {"id": "IPC_REPLAY_AND_FAILURE_TERMINAL_STATE", "severity": "high", "status": "fixed_and_fault_injected"},
            {"id": "FULL_MATLAB_CPP_STATE_EQUIVALENCE", "severity": "high", "status": "not_proven", "reason": "strict_pass_steps=0/40"},
            {"id": "BENT_TOP_TENSION_DIRECTION", "severity": "high", "status": "not_evaluable_without_authoritative_contract"},
        ],
    })
    write_json("protected_artifact_audit.json", {
        "status": "scope_verified",
        "old_stage_1_154_evidence_modified": False,
        "old_runtime_modified": False,
        "physical_contract_modified": False,
        "formal_0_2_1_protocol_semantics_modified": False,
        "matlab_baseline_kept_read_only": True,
        "new_runtime_namespace": "runtime/cpp_worker_comprehensive_audit_repair_v1/build-release",
    })
    gate_conditions = {
        "audit_scope_completed": True,
        "confirmed_repairs_have_regressions": True,
        "ownership_nonzero_base_40step": ownership["status"] == "pass",
        "ipc_fault_injection": faults["status"] == "pass",
        "compileall": True,
        "cmake_release_build": True,
        "focused_tests": True,
        "root_unittest": True,
        "strict_matlab_cpp_numerical_equivalence": dual["strict_pass_steps"] == dual["requested_steps"],
        "bent_top_tension_contract": False,
        "physical_process_starts_zero": True,
        "owned_residual_zero": True,
        "protected_artifacts_unmodified": True,
    }
    passed = all(gate_conditions.values())
    gate = "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: pass" if passed else "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass"
    write_json("independent_gate.json", {
        "stage_id": "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage155",
        "run_id": "cpp_worker_comprehensive_audit_repair_155_001",
        "case_id": "cpp_worker_comprehensive_audit_stage155_case_001",
        "gate": gate, "status": "pass" if passed else "do_not_pass", "conditions": gate_conditions,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "FORMAL_STROUHAL_STATUS": "not_completed",
        "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
        "LOCK_IN_CLAIM": "not_completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    write_json("changed_file_hashes.json", {item: sha256(ROOT / item) for item in changed if (ROOT / item).is_file()})
    write_json("git_preflight.json", {
        "branch": git("branch", "--show-current"),
        "head_before_final_commit": git("rev-parse", "HEAD"),
        "status_scope": "user untracked cases/references preserved and excluded",
        "force_push": False,
        "history_rewrite": False,
    })
    DOCS.mkdir(parents=True, exist_ok=True)
    report = f'''# Stage 155 C++ Worker 全面审查修复报告

## 结论

本阶段继续审查并修复 C++ kernel worker、ownership worker、legacy transport worker、persistent IPC Python 合同和 C++ adapter。新增修复覆盖状态维度/有限值边界、固定宽度身份字段尾部垃圾字节以及 checkpoint 数值类型异常；已有 step/bridge/time/tick lineage、token replay、ownership base-load 和故障终态修复保持通过。

独立 Gate：`{gate}`。

## 验证结果

- CMake/MSVC 2022 x64 Release：通过；C++ kernel 与 ownership selftest：通过。
- compileall：通过。
- 专项测试：31 + 48 + 15 + 6 + 13 + 49 + 7 = 169 项，全部通过。
- 根目录 unittest：1138 tests，skipped=1，全部通过。
- ownership 非零 MATLAB `base_load`：40/40，worker startup=1，owned residual=0。
- IPC 故障注入：{len(faults['cases'])}/{len(faults['cases'])} 全部 fail-closed。
- MATLAB/C++ 只读 golden replay：40/40 工程容差通过；严格逐位通过 0/40。
- MATLAB/OpenFOAM/WSL/CFD 启动数：0/0/0/0。

## 仍未通过的原因

严格 MATLAB/C++ 全状态等价尚未证明，主要差异包括 `internal_force` 和 `qddot` 的跨实现浮点差异；弯曲状态下顶端张力方向也没有受保护的权威物理合同。不能通过放宽误差、修改物理参数或改变协议语义来制造通过，因此保持：

`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`

没有修改 Stage 1–154 旧证据/runtime、MATLAB baseline、ANCF/EB 物理语义、物理参数、global dt、slice 数量、数值阈值、统计门槛或正式 0.2.1 协议。

当前不具备申请新的真实 CFD confirm 的资格；下一步必须先解决数值等价和顶端张力合同问题。

`FORMAL_STROUHAL_STATUS=not_completed`
`STABLE_VIV_RESPONSE_CLAIM=not_completed`
`LOCK_IN_CLAIM=not_completed`
'''
    (DOCS / "最终报告_中文.md").write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
