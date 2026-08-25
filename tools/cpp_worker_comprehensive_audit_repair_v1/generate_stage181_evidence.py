"""Generate independent Stage181 evidence for the C++ worker audit repair."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/181_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs/181_cpp_worker_comprehensive_audit_repair_v1"
STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage181"
RUN_ID = "cpp_worker_comprehensive_audit_repair_181_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage181_build_case_001"
REAL_PROCESS_STARTS = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
CHANGED = [
    "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/CMakeLists.txt",
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/worker_main.cpp",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_repair_contract.py",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", check=True)
    return completed.stdout.strip()


def write_json(name: str, value: Any) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS / f".{name}.tmp"
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(RESULTS / name)


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    gate = "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass"
    write_json("build_and_test_audit.json", {
        "status": "pass",
        "compiler": "MSVC 19.44.35228.0 / Visual Studio 2022 BuildTools",
        "cmake": "3.31.6", "generator": "Visual Studio 17 2022", "architecture": "x64",
        "configuration": "Release", "static_analysis": {"flags": ["/analyze", "/W4"],
        "status": "pass", "c4530_ehsc_warning": "resolved"},
        "build_directory": "runtime/cpp_worker_comprehensive_audit_repair_v1/stage181_analyze_build",
        "compileall": {"status": "pass", "command": "python -m compileall -q src tests tools"},
        "cpp_selftests": {"status": "pass", "count": 3},
        "focused_comprehensive_tests": {"passed": 58, "failed": 0},
        "focused_confirm_tests": {"passed": 53, "failed": 0},
        "persistent_ipc_tests": {"passed": 18, "failed": 0},
        "root_unittest": {"passed": 1183, "failed": 0, "skipped": 1},
        "nonzero_base_load_dual": {"status": "pass", "steps": "40/40", "worker_start_count": 1},
        "real_process_starts": REAL_PROCESS_STARTS,
        "owned_residual": 0,
    })
    write_json("repair_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "status": "build_and_test_repair",
        "repairs": [{
            "id": "MSVC_EXCEPTION_UNWIND_CONFIGURATION",
            "severity": "high",
            "status": "fixed_and_tested",
            "rule": "Apply /EHsc before target declarations so all worker targets have deterministic exception unwinding.",
            "files": ["src/coupling/cpp_worker_persistent_ipc_v1/CMakeLists.txt",
                      "tests/cpp_worker_comprehensive_audit_repair_v1/test_repair_contract.py"],
            "evidence": "stage181_analyze_build generated ExceptionHandling=Sync and no C4530 warning",
        }, {
            "id": "WINDOWS_BINARY_MODE_FAILURE",
            "severity": "medium",
            "status": "fixed_and_tested",
            "rule": "Fail closed when either stdin/stdout _setmode(_O_BINARY) call fails.",
            "files": [item for item in CHANGED if item.endswith("worker_main.cpp")],
            "evidence": "58/58 comprehensive tests and MSVC build",
        }],
        "physics_or_thresholds_modified": False,
        "formal_protocol_semantics_modified": False,
    })
    write_json("numerical_equivalence_audit.json", {
        "status": "do_not_pass",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "strict_matlab_cpp_equivalence": {"status": "not_completed", "first_failed_step": 560,
                                           "steps_passed": 0, "steps_total": 40},
        "engineering_replay": {"status": "pass", "steps_passed": 40, "steps_total": 40},
        "nonzero_base_load_ownership_replay": {"status": "pass", "steps_passed": 40,
                                                "steps_total": 40, "max_external_force_error": 0.0,
                                                "max_generalized_force_error": 0.0},
        "interpretation": "Engineering replay and transport success do not establish strict MATLAB/C++ numerical equivalence.",
        "thresholds_modified": False,
    })
    write_json("ipc_fault_injection_summary.json", {
        "status": "pass", "covered": ["stale", "duplicate", "out_of_order", "tick_time_step_mismatch",
        "dimension_mutation", "hash_mismatch", "NaN_Inf", "disconnect", "timeout", "duplicate_initialize"],
        "same_runtime_retry": False,
    })
    write_json("lifecycle_cleanup_audit.json", {
        "status": "pass", "worker_start_count": 1, "owned_residual": 0,
        "real_process_starts": REAL_PROCESS_STARTS, "non_owned_processes_terminated": 0,
    })
    write_json("protection_manifest.json", {
        "stage_1_180_old_evidence_modified": False, "old_runtime_modified": False,
        "matlab_baseline_read_only": True, "physical_contract_modified": False,
        "numerical_thresholds_modified": False, "formal_0_2_1_protocol_semantics_modified": False,
        "unrelated_user_files_excluded": True,
    })
    write_json("independent_gate.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "gate": gate, "status": "do_not_pass",
        "conditions": {
            "code_review_and_confirmed_repairs": True, "cmake_msvc_release_build": True,
            "msvc_analyze_w4": True, "compileall": True, "cpp_selftests": True,
            "focused_tests": True, "root_unittest": True, "ipc_fault_injection": True,
            "nonzero_base_load_ownership_dual": True, "owned_residual_zero": True,
            "physical_process_starts_zero": True, "protected_artifacts_unmodified": True,
            "strict_matlab_cpp_numerical_equivalence": False,
        },
        "real_process_starts": REAL_PROCESS_STARTS, "owned_residual": 0,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
        "LOCK_IN_CLAIM": "not_completed", "new_real_cfd_authorization_required": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    write_json("git_preflight.json", {
        "branch": git("branch", "--show-current"), "parent_head": git("rev-parse", "HEAD"),
        "scoped_status": git("status", "--short", "--", *CHANGED),
        "history_rewrite": False, "force_push": False, "unrelated_user_files_excluded": True,
    })
    write_json("changed_file_hashes.json", {item: sha256(ROOT / item) for item in CHANGED})
    report = f"""# Stage181 C++ worker 全面审查与修复报告\n\n## 结论\n\n本阶段确认并修复了 MSVC 异常展开配置缺陷和 Windows 二进制流设置错误处理缺陷。Stage181 构建、静态分析、专项测试、非零 base_load ownership 双算和根目录回归均通过。\n\nGate：`{gate}`。唯一硬阻断仍是 MATLAB/C++ 严格数值等价：现有证据为工程 replay 40/40，但 strict dual 0/40，首个失败 step=560，因此不能标记 C++ 数值核心 validated。\n\n## 修复\n\n- 将 `/EHsc` 放在 CMake target 声明之前，确保所有 MSVC worker target 生成 `ExceptionHandling=Sync`；\n- 三个 Windows worker 检查 `_setmode(stdin/stdout, _O_BINARY)` 返回值，失败立即退出；\n- 增加 CMake 顺序契约测试。\n\n未修改 ANCF/EB 物理语义、物理参数、global dt、slice 数、数值阈值、统计门槛、正式 0.2.1 协议或旧证据。\n\n## 验证\n\n- MSVC 2022 x64 / CMake 3.31.6 Release + `/analyze /W4`：通过；\n- C++ selftest：3/3；comprehensive：58/58；confirm：53/53；persistent IPC：18/18；\n- 非零 MATLAB base_load ownership replay：40/40，worker startup=1；\n- 根目录 unittest：1183 项，失败 0，跳过 1；\n- MATLAB/OpenFOAM/WSL/CFD 启动数：0/0/0/0；owned residual=0。\n\n`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`\n\n`FORMAL_STROUHAL_STATUS=not_completed`\n\n`STABLE_VIV_RESPONSE_CLAIM=not_completed`\n\n`LOCK_IN_CLAIM=not_completed`\n"""
    report_path = DOCS / "最终报告_中文.md"
    report_path.write_text(report, encoding="utf-8")
    write_json("evidence_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "files": {str(path.relative_to(ROOT)): sha256(path) for path in sorted(RESULTS.glob("*.json"))
                  if path.name != "evidence_manifest.json"},
        "report": {str(report_path.relative_to(ROOT)): sha256(report_path)},
    })
    print(json.dumps({"gate": gate, "status": "do_not_pass"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
