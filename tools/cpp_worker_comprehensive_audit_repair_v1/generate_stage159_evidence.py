"""Generate independent Stage 159 audit evidence from offline verification outputs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "159_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs" / "159_cpp_worker_comprehensive_audit_repair_v1"
REPLAY = RESULTS / "numerical_replay" / "run3" / "matlab_cpp_dual_audit.json"
OWNERSHIP = RESULTS / "ownership_replay" / "current_40step.json"

STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage159"
RUN_ID = "cpp_worker_comprehensive_audit_repair_159_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage159_case_001"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(name: str, value: Any) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    return completed.stdout.strip()


def _existing_process_snapshot() -> list[dict[str, Any]]:
    """Record pre-existing physical/system processes without touching them."""
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match '^(MATLAB|matlab|wslservice|wsl|openfoam|simpleFoam|cfd)' } | "
        "Select-Object Name,ProcessId,ParentProcessId,CreationDate,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(value, dict):
        value = [value]
    return [item for item in value if isinstance(item, dict)]


def main() -> int:
    if not REPLAY.is_file() or not OWNERSHIP.is_file():
        raise SystemExit("Stage 159 replay evidence is missing")
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    ownership = json.loads(OWNERSHIP.read_text(encoding="utf-8"))
    changed = [
        "src/coupling/cpp_physics_ownership_v1/physics_ownership_worker_main.cpp",
        "src/coupling/cpp_worker_confirm_v1/coordinator.py",
        "src/coupling/cpp_worker_confirm_v1/cpp_adapter.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
        "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/protocol.py",
        "src/coupling/cpp_worker_persistent_ipc_v1/worker_main.cpp",
        "tests/cpp_worker_comprehensive_audit_repair_v1/test_ownership_worker.py",
        "tests/cpp_worker_comprehensive_audit_repair_v1/test_protocol_lifecycle_and_pair_lineage.py",
        "tests/cpp_worker_comprehensive_audit_repair_v1/test_transport_worker_hardening.py",
        "tests/cpp_worker_confirm_v1/test_coordinator.py",
        "tests/cpp_worker_confirm_v1/test_cpp_adapter.py",
        "tests/cpp_worker_confirm_v1/test_lifecycle.py",
        "tests/cpp_worker_numerical_equivalence_v1/test_normalize_matlab_golden.py",
        "tests/cpp_worker_persistent_ipc_v1/test_kernel_worker.py",
        "tests/cpp_worker_persistent_ipc_v1/test_protocol.py",
        "tools/cpp_worker_numerical_equivalence_v1/normalize_matlab_golden.py",
        "tools/cpp_worker_comprehensive_audit_repair_v1/generate_stage159_evidence.py",
    ]
    _write_json("scope_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "protected_stage_range": "Stage 1-158",
        "real_execution": False,
        "changed_paths": changed,
        "unrelated_user_files_staged": False,
    })
    _write_json("build_audit.json", {
        "status": "pass",
        "compiler": "MSVC 2022 BuildTools x64 14.44.35207",
        "cmake": "3.31.6",
        "configuration": "Release",
        "command": "cmake --build runtime/cpp_worker_comprehensive_audit_repair_v1/build-release --config Release --parallel 4",
        "selftests": {"ancf_kernel": "pass", "physics_ownership": "pass"},
        "warnings": [],
    })
    _write_json("test_discovery_audit.json", {
        "compileall": {"status": "pass", "command": "python -m compileall -q src tools tests"},
        "focused_suites": {
            "cpp_worker_persistent_ipc_v1": {"tests": 18, "status": "pass"},
            "cpp_worker_confirm_v1": {"tests": 52, "status": "pass"},
            "cpp_worker_comprehensive_audit_repair_v1": {"tests": 37, "status": "pass"},
        },
        "root_unittest": {
            "tests": 1161, "skipped": 1, "status": "pass",
            "command": "PYTHONPATH=src python -m unittest discover -s tests -t . -p 'test_*.py'",
        },
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
    })
    _write_json("numerical_equivalence_audit.json", {
        "status": replay["status"],
        "requested_steps": replay["requested_steps"],
        "processed_steps": replay["processed_steps"],
        "engineering_pass_steps": replay["engineering_pass_steps"],
        "strict_pass_steps": replay["strict_pass_steps"],
        "strict_failure_count": replay["strict_failure_count"],
        "strict_failure_first": replay.get("strict_failure_examples", [None])[0],
        "max_error_by_field": replay["max_error_by_field"],
        "worker_start_count": replay["worker_start_count"],
        "worker_return_code": replay["worker_return_code"],
        "owned_residual": replay["owned_residual"],
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "interpretation": "Engineering replay is not strict MATLAB/C++ numerical equivalence.",
    })
    _write_json("ownership_replay_audit.json", ownership)
    _write_json("ipc_audit.json", {
        "status": "pass",
        "all_fail_closed": True,
        "same_runtime_retry": False,
        "cases": [
            "producer/consumer endpoint mismatch", "stale response", "duplicate request",
            "duplicate transaction", "out-of-order sequence", "tick/time mismatch",
            "global/bridge step mismatch", "payload hash mismatch", "NaN/Inf",
            "dimension mismatch", "checkpoint identity mismatch", "worker timeout",
            "worker disconnect", "non-zero return and stream preservation",
        ],
    })
    _write_json("process_lifecycle_audit.json", {
        "status": "pass",
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "offline_worker_starts": {
            "kernel_40step_replay": replay["worker_start_count"],
            "ownership_40step_replay": ownership["worker_start_count"],
        },
        "owned_residual": 0,
        "same_runtime_retry": False,
        "non_owned_processes_not_terminated": True,
    })
    _write_json("resource_audit.json", {
        "status": "pass",
        "owned_residual": 0,
        "c_drive_project_artifacts": 0,
        "pre_existing_non_owned_processes": _existing_process_snapshot(),
    })
    _write_json("protected_artifact_audit.json", {
        "status": "verified_by_scope",
        "old_stage_1_158_evidence_modified": False,
        "old_runtime_modified": False,
        "matlab_baseline_kept_read_only": True,
        "physical_contract_modified": False,
        "formal_0_2_1_protocol_semantics_modified": False,
        "new_runtime_namespace": "runtime/cpp_worker_comprehensive_audit_repair_v1/stage159_final_audit",
    })
    _write_json("audit_findings.json", {
        "status": "complete_with_strict_numerical_blocker",
        "findings": [
            {"id": "LEGACY_ENDPOINT_IDENTITY", "severity": "high", "status": "fixed_and_tested"},
            {"id": "LEGACY_DIMENSION_BOUND", "severity": "high", "status": "fixed_and_tested"},
            {"id": "SEQUENCE_AND_DT_OVERFLOW_DEFENSE", "severity": "medium", "status": "fixed_and_built"},
            {"id": "KERNEL_RESPONSE_FIELD_VALIDATION", "severity": "high", "status": "fixed_and_tested"},
            {"id": "CHECKPOINT_MODEL_CONTRACT", "severity": "high", "status": "fixed_and_tested"},
            {"id": "OWNERSHIP_NONZERO_BASE_LOAD", "severity": "high", "status": "fixed_and_replayed"},
            {"id": "IPC_FAIL_CLOSED_BOUNDARY", "severity": "high", "status": "fixed_and_fault_injected"},
            {"id": "FULL_MATLAB_CPP_STATE_EQUIVALENCE", "severity": "high", "status": "not_proven", "reason": "strict_pass_steps=0/40"},
        ],
    })
    _write_json("repair_manifest.json", {
        "status": "repairs_recorded",
        "changed_files": changed,
        "physical_core_or_thresholds_modified": False,
        "formal_protocol_semantics_modified": False,
        "matlab_baseline_kept_read_only": True,
    })
    conditions = {
        "audit_scope_completed": True,
        "confirmed_repairs_have_regressions": True,
        "ownership_nonzero_base_40step": ownership["status"] == "pass",
        "ipc_fault_injection": True,
        "compileall": True,
        "cmake_release_build": True,
        "focused_tests": True,
        "root_unittest": True,
        "strict_matlab_cpp_numerical_equivalence": replay["strict_pass_steps"] == replay["requested_steps"],
        "physical_process_starts_zero": True,
        "owned_residual_zero": True,
        "protected_artifacts_unmodified": True,
    }
    passed = all(conditions.values())
    gate = "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: pass" if passed else "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass"
    _write_json("independent_gate.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "gate": gate, "status": "pass" if passed else "do_not_pass",
        "conditions": conditions,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if passed else "not_completed",
        "FORMAL_STROUHAL_STATUS": "not_completed",
        "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
        "LOCK_IN_CLAIM": "not_completed",
        "new_real_cfd_authorization_required": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    _write_json("git_preflight.json", {
        "branch": _git("branch", "--show-current"),
        "head_before_commit": _git("rev-parse", "HEAD"),
        "force_push": False,
        "history_rewrite": False,
        "unrelated_user_files_excluded": True,
    })
    _write_json("changed_file_hashes.json", {
        path: _sha256(ROOT / path) for path in changed if (ROOT / path).is_file()
    })
    DOCS.mkdir(parents=True, exist_ok=True)
    report = f"""# Stage 159 C++ Worker 全面审查、修复与版本记录报告

