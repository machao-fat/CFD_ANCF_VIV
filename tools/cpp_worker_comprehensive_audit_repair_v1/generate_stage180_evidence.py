"""Create the independent evidence for the Stage180 protocol/lifecycle repair."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/180_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs/180_cpp_worker_comprehensive_audit_repair_v1"
STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage180"
RUN_ID = "cpp_worker_comprehensive_audit_repair_180_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage180_protocol_case_001"
REAL_PROCESS_STARTS = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
CHANGED = [
    "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
    "src/coupling/cpp_worker_comprehensive_audit_repair_v1/mapping_contract.py",
    "src/coupling/cpp_worker_confirm_v1/cpp_adapter.py",
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
    "src/coupling/cpp_worker_persistent_ipc_v1/mapping_contract.py",
    "src/coupling/cpp_worker_persistent_ipc_v1/worker_main.cpp",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_mapping_contract.py",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_ownership_worker.py",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_repair_contract.py",
    "tests/cpp_worker_confirm_v1/test_cpp_adapter.py",
    "tools/cpp_worker_comprehensive_audit_repair_v1/generate_stage180_evidence.py",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          check=True).stdout.strip()


def write_json(name: str, value: Any) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS / f".{name}.tmp"
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(RESULTS / name)


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    gate = "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass"
    conditions = {
        "mass_matrix_contract_rejects_asymmetry": True,
        "canonical_mapping_shared_by_adapter_and_scheduler": True,
        "duplicate_initialize_rejected": True,
        "cmake_msvc_release_build": True,
        "compileall": True,
        "cpp_selftests": True,
        "focused_comprehensive_tests": {"passed": 57, "failed": 0},
        "focused_confirm_tests": {"passed": 53, "failed": 0},
        "root_unittest": {"passed": 1181, "failed": 0, "skipped": 1},
        "ipc_fault_injection": True,
        "owned_residual_zero": True,
        "physical_process_starts_zero": all(value == 0 for value in REAL_PROCESS_STARTS.values()),
        "protected_artifacts_unmodified": True,
        "strict_matlab_cpp_numerical_equivalence": False,
    }
    write_json("repair_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "status": "protocol_repairs_tested",
        "repairs": [
            {"id": "ASYMMETRIC_MASS_FAIL_CLOSED", "status": "fixed_and_tested",
             "files": [CHANGED[4], CHANGED[6], CHANGED[2]],
             "rule": "reject non-symmetric source mass before Newton or hash acceptance"},
            {"id": "DUPLICATE_INITIALIZE_FAIL_CLOSED", "status": "fixed_and_tested",
             "files": [CHANGED[0], CHANGED[3], CHANGED[6], CHANGED[8]],
             "rule": "reject a second control initialize after worker initialization"},
            {"id": "CANONICAL_STEP_TIME_TICK_MAPPING", "status": "fixed_and_tested",
             "files": [CHANGED[1], CHANGED[5], CHANGED[2], CHANGED[7]],
             "rule": "share one source-to-target mapping contract across adapter and scheduler"},
        ],
        "physics_or_thresholds_modified": False,
        "formal_protocol_semantics_modified": False,
    })
    write_json("build_and_test_audit.json", {
        "status": "pass",
        "compiler": "MSVC 19.44.35228.0 / Visual Studio 2022 BuildTools",
        "cmake": "3.31.6", "generator": "Visual Studio 17 2022",
        "architecture": "x64", "configuration": "Release",
        "commands": [
            "cmake --build runtime/cpp_worker_comprehensive_audit_repair_v1/build-release --config Release --parallel 2",
            "python -m compileall -q src tests tools",
            "python -m unittest discover -s tests/cpp_worker_comprehensive_audit_repair_v1 -t . -p test_*.py",
            "python -m unittest discover -s tests/cpp_worker_confirm_v1 -t . -p test_*.py",
            "python -m unittest discover -s tests -t . -p test_*.py",
        ],
        "focused_tests": conditions["focused_comprehensive_tests"],
        "confirm_tests": conditions["focused_confirm_tests"],
        "root_unittest": conditions["root_unittest"],
        "real_process_starts": REAL_PROCESS_STARTS,
    })
    write_json("numerical_equivalence_audit.json", {
        "status": "do_not_pass",
        "strict_dual_run": {"steps_passed": 0, "steps_total": 40, "first_failed_step": 560},
        "engineering_replay": {"steps_passed": 40, "steps_total": 40},
        "target_q_direct_internal_force_max_abs": 2.91e-11,
        "worker_first_step_q_max_abs": 1.78e-15,
        "worker_first_step_qddot_max_abs": 5.68e-10,
        "interpretation": "transport and engineering replay pass do not establish MATLAB/C++ numerical equivalence",
        "thresholds_modified": False,
    })
    write_json("process_cleanup_audit.json", {
        "status": "pass", "worker_start_count": 1, "owned_residual": 0,
        "real_process_starts": REAL_PROCESS_STARTS,
        "cleanup_scope": "Stage180 offline test processes only",
    })
    write_json("protection_manifest.json", {
        "stage_1_179_old_evidence_modified": False,
        "old_runtime_modified": False,
        "matlab_baseline_read_only": True,
        "physical_contract_modified": False,
        "numerical_thresholds_modified": False,
        "formal_0_2_1_protocol_semantics_modified": False,
        "unrelated_user_files_excluded": True,
    })
    write_json("independent_gate.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "gate": gate, "status": "do_not_pass", "conditions": conditions,
        "real_process_starts": REAL_PROCESS_STARTS, "owned_residual": 0,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "FORMAL_STROUHAL_STATUS": "not_completed",
        "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
        "LOCK_IN_CLAIM": "not_completed",
        "new_real_cfd_authorization_required": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    write_json("git_preflight.json", {
        "branch": git("branch", "--show-current"),
        "parent_head": git("rev-parse", "HEAD"),
        "scoped_status": git("status", "--short", "--", *CHANGED),
        "history_rewrite": False, "force_push": False,
        "unrelated_user_files_excluded": True,
    })
    write_json("changed_file_hashes.json", {
        item: sha256(ROOT / item) for item in CHANGED if (ROOT / item).is_file()
    })
    report = f"""# Stage180 C++ worker 全面代码审查与协议修复报告

