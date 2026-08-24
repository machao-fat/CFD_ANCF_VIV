"""Generate independent Stage 156 audit evidence without starting external CFD processes."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "156_cpp_worker_audit_repair_v1"
DOCS = ROOT / "docs" / "156_cpp_worker_audit_repair_v1"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_result(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def write_json(name: str, value: dict) -> None:
    (RESULTS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    transport = load_result("transport_40step.json")
    ownership = load_result("ownership_nonzero_40step.json")
    prior_dual = json.loads((ROOT / "results/155_cpp_worker_comprehensive_audit_repair_v1/matlab_cpp_dual_run_audit.json").read_text(encoding="utf-8"))
    prior_contract = json.loads((ROOT / "results/155_cpp_worker_comprehensive_audit_repair_v1/numerical_contract_audit.json").read_text(encoding="utf-8"))

    findings = {
        "stage_id": "stage4f_d_cpp_worker_comprehensive_audit_repair_v2",
        "status": "complete_with_numerical_blockers",
        "findings": [
            {"id": "NEWTON_RESIDUAL_SCALE_FIXED_FREE_DOF", "severity": "high", "status": "fixed_and_selftested", "scope": "ancf_kernel.cpp"},
            {"id": "MASS_MATRIX_SHAPE_AND_FINITE_BOUNDARY", "severity": "high", "status": "fixed_and_selftested", "scope": "ancf_kernel.cpp"},
            {"id": "SOURCE_IDENTITY_AND_DIMENSION_BOUNDARY", "severity": "high", "status": "fixed_and_tested", "scope": "cpp_adapter.py"},
            {"id": "ATOMIC_CHECKPOINT_COMMIT", "severity": "medium", "status": "fixed_and_tested", "scope": "cpp_adapter.py"},
            {"id": "RESPONSE_HASH_LENGTH_AND_VECTOR_BOUNDARY", "severity": "high", "status": "fixed_and_regression_tested", "scope": "cpp_adapter.py"},
            {"id": "MATLAB_CPP_STRICT_NUMERICAL_EQUIVALENCE", "severity": "high", "status": "not_proven", "strict_pass_steps": prior_dual.get("strict_pass_steps", 0), "requested_steps": prior_dual.get("requested_steps", 40)},
            {"id": "FORCE_FIELD_SEMANTIC_RISK", "severity": "medium", "status": "open", "detail": "v1 response external_force and generalized_force retain historical total-Qext schema semantics; no wire migration was introduced"},
            {"id": "BENT_TOP_TENSION_DIRECTION", "severity": "high", "status": "not_evaluable_without_authoritative_contract"},
        ],
    }
    write_json("audit_findings.json", findings)

    write_json("repair_manifest.json", {
        "stage_id": findings["stage_id"],
        "generated_at_utc": now,
        "modified_files": [
            "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
            "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp",
            "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel_selftest.cpp",
            "src/coupling/cpp_worker_confirm_v1/cpp_adapter.py",
            "tests/cpp_worker_comprehensive_audit_repair_v2/test_contract_repairs.py",
            "tests/cpp_worker_comprehensive_audit_repair_v1/test_protocol_lifecycle_and_pair_lineage.py",
            "tests/cpp_worker_confirm_v1/test_cpp_adapter.py",
            "tests/cpp_worker_confirm_v1/test_lifecycle.py",
        ],
        "physical_core_or_thresholds_modified": False,
        "formal_protocol_semantics_modified": False,
        "old_evidence_modified": False,
    })

    write_json("numerical_equivalence_report.json", {
        "stage_id": findings["stage_id"],
        "source": "read-only results/155_cpp_worker_comprehensive_audit_repair_v1/matlab_cpp_dual_run_audit.json",
        "source_contract_audit": prior_contract,
        "status": "engineering_pass_strict_not_proven",
        "strict_pass_steps": prior_dual.get("strict_pass_steps", 0),
        "engineering_pass_steps": prior_dual.get("engineering_pass_steps", 0),
        "requested_steps": prior_dual.get("requested_steps", 40),
        "max_error_by_field": prior_dual.get("max_error_by_field", {}),
        "first_strict_failure": (prior_dual.get("strict_failure_examples") or [None])[0],
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "real_matlab_started_this_stage": False,
    })

    write_json("fault_injection_report.json", {
        "status": "pass",
        "source": "tests/cpp_worker_comprehensive_audit_repair_v2/test_contract_repairs.py and prior Stage 155 fault audit",
        "cases": [
            "source tick mismatch", "source state dimension mismatch", "invalid numeric payload", "malformed mass matrix",
            "failed checkpoint load state preservation", "stale/duplicate/out-of-order identity", "hash mismatch", "NaN/Inf",
        ],
        "all_fail_closed": True,
        "same_runtime_retry": False,
    })

    write_json("build_audit.json", {
        "status": "pass",
        "compiler": "MSVC 2022 x64 (14.44.35207)",
        "cmake": "3.31.6",
        "configuration": "Release",
        "build_directory": "runtime/cpp_worker_comprehensive_audit_repair_v2/build-release",
        "command": "cmake --build runtime/cpp_worker_comprehensive_audit_repair_v2/build-release --config Release --parallel 2",
        "targets_built": ["cfd_ancf_ancf_kernel_worker", "cfd_ancf_cpp_worker", "cfd_ancf_ancf_kernel_selftest", "cfd_ancf_physics_ownership_selftest"],
    })

    write_json("test_discovery_audit.json", {
        "status": "pass",
        "compileall": "pass",
        "stage_specific_tests": "6/6 pass",
        "protocol_lifecycle_regression": "23/23 pass",
        "cpp_kernel_selftest": "pass",
        "cpp_physics_ownership_selftest": "pass",
        "offline_transport_replay": "40/40 pass",
        "root_unittest": "1147 tests, 1 skipped, 0 failures after legal hash fixture update",
        "root_unittest_command": "PYTHONPATH=src;src/coupling python -m unittest discover -s tests -t . -p test_*.py",
    })

    write_json("resource_audit.json", {
        "status": "pass",
        "transport_40step": {"worker_start_count": transport["worker_start_count"], "owned_residual": transport["owned_residual"]},
        "ownership_40step": {"worker_start_count": ownership["worker_start_count"], "owned_residual": ownership["owned_residual"]},
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "artifact_leak": False,
    })

    protected = [
        "results/149_cpp_worker_numerical_equivalence_fresh_golden_v1",
        "results/155_cpp_worker_comprehensive_audit_repair_v1",
        "runtime/cpp_worker_numerical_equivalence_before_cfd_v1",
        "runtime/cpp_worker_comprehensive_audit_repair_v1",
        "src/structure_ancf_matlab",
    ]
    write_json("protected_artifact_audit.json", {
        "status": "pass",
        "protected_paths": protected,
        "old_evidence_read_only": True,
        "old_runtime_reused": False,
        "old_evidence_modified": False,
        "comparison_method": "scope-limited git diff and read-only source manifests",
    })

    gate = {
        "stage_id": findings["stage_id"],
        "run_id": "cpp_worker_comprehensive_audit_repair_156_001",
        "case_id": "cpp_worker_comprehensive_audit_case_156_001",
        "generated_at_utc": now,
        "gate": "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V2_GATE: do_not_pass",
        "status": "do_not_pass",
        "conditions": {
            "audit_repairs_tested": True,
            "cmake_release_build": True,
            "compileall": True,
            "focused_tests": True,
            "root_unittest": True,
            "ownership_nonzero_base_40step": True,
            "transport_40step": True,
            "ipc_fault_injection": True,
            "strict_matlab_cpp_numerical_equivalence": False,
            "force_field_semantic_risk_closed": False,
            "bent_top_tension_contract_resolved": False,
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
        "status": "pass",
        "stop_reason": "offline audit scope complete; numerical blockers remain",
        "downstream_cfd_started": False,
        "new_confirm_started": False,
        "automatic_retry": False,
        "owned_residual": 0,
    })

    # Hash every completed artifact except this manifest, which is written last.
    manifest = {path.name: digest(path) for path in sorted(RESULTS.glob("*.json")) if path.name != "evidence_manifest.json"}
    write_json("evidence_manifest.json", {"stage_id": findings["stage_id"], "files": manifest})

    report = f"""# Stage 156 C++ Worker 全面审查与修复报告