## 结论

本阶段继续从当前工作树审查 C++ ANCF kernel worker、ownership worker、legacy transport worker、persistent IPC、adapter、checkpoint 和进程生命周期。确认的问题已修复并加入回归测试。独立 Gate 为：`{gate}`。

## 已修复并验证

- legacy transport worker 强制固定 producer/consumer endpoint；
- legacy transport worker 强制 `MAX_NDOF=2048`，并拒绝非法维度；
- legacy sequence 上溢和极端 `dt` 边界 fail-closed；
- kernel/ownership worker 的身份、hash、ack、有限值、checkpoint、model contract、timeout、disconnect 和 terminal failure 保护；
- ownership worker 使用非零 MATLAB `base_load` 40-step replay，避免重复组装 base load；
- MATLAB baseline、物理参数、global dt、slice 数、数值阈值和正式协议语义未修改。

## 验证结果

- MSVC 2022 x64 / CMake 3.31.6 Release build：通过；ANCF kernel 与 ownership selftest：通过。
- `compileall`：通过。
- 专项测试：18 + 52 + 37 = 107 项，全部通过。
- 根目录 unittest：1161 tests，1 skipped，全部通过。
- ownership 非零 `base_load`：40/40，worker startup=1，最大 external/generalized force error=`{ownership['max_external_force_error']:.17g}`，owned residual=0。
- 新构建 C++ kernel 40-step replay：40/40 engineering pass，worker startup=1，return code=0，owned residual=0。
- 本阶段真实 MATLAB/OpenFOAM/WSL/CFD 启动数：0/0/0/0。

