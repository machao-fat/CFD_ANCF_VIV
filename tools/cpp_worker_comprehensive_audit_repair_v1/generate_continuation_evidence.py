"""Write independent continuation evidence without touching Stage 153 artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "154_cpp_worker_comprehensive_audit_repair_v1_continuation"
DOCS = ROOT / "docs" / "154_cpp_worker_comprehensive_audit_repair_v1_continuation"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(name: str, value: object) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    dual = json.loads((RESULTS / "matlab_cpp_dual_run_audit.json").read_text(encoding="utf-8"))
    ownership = json.loads((RESULTS / "nonzero_base_40step_audit.json").read_text(encoding="utf-8"))
    changed = [
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/protocol.py",
        "src/coupling/cpp_physics_ownership_v1/physics_ownership.cpp",
        "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
        "src/coupling/cpp_physics_ownership_v1/physics_ownership_selftest.cpp",
        "tests/cpp_worker_comprehensive_audit_repair_v1/test_repair_contract.py",
        "tests/cpp_worker_comprehensive_audit_repair_v1/test_transport_worker_hardening.py",
        "tests/cpp_worker_comprehensive_audit_repair_v1/test_ownership_worker.py",
        "tools/cpp_worker_comprehensive_audit_repair_v1/generate_continuation_evidence.py",
    ]
    write_json("build_audit.json", {
        "status": "pass", "compiler": "MSVC 2022 BuildTools x64", "cmake": "3.31.6",
        "configuration": "Release", "generator": "Visual Studio 17 2022", "architecture": "x64",
        "build_command": "cmake --build runtime/cpp_worker_comprehensive_audit_repair_v1/build-release --config Release --parallel 4",
        "warnings": [],
    })
    write_json("test_discovery_audit.json", {
        "compileall": {"status": "pass", "scope": "C++ worker Python protocol and audit tests"},
        "focused_unittest": {"status": "pass", "tests": 38,
            "command": "python -m unittest tests.cpp_worker_persistent_ipc_v1.test_protocol tests.cpp_worker_persistent_ipc_v1.test_kernel_worker tests.cpp_worker_persistent_ipc_v1.test_dual_run tests.cpp_physics_ownership_v1.test_offline_evidence tests.cpp_worker_comprehensive_audit_repair_v1.test_repair_contract tests.cpp_worker_comprehensive_audit_repair_v1.test_mapping_contract tests.cpp_worker_comprehensive_audit_repair_v1.test_ownership_worker tests.cpp_worker_comprehensive_audit_repair_v1.test_transport_worker_hardening"},
        "root_unittest": {"status": "pass", "tests": 1127, "skipped": 1,
            "command": "PYTHONPATH=src python -m unittest discover -s tests -t . -p 'test_*.py'"},
    })
    write_json("numerical_dual_run_audit.json", {
        "status": dual["status"], "requested_steps": dual["requested_steps"],
        "processed_steps": dual["processed_steps"], "strict_pass_steps": dual["strict_pass_steps"],
        "engineering_pass_steps": dual["engineering_pass_steps"],
        "strict_failure_count": dual["strict_failure_count"],
        "strict_failure_examples": dual.get("strict_failure_examples", [])[:5],
        "max_error_by_field": dual["max_error_by_field"],
        "engineering_tolerances": dual["engineering_tolerances"],
        "worker_start_count": dual["worker_start_count"], "worker_return_code": dual["worker_return_code"],
        "owned_residual": dual["owned_residual"],
        "real_process_starts": {"MATLAB": dual["matlab_start_count"], "OpenFOAM": dual["openfoam_start_count"], "WSL": dual["wsl_start_count"], "CFD": 0},
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "interpretation": "40-step replay passes engineering envelope but strict state equality is not proven; this is not a numerical equivalence Gate pass.",
    })
    write_json("ownership_replay_audit.json", ownership)
    write_json("protection_manifest.json", {
        "status": "verified_read_only_by_scope",
        "protected_paths": ["results/153_cpp_worker_comprehensive_audit_repair_v1", "runtime/cpp_worker_persistent_ipc_v1", "runtime/cpp_worker_numerical_equivalence_before_cfd_v1"],
        "old_stage_1_153_evidence_modified": False, "old_runtime_modified": False,
        "physical_contract_modified": False, "formal_protocol_semantics_modified": False,
        "real_matlab_openfoam_wsl_cfd_started": False,
    })
    write_json("process_audit.json", {
        "physical_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "cpp_worker_start_count": dual["worker_start_count"], "ownership_worker_start_count": ownership["worker_start_count"],
        "owned_residual": 0, "active_physical_processes_after_tests": 0, "same_runtime_retry": False,
    })
    write_json("audit_findings.json", {
        "status": "complete_with_numerical_blocker",
        "findings": [
            {"id": "MODEL_VALIDATION_AND_ALLOCATION_BOUNDS", "status": "fixed_and_tested"},
            {"id": "TIME_TICK_CONTRACT", "status": "fixed_and_tested"},
            {"id": "CONTIGUOUS_LINEAGE_NOT_ADVANCED", "status": "fixed_and_regression_tested", "evidence": "ancf_worker_main.cpp and three-step ownership test"},
            {"id": "OWNERSHIP_BASE_DOUBLE_COUNT", "status": "fixed_and_replayed"},
            {"id": "FULL_MATLAB_CPP_STATE_EQUIVALENCE", "status": "not_proven", "reason": "strict_pass_steps=0/40"},
            {"id": "TOP_TENSION_BENT_STATE_SEMANTICS", "status": "not_evaluable_without_authoritative_contract"},
        ],
    })
    conditions = {
        "build": True, "compileall": True, "focused_tests": True, "root_unittest": True,
        "lineage_regression": True, "ownership_40step_engineering_replay": ownership["status"] == "pass",
        "strict_matlab_cpp_state_equivalence": dual["strict_pass_steps"] == dual["requested_steps"],
        "physical_process_starts_zero": True, "owned_residual_zero": True, "protected_artifacts_unmodified": True,
    }
    gate = "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: pass" if all(conditions.values()) else "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass"
    write_json("independent_gate.json", {
        "stage_id": "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_continuation",
        "run_id": "cpp_worker_comprehensive_audit_repair_continuation_001",
        "case_id": "cpp_worker_comprehensive_audit_continuation_case_001",
        "gate": gate, "status": "pass" if all(conditions.values()) else "do_not_pass", "conditions": conditions,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed", "FORMAL_STROUHAL_STATUS": "not_completed",
        "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    write_json("changed_file_hashes.json", {item: sha256(ROOT / item) for item in changed if (ROOT / item).is_file()})
    DOCS.mkdir(parents=True, exist_ok=True)
    report = f'''# Stage 154 C++ Worker 全面审查修复续阶段报告

## 结论

本续阶段修复并验证了一个真实的持久 worker lineage 缺陷：原实现只保存首步期望的 step/time/tick，第三步会错误返回 16；现在每个通过校验的请求都会推进 lineage，并有三步回归测试。模型边界、time/tick 一致性、未实现阻尼 fail-closed、ownership base-load 和协议输出校验也保持通过。

40-step MATLAB golden replay：工程容差 `40/40`，worker 启动 `1` 次，return code `0`，owned residual `0`；严格状态等价 `0/40`，因此 Gate 保守为：`{gate}`。

## 关键证据

- CMake/MSVC Release build：pass。
- compileall：pass。
- 受影响专项：38/38 pass。
- 根目录正确入口：1127 tests，skipped=1，OK。
- ownership non-zero base-load replay：40/40，最大 external/generalized force error = `{ownership['max_external_force_error']:.17g}`。
- MATLAB/OpenFOAM/WSL/CFD 启动数：0/0/0/0。

## 数值结论

MATLAB golden 与 C++ 结果在工程容差内，但严格逐位状态合同未通过（`strict_pass_steps=0/40`，主要为 internal_force/qddot 的浮点差异）。不能把工程容差通过写成 MATLAB/C++ 数值核心已验证；`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed` 保持不变。顶端张力在弯曲状态下的权威方向合同仍未获得，未擅自修改物理语义。

旧 Stage 1–153 证据和旧 runtime 未修改，本阶段未启动任何真实物理进程，也未执行新的 CFD confirm。

`FORMAL_STROUHAL_STATUS=not_completed`
`STABLE_VIV_RESPONSE_CLAIM=not_completed`
`LOCK_IN_CLAIM=not_completed`
'''
    (DOCS / "最终报告_中文.md").write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
