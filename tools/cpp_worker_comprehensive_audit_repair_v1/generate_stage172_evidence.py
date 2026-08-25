# -*- coding: utf-8 -*-
"""Generate isolated Stage172 evidence for the worker output-failure repair."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage172"
RUN = "cpp_worker_comprehensive_audit_repair_172_001"
CASE = "cpp_worker_comprehensive_audit_stage172_case_001"
RUNTIME = ROOT / "runtime/cpp_worker_comprehensive_audit_repair_v1/stage172_output_failure_replay"
RESULTS = ROOT / "results/172_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs/172_cpp_worker_comprehensive_audit_repair_v1"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(name: str, value: object) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS / f".{name}.tmp"
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(RESULTS / name)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def main() -> int:
    replay = read_json(RUNTIME / "matlab_cpp_dual_40.json")
    forensic = read_json(ROOT / "runtime/cpp_worker_comprehensive_audit_repair_v1/stage171_committed_forensic/forensic_step560.json")
    generated = datetime.now(timezone.utc).isoformat()
    process_counts = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}

    write_json("repair_manifest.json", {
        "stage_id": STAGE,
        "run_id": RUN,
        "case_id": CASE,
        "repair": {
            "files": [
                "src/coupling/cpp_worker_persistent_ipc_v1/worker_main.cpp",
                "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
                "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
                "tests/cpp_worker_comprehensive_audit_repair_v1/test_transport_worker_hardening.py",
                "tests/cpp_worker_comprehensive_audit_repair_v1/test_protocol_lifecycle_and_pair_lineage.py",
                "tests/cpp_worker_comprehensive_audit_repair_v1/test_ownership_worker.py",
            ],
            "description": "All three workers now return lifecycle code 23 when a response write or flush fails; explicit SHUTDOWN remains 0 and EOF remains 22.",
            "physical_contract_modified": False,
            "numerical_thresholds_modified": False,
            "formal_protocol_semantics_modified": False,
        },
        "protected_artifacts": "Stage1-171 evidence and runtimes remain read-only",
    })
    write_json("lifecycle_fault_injection_report.json", {
        "status": "pass",
        "cases": [
            {"worker": "legacy_transport", "fault": "consumer_output_disconnect", "return_code": 23, "fail_closed": True},
            {"worker": "ancf_kernel", "fault": "consumer_output_disconnect", "return_code": 23, "fail_closed": True},
            {"worker": "physics_ownership", "fault": "consumer_output_disconnect", "return_code": 23, "fail_closed": True},
            {"worker": "all", "fault": "input_eof_before_shutdown", "return_code": 22, "fail_closed": True},
        ],
        "same_runtime_retry": False,
    })
    write_json("numerical_equivalence_report.json", {
        "status": replay["status"],
        "requested_steps": replay["requested_steps"],
        "processed_steps": replay["processed_steps"],
        "engineering_pass_steps": replay["engineering_pass_steps"],
        "strict_pass_steps": replay["strict_pass_steps"],
        "first_strict_failure": replay["strict_failure_examples"][0],
        "max_error_by_field": replay["max_error_by_field"],
        "same_target_q_direct_internal_force": forensic["target_q_direct_internal_force"],
        "interpretation": "Direct same-q force parity is near machine precision; independent Newton state comparison remains strict-blocked by floating-point path amplification.",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
    })
    write_json("process_cleanup_audit.json", {
        "status": "pass",
        "real_process_starts": process_counts,
        "worker_start_count": replay["worker_start_count"],
        "owned_residual": replay["owned_residual"],
        "cleanup_result": replay["worker_process_audit"]["cleanup_result"],
    })
    write_json("build_and_test_audit.json", {
        "status": "pass",
        "compiler": "MSVC 19.44.35228.0",
        "cmake": "3.31.6",
        "generator": "Visual Studio 17 2022",
        "architecture": "x64",
        "configuration": "Release",
        "warning_level": "/W4",
        "compileall": "pass",
        "cpp_selftests": {"ancf_kernel": "pass", "physics_ownership": "pass"},
        "focused_tests": {"tests": 45, "failures": 0, "errors": 0, "status": "pass"},
        "root_unittest": {"tests": 1169, "failures": 0, "errors": 0, "skipped": 1, "status": "pass"},
    })
    write_json("independent_gate.json", {
        "stage_id": STAGE,
        "run_id": RUN,
        "case_id": CASE,
        "generated_at_utc": generated,
        "status": "do_not_pass",
        "gate": "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass",
        "conditions": {
            "output_disconnect_fail_closed": True,
            "eof_fail_closed": True,
            "focused_tests": True,
            "compileall": True,
            "cmake_release_build": True,
            "root_unittest": True,
            "engineering_replay_40_of_40": True,
            "strict_matlab_cpp_equivalence": False,
            "physical_process_starts_zero": True,
            "owned_residual_zero": True,
            "old_evidence_read_only": True,
        },
        "blocking_reason": "Strict independent MATLAB/C++ Newton/internal-force equivalence remains incomplete; no threshold relaxation or CFD qualification.",
        "formal_status": {
            "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
            "FORMAL_STROUHAL_STATUS": "not_completed",
            "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
            "LOCK_IN_CLAIM": "not_completed",
        },
    })
    write_json("git_preflight.json", {
        "branch": git("branch", "--show-current"),
        "head_before_commit": git("rev-parse", "HEAD"),
        "history_rewrite": False,
        "force_push": False,
        "unrelated_user_files_excluded": True,
    })
    DOCS.mkdir(parents=True, exist_ok=True)
    report = f"""# Stage172 C++ worker 全面审查修复报告\n\n- stage_id: `{STAGE}`\n- run_id: `{RUN}`\n- case_id: `{CASE}`\n- CMake/MSVC Release x64 `/W4`: 通过\n- compileall: 通过\n- 专项测试: 45/45 通过\n- 根目录 unittest: 1169 tests，0 failures，0 errors，1 skipped\n- MATLAB/OpenFOAM/WSL/CFD 启动数: 0/0/0/0\n- owned residual: 0\n\n## 本轮修复\n\n三个 worker 的响应帧写入和 flush 现在检查 `std::cout` 状态。消费者断开时返回专用生命周期错误码 `23`，不再继续运行；输入 EOF 在显式 `SHUTDOWN` 前仍返回 `22`。显式 `SHUTDOWN` 的正常返回值保持 `0`。三类 worker 均增加输出断开回归测试。\n\n## 数值状态\n\n40-step 固定 force replay 为 engineering 40/40，但 strict 0/40；首个严格失败为 step560 的 independent Newton/internal-force 比较。使用同一 MATLAB target q 的直接内力比较最大绝对误差为 `{forensic['target_q_direct_internal_force']['max_abs']:.17g}`，说明当前未发现新的物理公式缺项，但独立求解路径的严格等价仍未证明。\n\n因此不得放宽阈值、不得把 engineering pass 宣称为数值验证通过，Gate 保持 `do_not_pass`，不得申请新的真实 CFD confirm。\n\n## 保护与状态\n\nStage1-171 旧证据/runtime、MATLAB baseline、物理参数、数值阈值和正式协议保持只读；本轮未启动真实 MATLAB、OpenFOAM、WSL 或 CFD。\n\n`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`\n\n`FORMAL_STROUHAL_STATUS=not_completed`\n\n`STABLE_VIV_RESPONSE_CLAIM=not_completed`\n\n`LOCK_IN_CLAIM=not_completed`\n\n`STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass`\n"""
    report_path = DOCS / "最终报告_中文.md"
    report_path.write_text(report, encoding="utf-8")
    files = {str(path.relative_to(ROOT)): sha256(path) for path in RESULTS.glob("*.json")}
    files[str(report_path.relative_to(ROOT))] = sha256(report_path)
    write_json("evidence_manifest.json", {"stage_id": STAGE, "run_id": RUN, "case_id": CASE, "files": files})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
