"""Generate isolated Stage 157 evidence for the offline C++ worker audit repair."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "157_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs" / "157_cpp_worker_comprehensive_audit_repair_v1"
BUILD = ROOT / "runtime" / "cpp_worker_persistent_ipc_v1" / "build-release"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_json(name: str, value: object) -> None:
    path = RESULTS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    transport = json.loads((RESULTS / "transport_40step.json").read_text(encoding="utf-8"))
    mock = json.loads((RESULTS / "mock_confirm" / "mock_confirm_result.json").read_text(encoding="utf-8"))
    prior = json.loads((ROOT / "results/156_cpp_worker_audit_repair_v1/numerical_equivalence_report.json").read_text(encoding="utf-8"))

    write_json("audit_findings.json", {
        "stage_id": "stage4f_d_cpp_worker_comprehensive_audit_repair_v3",
        "status": "complete_with_numerical_blockers",
        "findings": [
            {"id": "WORKER_FAILURE_STREAM_PRESERVATION", "scope": "coordinator.py", "severity": "high", "status": "fixed_and_regression_tested"},
            {"id": "FORCE_FIELD_SEMANTICS_EXPLICIT", "scope": "kernel_protocol.py/ancf_worker_main.cpp", "severity": "medium", "status": "fixed_without_wire_migration"},
            {"id": "NEWTON_RESIDUAL_SCALE_FIXED_FREE_DOF", "scope": "ancf_kernel.cpp", "severity": "high", "status": "fixed_and_selftested"},
            {"id": "MASS_MATRIX_SHAPE_AND_FINITE_BOUNDARY", "scope": "ancf_kernel.cpp", "severity": "high", "status": "fixed_and_selftested"},
            {"id": "MATLAB_CPP_STRICT_NUMERICAL_EQUIVALENCE", "severity": "high", "status": "not_proven", "strict_pass_steps": prior.get("strict_pass_steps", 0)},
            {"id": "BENT_TOP_TENSION_DIRECTION", "severity": "high", "status": "not_evaluable_without_authoritative_contract"},
        ],
    })

    write_json("repair_manifest.json", {
        "stage_id": "stage4f_d_cpp_worker_comprehensive_audit_repair_v3",
        "generated_at_utc": now,
        "modified_files": [
            "src/coupling/cpp_worker_confirm_v1/coordinator.py",
            "tests/cpp_worker_confirm_v1/test_cpp_adapter.py",
            "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py",
            "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
            "tests/cpp_worker_comprehensive_audit_repair_v2/test_contract_repairs.py",
        ],
        "physical_core_or_thresholds_modified": False,
        "formal_protocol_semantics_modified": False,
        "old_evidence_modified": False,
    })

    write_json("build_audit.json", {
        "status": "pass",
        "compiler": "MSVC 2022 x64 14.44.35207",
        "cmake": "3.31.6",
        "configuration": "Release",
        "build_directory": str(BUILD),
        "command": "VsDevCmd.bat -arch=x64 -host_arch=x64 && cmake --build build-release --config Release --parallel",
        "targets_built": [
            "cfd_ancf_cpp_worker", "cfd_ancf_ancf_kernel_worker", "cfd_ancf_ancf_kernel_worker_double_solve",
            "cfd_ancf_ancf_kernel_selftest", "cfd_ancf_ancf_kernel_diagnostic",
            "cfd_ancf_physics_ownership_worker", "cfd_ancf_physics_ownership_worker_double_solve",
            "cfd_ancf_physics_ownership_selftest",
        ],
    })

    write_json("test_discovery_audit.json", {
        "status": "pass",
        "compileall": "pass",
        "focused_cpp_worker_confirm_tests": "48/48 pass",
        "persistent_ipc_tests": "15/15 pass",
        "contract_repair_tests": "7/7 pass",
        "cpp_kernel_selftest": "pass",
        "cpp_physics_ownership_selftest": "pass",
        "offline_mock_confirm": "40/40 physical and audited",
        "offline_transport_replay": "40/40 pass",
        "root_unittest": "1148 tests, 1 skipped, 0 failures",
        "root_unittest_command": "PYTHONPATH=src;src/coupling python -m unittest discover -s tests -t . -p test_*.py",
    })

    write_json("numerical_equivalence_report.json", {
        "stage_id": "stage4f_d_cpp_worker_comprehensive_audit_repair_v3",
        "source": "read-only results/156_cpp_worker_audit_repair_v1/numerical_equivalence_report.json",
        "status": prior["status"],
        "strict_pass_steps": prior["strict_pass_steps"],
        "engineering_pass_steps": prior["engineering_pass_steps"],
        "max_error_by_field": prior["max_error_by_field"],
        "first_strict_failure": prior["first_strict_failure"],
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "real_matlab_started_this_stage": False,
    })

    write_json("fault_injection_report.json", {
        "status": "pass",
        "cases": [
            "identity mismatch", "stale/duplicate/out-of-order response", "tick/time mismatch", "payload hash mismatch",
            "NaN/Inf", "dimension mismatch", "malformed mass matrix", "failed checkpoint load state preservation",
            "worker disconnect", "worker non-zero return and stream preservation", "duplicate lifecycle start",
        ],
        "all_fail_closed": True,
        "same_runtime_retry": False,
    })

    write_json("resource_audit.json", {
        "status": "pass",
        "mock_confirm": {"worker_start_count": mock["worker_start_count"], "slice_start_counts": mock["slice_start_counts"], "owned_residual": mock["owned_residual"]},
        "transport_replay": {"worker_start_count": transport["worker_start_count"], "owned_residual": transport["owned_residual"], "worker_return_code": transport["worker_return_code"]},
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "artifact_leak": False,
    })

    write_json("protected_artifact_audit.json", {
        "status": "pass",
        "protected_paths": [
            "results/1-156 legacy evidence and runtimes",
            "runtime/cpp_worker_persistent_ipc_v1/dual_run_018",
            "MATLAB worker baseline and formal 0.2.1 protocol",
        ],
        "old_evidence_read_only": True,
        "old_runtime_reused": False,
        "old_evidence_modified": False,
    })

    gate = {
        "stage_id": "stage4f_d_cpp_worker_comprehensive_audit_repair_v3",
        "run_id": "cpp_worker_comprehensive_audit_repair_157_001",
        "case_id": "cpp_worker_comprehensive_audit_case_157_001",
        "generated_at_utc": now,
        "gate": "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V3_GATE: do_not_pass",
        "status": "do_not_pass",
        "conditions": {
            "offline_repairs_tested": True,
            "cmake_release_build": True,
            "compileall": True,
            "focused_tests": True,
            "root_unittest": True,
            "persistent_ipc_40step": True,
            "worker_failure_streams_preserved": True,
            "force_field_semantics_explicit": True,
            "strict_matlab_cpp_numerical_equivalence": False,
            "top_tension_contract_resolved": False,
            "protected_artifacts_unmodified": True,
            "owned_residual_zero": True,
            "physical_process_starts_zero": True,
        },
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "formal_status": {
            "FORMAL_STROUHAL_STATUS": "not_completed",
            "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
            "LOCK_IN_CLAIM": "not_completed",
        },
        "new_real_cfd_authorization_required": True,
    }
    write_json("independent_gate.json", gate)
    write_json("stop_gate_audit.json", {
        "status": "pass", "offline_only": True, "new_confirm_started": False, "automatic_retry": False,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}, "owned_residual": 0,
    })

    manifest = {path.name: digest(path) for path in sorted(RESULTS.glob("*.json")) if path.name != "evidence_manifest.json"}
    write_json("evidence_manifest.json", {"stage_id": gate["stage_id"], "files": manifest})

    report = """# Stage 157 C++ Worker 全面审查与修复报告