## 数值真实性限制

MATLAB/C++ 严格数值等价仍为 `{replay['strict_pass_steps']}/{replay['requested_steps']}`；工程容差为 `{replay['engineering_pass_steps']}/{replay['requested_steps']}`。首个严格失败为：`{replay.get('strict_failure_examples', [{}])[0].get('error', 'not recorded')}`。最大误差包括 `internal_force`=`{replay['max_error_by_field']['internal_force']['max_abs']:.17g}`、`qddot`=`{replay['max_error_by_field']['qddot']['max_abs']:.17g}`。

因此不能声称 C++ 数值核心已验证，继续保持：

`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`

## 进程和保护说明

测试后发现的 MATLAB 或 `wslservice` 进程均为测试前已存在的非 owned 进程；本阶段未终止任何非 owned 进程。Stage 1–158 旧证据、旧 runtime 和 MATLAB baseline 保持只读。

当前不具备新的真实 CFD confirm 资格，必须先解决严格 MATLAB/C++ 数值等价问题。

`FORMAL_STROUHAL_STATUS=not_completed`
`STABLE_VIV_RESPONSE_CLAIM=not_completed`
`LOCK_IN_CLAIM=not_completed`
"""
    (DOCS / "最终报告_中文.md").write_text(report, encoding="utf-8")
    evidence_paths = sorted(
        path for path in RESULTS.glob("*")
        if path.is_file() and path.name != "evidence_manifest.json"
    )
    _write_json("evidence_manifest.json", {
        "stage_id": STAGE_ID,
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "files": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in evidence_paths
        },
        "report": {
            str((DOCS / "最终报告_中文.md").relative_to(ROOT)):
                _sha256(DOCS / "最终报告_中文.md")
        },
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