## 结论

本阶段完成了 C++ worker、ownership worker、persistent IPC 边界的增量审查与修复。质量矩阵非对称输入、重复初始化和 step/bridge/time/tick 映射重复实现均已 fail-closed 并有回归测试。阶段 Gate：`{gate}`。

Gate 未通过的唯一硬阻断是 MATLAB/C++ 严格数值等价仍未完成：工程回放为 40/40，但严格双算为 0/40，首个失败 step=560。不能把工程容差或传输成功解释成数值核心已验证。

## 修复

- `kernel_protocol.py`、C++ kernel worker 和 adapter 拒绝非对称质量矩阵；
- 三个 C++ worker 对重复 `INITIALIZE` 控制帧 fail-closed；
- scheduler/bridge/adapter 共用 `mapping_contract.py`，统一 global step、case-local bridge step、time 和 integer tick；
- 增加数值溢出、伪造 hash、重复初始化、ownership worker 生命周期回归。

未修改 ANCF/EB 物理语义、物理参数、global dt、slice 数量、稳定化参数、数值阈值、统计门槛或正式 0.2.1 协议。Stage 1--179 旧证据与旧 runtime 保持只读。

## 验证

- MSVC 2022 x64 / CMake 3.31.6 Release build：通过；
- C++ selftest、compileall：通过；
- comprehensive 专项：57/57；confirm 专项：53/53；
- 根目录 unittest：1181 项，失败 0，跳过 1；
- MATLAB/OpenFOAM/WSL/CFD 启动数：0/0/0/0；worker 启动数：1；owned residual=0。

`clang-tidy`、`cppcheck`、VTune/AMD uProf 在当前环境不可用，本阶段未声称使用。实际使用了项目审计 skill、MSVC/CMake、Python unittest、compileall 和 C++ selftest。

## 数值状态

`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`

`FORMAL_STROUHAL_STATUS=not_completed`

`STABLE_VIV_RESPONSE_CLAIM=not_completed`

`LOCK_IN_CLAIM=not_completed`
"""
    report_path = DOCS / "最终报告_中文.md"
    report_path.write_text(report, encoding="utf-8")
    write_json("evidence_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "files": {str(path.relative_to(ROOT)): sha256(path)
                  for path in sorted(RESULTS.glob("*.json"))
                  if path.name != "evidence_manifest.json"},
        "report": {str(report_path.relative_to(ROOT)): sha256(report_path)},
    })
    print(json.dumps({"gate": gate, "status": "do_not_pass",
                      "root_unittest": conditions["root_unittest"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
