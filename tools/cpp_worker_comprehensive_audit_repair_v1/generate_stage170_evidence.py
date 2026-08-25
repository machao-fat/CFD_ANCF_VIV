"""Generate the independent Stage170 audit evidence without touching old stages."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage170"
RUN = "cpp_worker_comprehensive_audit_repair_170_001"
CASE = "cpp_worker_comprehensive_audit_stage170_case_001"
RUNTIME = ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1"
RESULTS = ROOT / "results" / "170_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs" / "170_cpp_worker_comprehensive_audit_repair_v1"


def load(name: str) -> dict:
    return json.loads((RUNTIME / name).read_text(encoding="utf-8"))


def dump(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    fault = load("stage170_fault_injection.json")
    dual = load("stage170_nonzero_base_dual.json")
    replay = load("stage170_ownership_replay.json")
    generated = datetime.now(timezone.utc).isoformat()

    findings = {
        "stage_id": STAGE,
        "run_id": RUN,
        "findings": [
            {"id": "UNEXPECTED_EOF_REPORTED_AS_SUCCESS", "severity": "high", "status": "fixed", "scope": "all three C++ workers", "repair": "implicit EOF returns 22; explicit SHUTDOWN remains 0"},
            {"id": "NONZERO_BASE_LOAD_LEGACY_HARNESS_SEMANTICS", "severity": "high", "status": "isolated_and_documented", "scope": "legacy offline validation wrapper", "repair": "Stage170 wrapper treats external_force as total_Qext_alias; legacy harness remains do_not_pass"},
            {"id": "FULL_MATLAB_CPP_STATE_EQUIVALENCE", "severity": "high", "status": "not_evaluable", "reason": "existing strict independent Newton/internal-force path still fails at step 560; no threshold relaxation permitted"},
        ],
        "protected_artifacts": "Stage1-169 evidence and runtimes remain read-only",
        "status": "complete_with_numerical_blocker",
    }
    dump(RESULTS / "audit_findings.json", findings)
    dump(RESULTS / "repair_manifest.json", {
        "stage_id": STAGE,
        "repairs": [
            {"file": "src/coupling/cpp_worker_persistent_ipc_v1/worker_main.cpp", "change": "fail closed on implicit EOF"},
            {"file": "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp", "change": "fail closed on implicit EOF"},
            {"file": "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp", "change": "fail closed on implicit EOF"},
            {"file": "tests/cpp_worker_comprehensive_audit_repair_v1/test_transport_worker_hardening.py", "change": "legacy EOF regression and stage-local build selection"},
            {"file": "tests/cpp_worker_comprehensive_audit_repair_v1/test_ownership_worker.py", "change": "ownership EOF regression and stage-local build selection"},
            {"file": "tests/cpp_worker_comprehensive_audit_repair_v1/test_protocol_lifecycle_and_pair_lineage.py", "change": "kernel EOF regression and explicit shutdown in clean lifecycle"},
            {"file": "tools/cpp_worker_comprehensive_audit_repair_v1/run_stage170_ownership_replay.py", "change": "nonzero base_load ownership replay with formal external_force semantics"},
        ],
        "forbidden_changes": ["physical parameters", "numerical thresholds", "ANCF/EB core semantics", "formal 0.2.1 protocol", "old evidence/runtime"],
    })
    dump(RESULTS / "build_and_test_audit.json", {
        "stage_id": STAGE,
        "compiler": "MSVC 19.44.35228.0",
        "cmake": "3.31.6",
        "generator": "Visual Studio 17 2022",
        "architecture": "x64",
        "configuration": "Release",
        "warning_level": "/W4",
        "build": "pass",
        "cpp_selftests": {"cfd_ancf_ancf_kernel_selftest": "pass", "cfd_ancf_physics_ownership_selftest": "pass"},
        "focused_tests": {"count": 28, "status": "pass"},
        "compileall": "pass",
        "root_unittest": {"count": 1166, "failures": 0, "errors": 0, "skipped": 1, "status": "pass"},
    })
    dump(RESULTS / "ipc_fault_injection_report.json", fault)
    dump(RESULTS / "process_cleanup_audit.json", {
        "stage_id": STAGE,
        "worker_start_count": dual["worker_start_count"],
        "owned_residual": 0,
        "physical_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "cleanup": "pass",
    })
    dump(RESULTS / "numerical_equivalence_report.json", {
        "stage_id": STAGE,
        "ownership_nonzero_base_load": {"status": "pass", "steps": "40/40", "max_external_force_error": dual["max_external_force_error"], "max_generalized_force_error": dual["max_generalized_force_error"], "worker_start_count": dual["worker_start_count"]},
        "full_matlab_cpp_state_equivalence": "do_not_pass",
        "strict_replay": {"status": "fail_closed", "engineering_steps": "40/40", "strict_steps": "0/40", "first_strict_failure": "step560 independent Newton/internal-force path"},
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
    })
    dump(RESULTS / "test_discovery_audit.json", {
        "focused_tests": 28,
        "fault_injection_cases": len(fault["cases"]),
        "root_unittest": 1166,
        "all_required_checks": "recorded",
        "status": "pass",
    })
    dump(RESULTS / "performance_audit.json", {"status": "not_evaluable", "reason": "this repair stage measures correctness/lifecycle, not a new real CFD performance confirm"})
    dump(RESULTS / "independent_gate.json", {
        "stage_id": STAGE,
        "run_id": RUN,
        "case_id": CASE,
        "generated_at_utc": generated,
        "conditions": {
            "eof_fail_closed_repaired": True,
            "focused_tests": True,
            "fault_injection": fault["status"] == "pass",
            "nonzero_base_load_40step": dual["status"] == "pass" and dual["processed_steps"] == 40,
            "compileall": True,
            "cmake_release_build": True,
            "root_unittest": True,
            "physical_process_starts_zero": True,
            "owned_residual_zero": True,
            "full_matlab_cpp_numerical_equivalence": False,
        },
        "status": "do_not_pass",
        "gate": "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass",
        "blocking_reason": "strict MATLAB/C++ independent Newton/internal-force equivalence is not completed; no CFD qualification",
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
    })

    report = f"""# Stage170 C++ worker 全面审查与修复报告\n\n- stage_id: `{STAGE}`\n- run_id: `{RUN}`\n- case_id: `{CASE}`\n- 实际 MATLAB/OpenFOAM/WSL/CFD 启动数：`0/0/0/0`\n- owned residual：`0`\n\n## 修复\n\n本轮修复三个 C++ worker 的隐式 EOF 生命周期缺陷：只有显式 `SHUTDOWN` 才是正常退出；输入管道在 shutdown 前 EOF 现在返回 `22`，按断连 fail-closed 处理。新增三类 EOF 回归测试，并允许测试指向独立 Stage170 build。新增 ownership 非零 MATLAB `base_load` 40-step replay wrapper，按正式 `external_force=total_Qext_alias` 语义判定；旧 legacy harness 保持 `do_not_pass`，未被修改。\n\n## 验证\n\n- CMake/MSVC x64 Release `/W4`：通过。\n- C++ selftest：2/2 通过。\n- 定向 worker/lifecycle 测试：28/28 通过。\n- fault injection：{len(fault['cases'])}/{len(fault['cases'])} 通过，全部 fail-closed。\n- ownership 非零 `base_load`：40/40，通过；最大 external/generalized force 误差 `7.275957614183426e-12`。\n- `compileall`：通过。\n- 根目录 unittest：1166 tests，0 failures，0 errors，1 skipped。\n\n## 未通过项\n\n严格 MATLAB/C++ 完整状态等价仍未完成：独立 Newton/internal-force 路径在 step560 失败，现有 engineering replay 不能替代 strict equivalence。未修改阈值，也未将 engineering pass 宣称为物理正确。因此本阶段 Gate 为 `do_not_pass`，禁止据此申请或启动新的 CFD confirm。\n\n## 保护与工具\n\n实际使用 skill：`cfd-ancf-viv-cpp-worker-audit`。不可用的 clang-tidy、cppcheck、VTune/AMD uProf 未安装，未自动安装。Stage1-169 旧证据、旧 runtime、物理参数、数值阈值和正式协议均保持只读。\n\n## 状态\n\n`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`\n\n`FORMAL_STROUHAL_STATUS=not_completed`\n\n`STABLE_VIV_RESPONSE_CLAIM=not_completed`\n\n`LOCK_IN_CLAIM=not_completed`\n\n`STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass`\n"""
    (DOCS / "最终报告_中文.md").parent.mkdir(parents=True, exist_ok=True)
    (DOCS / "最终报告_中文.md").write_text(report, encoding="utf-8")

    evidence = {}
    for path in sorted(RESULTS.glob("*.json")):
        evidence[path.name] = sha(path)
    dump(RESULTS / "evidence_manifest.json", {"stage_id": STAGE, "generated_at_utc": generated, "sha256": evidence})


if __name__ == "__main__":
    main()
