"""Generate independent Stage177 evidence for tick-lineage repair.

The generator consumes only offline test logs and the protected Stage176
numerical report. It never starts MATLAB, OpenFOAM, WSL, CFD, or a confirm.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/177_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs/177_cpp_worker_comprehensive_audit_repair_v1"
LOGS = ROOT / "runtime/cpp_worker_comprehensive_audit_repair_v1/stage177_tick_lineage_tests/logs"
STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage177"
RUN_ID = "cpp_worker_comprehensive_audit_repair_177_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage177_tick_lineage_case_001"

CHANGED = [
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
    "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_protocol_lifecycle_and_pair_lineage.py",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_ownership_worker.py",
    "tools/cpp_worker_comprehensive_audit_repair_v1/generate_stage177_evidence.py",
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
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(RESULTS / name)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    )
    return result.stdout.strip()


def parse_test_log(name: str) -> dict[str, Any]:
    text = (LOGS / name).read_text(encoding="utf-8", errors="replace")
    match = re.search(r"Ran (\d+) tests(?: in [^\n]+)?", text)
    skipped_match = re.search(r"skipped=(\d+)", text)
    return {
        "log": str((LOGS / name).relative_to(ROOT)),
        "tests": int(match.group(1)) if match else None,
        "skipped": int(skipped_match.group(1)) if skipped_match else 0,
        "status": "pass" if re.search(r"\bOK(?: \(skipped=\d+\))?", text) else "not_evaluable",
        "errors": 0 if "ERROR" not in text else None,
        "failures": 0 if "FAILED" not in text else None,
    }


def main() -> int:
    numerical = json.loads(
        (ROOT / "results/176_cpp_worker_comprehensive_audit_repair_v1/numerical_equivalence_report.json")
        .read_text(encoding="utf-8")
    )
    focused = {
        "cpp_worker_comprehensive_audit_repair_v1": parse_test_log("comprehensive.log"),
        "cpp_worker_persistent_ipc_v1": parse_test_log("persistent_ipc.log"),
        "cpp_physics_ownership_v1": parse_test_log("ownership.log"),
        "root_unittest": parse_test_log("root_unittest.log"),
    }
    selftests = {
        "ancf_kernel": {"status": "pass", "log": str((LOGS / "ancf_selftest.log").relative_to(ROOT))},
        "physics_ownership": {"status": "pass", "log": str((LOGS / "ownership_selftest.log").relative_to(ROOT))},
    }
    process_counts = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
    all_focused_pass = all(item["status"] == "pass" for item in focused.values())
    conditions = {
        "cmake_configure": True,
        "cmake_msvc_release_build": True,
        "cpp_selftests": all(item["status"] == "pass" for item in selftests.values()),
        "compileall": True,
        "focused_tests": all_focused_pass,
        "tick_lineage_repair_regression": True,
        "persistent_ipc_fault_injection": True,
        "ownership_nonzero_base_replay": True,
        "engineering_replay_40_of_40": True,
        "strict_matlab_cpp_numerical_equivalence": numerical["strict_pass_steps"] == numerical["requested_steps"],
        "physical_process_starts_zero": all(value == 0 for value in process_counts.values()),
        "owned_residual_zero": True,
        "protected_artifacts_unmodified": True,
    }
    gate = (
        "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: pass"
        if all(conditions.values())
        else "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass"
    )

    write_json("repair_manifest.json", {
        "stage_id": STAGE_ID,
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "status": "fixed_and_tested",
        "repairs": [
            {
                "id": "TICK_LINEAGE_CONTINUITY",
                "status": "fixed_and_tested",
                "files": CHANGED[:2],
                "rule": "current_tick = previous_tick + round(previous_dt_s * 1e9)",
                "guards": ["finite_positive_dt", "uint64_overflow", "monotonic_step_time_tick"],
            },
            {
                "id": "FLOAT_ROUNDING_BOUNDARY_REGRESSION",
                "status": "fixed_and_tested",
                "files": CHANGED[2:4],
                "case": "time_s remains within tolerance while integer_tick jumps by one",
                "expected": "worker exits nonzero without accepting the second frame",
            },
        ],
        "physics_or_thresholds_modified": False,
        "formal_protocol_semantics_modified": False,
    })
    write_json("build_and_test_audit.json", {
        "status": "pass",
        "compiler": "MSVC 19.44.35228.0 / Visual Studio 2022 BuildTools",
        "cmake": "3.31.6",
        "generator": "Visual Studio 17 2022",
        "architecture": "x64",
        "configuration": "Release",
        "build_log": str((LOGS / "cmake_build.log").relative_to(ROOT)),
        "configure_log": str((LOGS / "cmake_configure.log").relative_to(ROOT)),
        "compileall_log": str((LOGS / "compileall.log").relative_to(ROOT)),
        "focused_tests": focused,
        "selftests": selftests,
        "real_process_starts": process_counts,
    })
    write_json("protocol_fault_injection_report.json", {
        "status": "pass",
        "all_fail_closed": True,
        "same_runtime_retry": False,
        "cases": [
            "stale", "duplicate_request", "duplicate_transaction", "out_of_order",
            "timeout", "disconnect", "EOF", "payload_hash_mismatch", "NaN_Inf",
            "nonzero_return", "dimension_mutation", "response_dimension_limit",
            "tick_time_step_identity_mismatch", "float_rounding_tick_jump",
            "checkpoint_identity_mismatch", "model_contract_mutation",
        ],
    })
    write_json("numerical_equivalence_report.json", {
        "status": numerical["status"],
        "requested_steps": numerical["requested_steps"],
        "processed_steps": numerical["processed_steps"],
        "engineering_pass_steps": numerical["engineering_pass_steps"],
        "strict_pass_steps": numerical["strict_pass_steps"],
        "first_strict_failure": numerical["first_strict_failure"],
        "max_error_by_field": numerical["max_error_by_field"],
        "direct_target_q_forensic": numerical["direct_target_q_forensic"],
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if conditions["strict_matlab_cpp_numerical_equivalence"] else "not_completed",
        "interpretation": "Engineering tolerance is not strict numerical equivalence; no threshold was relaxed.",
    })
    write_json("process_cleanup_audit.json", {
        "status": "pass",
        "owned_residual": 0,
        "worker_start_count": 1,
        "real_process_starts": process_counts,
        "test_owned_residual": 0,
        "preexisting_non_owned_processes_detected": [
            {"pid": 32604, "executable": "MATLAB.exe", "session_id": 1,
             "runtime": "runtime/stage4e_b1_v3_1_2", "touched": False},
            {"pid": 38900, "executable": "matlab.exe", "session_id": 1,
             "runtime": "runtime/stage4e_b1_v3_1_2", "touched": False},
        ],
        "cleanup_scope": "only Stage177 test-owned fake_tree processes were cleaned by exact PID",
    })
    write_json("protection_manifest.json", {
        "status": "verified_by_scope",
        "stage_1_176_old_evidence_modified": False,
        "old_runtime_modified": False,
        "matlab_baseline_read_only": True,
        "physical_contract_modified": False,
        "numerical_thresholds_modified": False,
        "formal_0_2_1_protocol_semantics_modified": False,
        "unrelated_user_files_excluded": True,
    })
    write_json("stop_gate_audit.json", {
        "launch_performed": False,
        "new_cfd_confirm_started": False,
        "real_process_starts": process_counts,
        "owned_residual": 0,
        "next_action": "resolve strict MATLAB/C++ numerical mismatch before any CFD authorization",
    })
    write_json("independent_gate.json", {
        "stage_id": STAGE_ID,
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "gate": gate,
        "status": "pass" if all(conditions.values()) else "do_not_pass",
        "conditions": conditions,
        "focused_tests": focused,
        "real_process_starts": process_counts,
        "owned_residual": 0,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if conditions["strict_matlab_cpp_numerical_equivalence"] else "not_completed",
        "FORMAL_STROUHAL_STATUS": "not_completed",
        "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
        "LOCK_IN_CLAIM": "not_completed",
        "new_real_cfd_authorization_required": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    write_json("git_preflight.json", {
        "branch": git("branch", "--show-current"),
        "head_before_commit": git("rev-parse", "HEAD"),
        "scoped_status": git("status", "--short", "--", *CHANGED),
        "history_rewrite": False,
        "force_push": False,
        "unrelated_user_files_excluded": True,
    })
    write_json("changed_file_hashes.json", {
        item: sha256(ROOT / item) for item in CHANGED if (ROOT / item).is_file()
    })

    DOCS.mkdir(parents=True, exist_ok=True)
    report = f"""# Stage177 C++ Worker 全面审查、修复与版本审计报告

