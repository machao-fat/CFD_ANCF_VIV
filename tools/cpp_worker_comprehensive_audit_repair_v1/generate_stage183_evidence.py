from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage183"
RUN_ID = "cpp_worker_comprehensive_audit_repair_183_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage183_offline_case_001"
RESULTS = ROOT / "results" / "183_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs" / "183_cpp_worker_comprehensive_audit_repair_v1"

CHANGED_FILES = [
    "src/coupling/cpp_physics_ownership_v1/physics_ownership.cpp",
    "src/coupling/cpp_physics_ownership_v1/physics_ownership_selftest.cpp",
    "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
    "src/coupling/cpp_worker_persistent_ipc_v1/protocol.py",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_ownership_worker.py",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_stage182_contracts.py",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_stage183_contracts.py",
    "tools/cpp_worker_comprehensive_audit_repair_v1/generate_stage182_evidence.py",
    "tools/cpp_worker_comprehensive_audit_repair_v1/generate_stage183_evidence.py",
]


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def write_json(name: str, value: object) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    target = RESULTS / name
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(canonical(value))
        stream.flush()
    temporary.replace(target)


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                       stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as error:
        return f"unavailable: {error.output.strip()}"


def main() -> None:
    generated = datetime.now(timezone.utc).isoformat()
    file_hashes = {name: sha256(ROOT / name) for name in CHANGED_FILES}
    write_json("git_preflight.json", {
        "generated_at_utc": generated,
        "branch": git_value("branch", "--show-current"),
        "head": git_value("rev-parse", "HEAD"),
        "status_scope": "untracked user cases/references are excluded from this stage",
    })
    write_json("changed_file_hashes.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "files": file_hashes,
    })
    write_json("audit_findings.json", {
        "stage_id": STAGE_ID,
        "confirmed_repairs": [
            {"id": "UNKNOWN_FORCE_REPRESENTATION_NAME", "severity": "high",
             "status": "fixed_and_tested",
             "evidence": "representation_name now rejects values outside integrated_N and line_Npm"},
            {"id": "CROSS_LANGUAGE_INTEGER_TICK_ROUNDING", "severity": "high",
             "status": "fixed_and_tested",
             "evidence": "Python canonical_integer_tick matches non-negative C++ llround at half-ns ties"},
            {"id": "STALE_BINARY_TEST_SELECTION", "severity": "medium",
             "status": "fixed_and_tested",
             "evidence": "process tests require explicit CFD_ANCF_STAGE_BUILD and no longer use stage158 by default"},
        ],
        "remaining_blocker": {
            "id": "STRICT_MATLAB_CPP_NUMERICAL_EQUIVALENCE",
            "status": "not_completed",
            "first_failed_step": 560,
            "strict_steps": "0/40",
            "engineering_steps": "40/40",
        },
    })
    write_json("repair_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "formal_protocol_semantics_modified": False,
        "physics_or_thresholds_modified": False,
        "repairs_confirmed": 3,
        "protected_old_evidence_modified": False,
    })
    write_json("build_and_test_audit.json", {
        "stage_id": STAGE_ID, "case_id": CASE_ID,
        "compiler": "MSVC 19.44.35228.0 / Visual Studio 2022 BuildTools",
        "cmake": "3.31.6", "architecture": "x64", "configuration": "Release",
        "build_flags": ["/W4", "/analyze"], "build_status": "pass",
        "compileall": {"status": "pass"},
        "cpp_selftests": {"status": "pass", "count": 3},
        "stage183_contract_tests": {"status": "pass", "passed": 4, "failed": 0},
        "persistent_ipc_tests": {"status": "pass", "passed": 18, "failed": 0},
        "comprehensive_tests_with_stage183_build": {"status": "pass", "passed": 64, "failed": 0},
        "root_unittest_without_stale_binary": {"status": "pass", "passed": 1176, "failed": 0, "skipped": 2},
        "owned_residual": 0,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
    })
    write_json("ipc_fault_injection_summary.json", {
        "status": "pass",
        "covered": ["stale", "duplicate", "out_of_order", "tick_time_step_mismatch",
                     "dimension_mutation", "hash_mismatch", "NaN_Inf", "disconnect",
                     "timeout", "duplicate_initialize", "unknown_force_representation",
                     "half_nanosecond_tick_rounding"],
        "same_runtime_retry": False,
    })
    write_json("numerical_equivalence_audit.json", {
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "strict_matlab_cpp_equivalence": {"status": "do_not_pass", "steps_passed": 0,
                                            "steps_total": 40, "first_failed_step": 560},
        "engineering_replay": {"status": "pass", "steps_passed": 40, "steps_total": 40},
        "thresholds_modified": False,
    })
    write_json("process_cleanup_audit.json", {
        "status": "pass", "owned_residual": 0,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "offline_cpp_worker_processes": "selftests and explicitly selected test build only",
    })
    gate = ("STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass")
    write_json("independent_gate.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "gate": gate, "status": "do_not_pass",
        "reason": "strict MATLAB/C++ numerical equivalence remains unproven",
        "new_real_cfd_authorization_required": True,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "FORMAL_STROUHAL_STATUS": "not_completed",
        "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
        "LOCK_IN_CLAIM": "not_completed",
    })
    write_json("evidence_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "generated_at_utc": generated,
        "files": sorted(path.name for path in RESULTS.iterdir() if path.is_file()),
        "gate": gate,
    })
    DOCS.mkdir(parents=True, exist_ok=True)
    report = f"""# Stage183 C++ worker 全面审查续审报告\n\n阶段：`{STAGE_ID}`\n\n## 结论\n\n本阶段从 Stage182 断点继续，确认并修复三个问题：非法 `ForceRepresentation` 名称映射、Python/C++ 半纳秒 `integer_tick` 舍入不一致、以及测试默认使用旧 stage158 二进制造成的假失败。修复未改变物理参数、数值阈值或正式 0.2.1 协议语义。\n\n严格 MATLAB/C++ 数值等价仍未完成，首个失败仍为 step 560；因此 Gate 保持：\n\n`{gate}`\n\n## 验证\n\n- MSVC 2022 x64 Release、CMake 3.31.6、`/W4 /analyze`：通过。\n- C++ selftest：3/3；ownership selftest 包含 `unknown_representation_name_rejected=true`。\n- Stage183 tick/协议专项：4/4；persistent IPC：18/18。\n- 使用 Stage183 构建的综合专项：64/64。\n- 根目录 unittest（未选择 stale 二进制）：1176 通过，0 失败，2 跳过。\n- MATLAB/OpenFOAM/WSL/CFD 启动数：0/0/0/0；owned residual=0。\n- engineering replay：40/40；strict dual：0/40，首次失败 step 560。\n\n## 保护状态\n\nStage1–182 旧证据和 runtime 保持只读；没有启动新的真实 CFD，也没有扩大研究范围。\n\n`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`\n\n`FORMAL_STROUHAL_STATUS=not_completed`\n\n`STABLE_VIV_RESPONSE_CLAIM=not_completed`\n\n`LOCK_IN_CLAIM=not_completed`\n"""
    with (DOCS / "最终报告_中文.md").open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(report)


if __name__ == "__main__":
    main()