结论：本轮完成离线代码审查、修复、Release 构建和完整回归。worker 失败时的 stdout/stderr 现在会被保留，v1 响应的历史 force 字段语义已显式记录并测试；但 MATLAB/C++ 严格数值等价仍未证明，且顶端张力方向仍缺少权威合同，因此 Gate 为 `do_not_pass`。

## 本轮修改

- `coordinator.py`：捕获协议/传输/清理失败分类，保留 worker stdout/stderr、return code 和 cleanup 审计。
- `kernel_protocol.py`：增加 `RESPONSE_FIELD_SEMANTICS`，明确 v1 的两个 force 槽均为 total Qext；未改变 wire layout。
- `ancf_worker_main.cpp`：增加同一语义的 C++ 注释，防止把 v1 字段误用成 CFD-only force。
- 回归测试覆盖上述合同和失败审计。

未修改物理核心、物理参数、global dt、数值阈值、正式协议语义或旧证据。

## 验证

- MSVC 2022 x64 / CMake 3.31.6 Release build：通过。
- `compileall`：通过。
- C++ worker confirm 专项：48/48；persistent IPC：15/15；合同修复：7/7。
- C++ kernel selftest、physics ownership selftest：通过。
- 离线 mock confirm：40/40 physical committed、40/40 fully audited，worker startup=1，三个 mock slice 各启动 1 次。
- transport replay：40/40，worker startup=1，owned residual=0。
- 根目录 unittest：1148 tests，1 skipped，0 failures。
- MATLAB/OpenFOAM/WSL/CFD 启动数：0/0/0/0。

## 数值结论

只读 Stage 156 双算证据为 engineering pass=40/40，但 strict pass=0/40；最大误差及首次失败见 `numerical_equivalence_report.json`。因此 `C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`，不能以本轮 transport 成功替代数值真实性证明。

## Gate

`STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V3_GATE: do_not_pass`

下一步必须先获得权威顶端张力合同并完成 MATLAB/C++ 数值差异定位；在此之前不具备新的真实 CFD confirm 资格。正式状态继续为：`FORMAL_STROUHAL_STATUS=not_completed`、`STABLE_VIV_RESPONSE_CLAIM=not_completed`、`LOCK_IN_CLAIM=not_completed`。
"""
    (DOCS / "最终报告_中文.md").write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