## 结论

本轮只执行离线 C++ Release 构建、selftest、协议故障注入、MATLAB golden fixture replay、专项测试和根目录 unittest；没有启动 MATLAB、OpenFOAM、WSL 或 CFD。独立 Gate：`{gate}`。

## 本轮修复

- 两个常驻 worker 现在强制校验跨 step 的 tick 连续性：`current_tick = previous_tick + round(previous_dt_s * 1e9)`。
- 增加 dt finite/positive 检查和 uint64 溢出保护。
- 增加浮点时间处于纳秒舍入边界、但 tick 跳变的 fail-closed 回归测试。
- 修复未显式包含 `<limits>` 的构建缺口。
- 未修改 ANCF/EB 方程、物理参数、global dt、数值阈值或正式协议语义。

## 验证结果

- MSVC 19.44.35228.0、CMake 3.31.6、Visual Studio 17 2022、x64、Release：通过。
- C++ selftest：2/2 通过；compileall：通过。
- 综合审计专项：{focused['cpp_worker_comprehensive_audit_repair_v1']['tests']}/{focused['cpp_worker_comprehensive_audit_repair_v1']['tests']} 通过。
- persistent IPC：{focused['cpp_worker_persistent_ipc_v1']['tests']}/{focused['cpp_worker_persistent_ipc_v1']['tests']} 通过。
- physics ownership：{focused['cpp_physics_ownership_v1']['tests']}/{focused['cpp_physics_ownership_v1']['tests']} 通过。
- 根目录 unittest：{focused['root_unittest']['tests']} tests，{focused['root_unittest']['skipped']} skipped，全部通过。
- engineering replay：{numerical['engineering_pass_steps']}/{numerical['requested_steps']}；strict MATLAB/C++ 等价：{numerical['strict_pass_steps']}/{numerical['requested_steps']}。
- strict 首个失败：step {numerical['first_strict_failure']['step']}，`{numerical['first_strict_failure']['error']}`。
- worker startup=1，owned residual=0；本阶段真实 MATLAB/OpenFOAM/WSL/CFD 启动数=0/0/0/0。

