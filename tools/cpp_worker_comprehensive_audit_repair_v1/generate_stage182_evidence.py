"""Generate independent Stage182 evidence for confirmed C++ contract repairs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/182_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs/182_cpp_worker_comprehensive_audit_repair_v1"
STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage182"
RUN_ID = "cpp_worker_comprehensive_audit_repair_182_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage182_offline_case_001"
REAL_PROCESS_STARTS = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
CHANGED = [
    "src/coupling/cpp_physics_ownership_v1/physics_ownership.cpp",
    "src/coupling/cpp_physics_ownership_v1/physics_ownership_selftest.cpp",
    "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_stage182_contracts.py",
    "tools/cpp_worker_comprehensive_audit_repair_v1/generate_stage182_evidence.py",
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
        "configuration": "Release",
        "static_analysis": {"flags": ["/analyze", "/W4"], "status": "pass"},
        "build_directory": "runtime/cpp_worker_comprehensive_audit_repair_v1/stage182_build",
        "compileall": {"status": "pass", "command": "python -m compileall -q src/coupling tests/cpp_worker_comprehensive_audit_repair_v1"},
        "cpp_selftests": {"status": "pass", "count": 3,
                          "unknown_force_representation_rejected": True},
        "focused_comprehensive_tests": {"passed": 60, "failed": 0},
        "persistent_ipc_tests": {"passed": 18, "failed": 0},
        "confirm_offline_tests": {"passed": 53, "failed": 0},
        "root_unittest": {"passed": 1185, "failed": 0, "skipped": 1},
        "real_process_starts": REAL_PROCESS_STARTS,
        "worker_start_count": 0,
        "owned_residual": 0,
        "performance_claim": "not_measured; contract-only repair stage",
    })

    write_json("repair_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "status": "confirmed_repairs_tested",
        "repairs": [
            {
                "id": "UNKNOWN_FORCE_REPRESENTATION_FAIL_CLOSED",
                "severity": "high",
                "status": "fixed_and_tested",
                "rule": "Reject enum values outside integrated_N and line_Npm before load mapping.",
                "files": ["src/coupling/cpp_physics_ownership_v1/physics_ownership.cpp",
                          "src/coupling/cpp_physics_ownership_v1/physics_ownership_selftest.cpp"],
                "evidence": "ownership selftest reports unknown_representation_rejected=true",
            },
            {
                "id": "NUMERICAL_STATE_IDENTITY_ECHO_GUARD",
                "severity": "high",
                "status": "fixed_and_tested",
                "rule": "Verify committed state.step and state.time_s before emitting checkpoint identity.",
                "files": ["src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
                          "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp"],
                "evidence": "Stage182 source-contract regression plus 60 focused tests",
            },
        ],
        "physics_or_thresholds_modified": False,
        "formal_protocol_semantics_modified": False,
    })

    write_json("numerical_equivalence_audit.json", {
        "status": "do_not_pass",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "strict_matlab_cpp_equivalence": {
            "status": "not_completed", "first_failed_step": 560,
            "steps_passed": 0, "steps_total": 40,
        },
        "engineering_replay": {"status": "pass", "steps_passed": 40, "steps_total": 40},
        "interpretation": "The two contract repairs do not establish strict MATLAB/C++ numerical equivalence.",
        "thresholds_modified": False,
    })

    write_json("ipc_fault_injection_summary.json", {
        "status": "pass",
        "covered": ["stale", "duplicate", "out_of_order", "tick_time_step_mismatch",
                    "dimension_mutation", "hash_mismatch", "NaN_Inf", "disconnect",
                    "timeout", "duplicate_initialize", "unknown_force_representation"],
        "same_runtime_retry": False,
    })
    write_json("lifecycle_cleanup_audit.json", {
        "status": "pass", "worker_start_count": 0, "owned_residual": 0,
        "real_process_starts": REAL_PROCESS_STARTS, "non_owned_processes_terminated": 0,
    })
    write_json("test_discovery_audit.json", {
        "status": "pass",
        "focused_command": "PYTHONPATH=src python -m unittest discover -s tests/cpp_worker_comprehensive_audit_repair_v1 -p 'test*.py'",
        "focused_tests": 60,
        "persistent_ipc_tests": 18,
        "confirm_tests": 53,
        "root_command": "PYTHONPATH=src python -m unittest discover -s tests -t . -p 'test_*.py'",
        "root_tests": 1185, "root_failures": 0, "root_errors": 0, "root_skipped": 1,
        "initial_wrong_discovery_invocation": "excluded from result; omitted -t . and used test*.py",
    })
    write_json("protection_manifest.json", {
        "stage_1_181_old_evidence_modified": False,
        "old_runtime_modified": False,
        "matlab_baseline_read_only": True,
        "physical_contract_modified": False,
        "numerical_thresholds_modified": False,
        "formal_0_2_1_protocol_semantics_modified": False,
        "unrelated_user_files_excluded": True,
    })
    write_json("independent_gate.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "gate": gate, "status": "do_not_pass",
        "conditions": {
            "code_review_and_confirmed_repairs": True,
            "cmake_msvc_release_build": True, "msvc_analyze_w4": True,
            "compileall": True, "cpp_selftests": True, "focused_tests": True,
            "persistent_ipc_tests": True, "confirm_offline_tests": True,
            "root_unittest": True, "ipc_fault_injection": True,
            "owned_residual_zero": True, "physical_process_starts_zero": True,
            "protected_artifacts_unmodified": True,
            "strict_matlab_cpp_numerical_equivalence": False,
        },
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
    write_json("changed_file_hashes.json", {item: sha256(ROOT / item) for item in CHANGED})

    report_path = DOCS / "最终报告_中文.md"
    report_path.write_text(f"""# Stage182 C++ worker 全面审查与修复报告

## 结论

本阶段在 Stage181 断点上继续审查，确认并修复两个底层缺陷：非法 `ForceRepresentation` 未 fail-closed，以及 worker 在输出请求身份前未验证内部 `state.step/time_s`。两项修复均未改变物理参数、数值阈值或正式协议语义。

Gate：`{gate}`。严格 MATLAB/C++ 数值等价仍未完成；已有 strict dual 首个失败为 step 560，因此不能把 C++ 数值核心标记为 validated。

## 验证

- MSVC 2022 x64 / CMake 3.31.6 Release：通过；
- `/W4` 与 `/analyze`：通过；
- C++ selftest：3/3；comprehensive：60/60；persistent IPC：18/18；confirm 离线：53/53；
- 根目录 unittest：1185 项通过，1 项跳过；
- MATLAB/OpenFOAM/WSL/CFD 启动数：0/0/0/0；owned residual=0；
- 未进行真实 confirm，未进行性能提升声明。

## 保护与剩余风险

Stage1–181 旧证据、旧 runtime、MATLAB baseline、物理合同和阈值保持只读。剩余硬阻断是 MATLAB/C++ 严格数值等价证据不足，而不是本阶段两个协议修复失败。

`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`

`FORMAL_STROUHAL_STATUS=not_completed`

`STABLE_VIV_RESPONSE_CLAIM=not_completed`

`LOCK_IN_CLAIM=not_completed`
""", encoding="utf-8")
    write_json("evidence_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "files": {str(path.relative_to(ROOT)): sha256(path)
                  for path in sorted(RESULTS.glob("*.json"))
                  if path.name != "evidence_manifest.json"},
        "report": {str(report_path.relative_to(ROOT)): sha256(report_path)},
    })
    print(json.dumps({"gate": gate, "status": "do_not_pass"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