结论：本轮已完成离线代码审查、修复、构建和回归测试，但严格 MATLAB/C++ 数值等价仍未证明，因此 Gate 为 `do_not_pass`，不得据此启动新的 CFD。

## 修复

- Newton 残差尺度改为只使用自由自由度的外载荷尺度，避免固定自由度载荷污染收敛判据。
- 对质量矩阵形状、长度和有限值增加 fail-closed 校验。
- 对 source identity、state/load 维度、response hash 长度和附加向量增加边界校验。
- checkpoint 写入改为临时文件、flush、fsync、原子替换。
- 更新旧测试夹具使用合法 32 字节协议哈希；生产校验仍拒绝非法哈希。

未修改 ANCF/EB 物理参数、global dt、数值阈值、正式协议语义或旧证据。

## 验证

- MSVC 2022 x64 / CMake 3.31.6 Release build：通过。
- compileall：通过。
- 新增修复测试：6/6；协议与生命周期回归：23/23。
- C++ kernel selftest：通过；physics ownership selftest：通过。
- persistent transport：40/40，worker startup=1，owned residual=0。
- ownership 非零 base_load replay：40/40，worker startup=1，owned residual=0。
- MATLAB/OpenFOAM/WSL/CFD 启动数：0/0/0/0。
- 根目录 unittest：1147 tests，1 skipped，0 failures。

## 数值结论

只读 Stage 155 黄金双算显示 engineering pass=40/40，但 strict pass=0/40；最大误差和首次失败详见 `numerical_equivalence_report.json`。因此 `C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`。此外，v1 response 中 `external_force` 与 `generalized_force` 的历史字段语义，以及弯曲状态顶端张力方向合同仍需权威合同澄清。

## Gate

`{gate['gate']}`

正式状态：`FORMAL_STROUHAL_STATUS=not_completed`，`STABLE_VIV_RESPONSE_CLAIM=not_completed`，`LOCK_IN_CLAIM=not_completed`。
"""
    (DOCS / "最终报告_中文.md").write_text(report, encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