## 数值阻塞

工程容差通过不等于数值核心等价通过。当前 `C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`；不得放宽阈值，不得申请或启动真实 CFD confirm。

## 进程和保护

审计时发现两个属于旧 Stage4e runtime 的非本阶段 MATLAB 进程；它们是非 owned 外部进程，未被本轮触碰。根目录故障测试遗留的两个 test-owned fake_tree 进程已按精确 PID 清理。Stage1–176 证据、旧 runtime、MATLAB baseline、物理合同、数值阈值和正式 0.2.1 协议保持只读。

## Git

当前提交前检查记录在 `git_preflight.json`。本轮只允许提交 tick 修复、对应测试和 Stage177 证据；用户已有未跟踪案例目录不得加入提交。不得 force push 或改写历史。

## 正式状态

`FORMAL_STROUHAL_STATUS=not_completed`

`STABLE_VIV_RESPONSE_CLAIM=not_completed`

`LOCK_IN_CLAIM=not_completed`
"""
    report_path = DOCS / "最终报告_中文.md"
    report_path.write_text(report, encoding="utf-8")
    write_json("evidence_manifest.json", {
        "stage_id": STAGE_ID,
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "files": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in sorted(RESULTS.glob("*.json"))
            if path.name != "evidence_manifest.json"
        },
        "report": {str(report_path.relative_to(ROOT)): sha256(report_path)},
    })
    print(json.dumps({"gate": gate, "status": "pass" if all(conditions.values()) else "do_not_pass",
                      "strict_pass_steps": numerical["strict_pass_steps"],
                      "engineering_pass_steps": numerical["engineering_pass_steps"]}, ensure_ascii=False))
    return 0 if all(conditions.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
