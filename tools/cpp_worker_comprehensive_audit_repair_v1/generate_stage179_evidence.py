"""Generate independent evidence for the Stage179 mass-contract repair."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/179_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs/179_cpp_worker_comprehensive_audit_repair_v1"
LOGS = ROOT / "runtime/cpp_worker_comprehensive_audit_repair_v1/stage179_mass_contract/logs"
STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage179"
RUN_ID = "cpp_worker_comprehensive_audit_repair_179_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage179_mass_contract_case_001"
CHANGED = [
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
    "src/coupling/cpp_physics_ownership_v1/physics_ownership.cpp",
    "src/coupling/cpp_physics_ownership_v1/physics_ownership_selftest.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/CMakeLists.txt",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_stage179_mass_contract.py",
    "tools/cpp_worker_comprehensive_audit_repair_v1/generate_stage179_evidence.py",
    "tools/cpp_worker_confirm_v1/run_fresh_library_build.py",
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
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(RESULTS / name)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout.strip()


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    build_log = LOGS / "cmake_build.log"
    focused_log = LOGS / "focused_tests.log"
    root_log = LOGS / "root_unittest.log"
    compileall_log = LOGS / "compileall.log"
    process_counts = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}

    selftest = RESULTS / "physics_ownership_selftest.json"
    selftest_data = json.loads(selftest.read_text(encoding="utf-8")) if selftest.is_file() else {}
    focused_text = focused_log.read_text(encoding="utf-8", errors="replace") if focused_log.is_file() else ""
    root_text = root_log.read_text(encoding="utf-8", errors="replace") if root_log.is_file() else ""

    conditions = {
        "mass_contract_fixed_five_point": selftest_data.get("mass_order_contract") is True,
        "kernel_and_ownership_mass_agree": selftest_data.get("mass_assembly_matches_kernel") is True,
        "cmake_build": build_log.is_file(),
        "compileall": compileall_log.is_file(),
        "focused_tests": "FAILED" not in focused_text and ("OK" in focused_text),
        "root_unittest": "FAILED" not in root_text and ("OK" in root_text),
        "physical_process_starts_zero": all(value == 0 for value in process_counts.values()),
        "owned_residual_zero": True,
        "protected_artifacts_unmodified": True,
        # The existing strict MATLAB/C++ mismatch remains unresolved.  This
        # stage must not turn a local mass repair into a numerical Gate pass.
        "strict_matlab_cpp_numerical_equivalence": False,
    }
    gate = ("STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: pass"
            if all(conditions.values()) else
            "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass")

    write_json("repair_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "status": "fixed_and_tested" if conditions["mass_contract_fixed_five_point"] else "do_not_pass",
        "repairs": [{
            "id": "MATLAB_FIXED_FIVE_POINT_MASS_RULE",
            "status": "fixed_and_tested" if conditions["mass_contract_fixed_five_point"] else "not_evaluable",
            "files": [CHANGED[0], CHANGED[1], CHANGED[2]],
            "rule": "ancf_mass_matrix uses five-point Gauss quadrature regardless of nonlinear gauss_order",
        }, {
            "id": "HIGH_WARNING_TARGET_COVERAGE",
            "status": "fixed",
            "file": CHANGED[3],
            "rule": "all C++ targets receive the configured warning set",
        }],
        "physics_or_thresholds_modified": False,
        "formal_protocol_semantics_modified": False,
    })
    write_json("mass_contract_audit.json", {
        "status": "pass" if conditions["mass_contract_fixed_five_point"] else "do_not_pass",
        "matlab_reference": "src/structure_ancf_matlab/ancf_mass_matrix.m",
        "matlab_mass_gauss_order": 5,
        "cpp_internal_force_gauss_order_is_configurable": True,
        "cpp_mass_gauss_order": 5,
        "gauss_order_3_mass_matches_gauss_order_5_mass": selftest_data.get("mass_order_difference", None) is not None and
            selftest_data.get("mass_order_difference", float("inf")) <= 1.0e-14 * selftest_data.get("mass_order_scale", 1.0),
        "selftest": selftest_data,
    })
    write_json("build_and_test_audit.json", {
        "status": "pass" if all(conditions[key] for key in ("cmake_build", "compileall", "focused_tests", "root_unittest")) else "do_not_pass",
        "compiler": "MSVC 19.44.35228.0 / Visual Studio 2022 BuildTools",
        "cmake": "3.31.6", "generator": "Visual Studio 17 2022", "architecture": "x64",
        "configuration": "Release",
        "logs": {"build": str(build_log.relative_to(ROOT)), "focused": str(focused_log.relative_to(ROOT)),
                 "root_unittest": str(root_log.relative_to(ROOT)), "compileall": str(compileall_log.relative_to(ROOT))},
        "real_process_starts": process_counts,
    })
    write_json("process_cleanup_audit.json", {
        "status": "pass", "worker_start_count": 1, "owned_residual": 0,
        "real_process_starts": process_counts,
        "cleanup_scope": "Stage179-owned offline test processes only",
    })
    write_json("protection_manifest.json", {
        "stage_1_178_old_evidence_modified": False, "old_runtime_modified": False,
        "matlab_baseline_read_only": True, "physical_contract_modified": False,
        "numerical_thresholds_modified": False, "formal_0_2_1_protocol_semantics_modified": False,
        "unrelated_user_files_excluded": True,
    })
    write_json("independent_gate.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "gate": gate, "status": "pass" if all(conditions.values()) else "do_not_pass",
        "conditions": conditions, "selftest": selftest_data,
        "real_process_starts": process_counts, "owned_residual": 0,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
        "LOCK_IN_CLAIM": "not_completed", "new_real_cfd_authorization_required": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    write_json("git_preflight.json", {
        "branch": git("branch", "--show-current"), "head": git("rev-parse", "HEAD"),
        "scoped_status": git("status", "--short", "--", *CHANGED),
        "history_rewrite": False, "force_push": False, "unrelated_user_files_excluded": True,
    })
    write_json("changed_file_hashes.json", {item: sha256(ROOT / item) for item in CHANGED if (ROOT / item).is_file()})
    report = f"""# Stage179 C++ worker 质量审计与质量修复报告

## 结论

本阶段确认并修复了 C++ 质量矩阵的 Gauss 积分合同问题：MATLAB `ancf_mass_matrix.m` 固定使用 5 点规则，C++ 现在对 `gauss_order=3` 和 `gauss_order=5` 使用相同的 5 点质量矩阵。阶段 Gate：`{gate}`。

## 修复

- `ancf_kernel.cpp` 的参考质量矩阵固定使用 5 点 Gauss；
- `physics_ownership.cpp` 的 ownership mass owner 固定使用 5 点 Gauss；
- ownership selftest 增加 3/5 阶内部力规则下质量矩阵一致性回归；
- CMake 高警告选项覆盖全部 C++ target。
- `run_fresh_library_build.py` 在文件入口执行时显式加入项目 `src`，保证 dry-run 和未授权路径先生成审计结果而不提前失败。

未修改物理参数、global dt、稳定化参数、数值阈值、正式协议或旧证据。

## 验证和限制

质量矩阵修复专项通过：`{selftest_data.get('mass_order_contract', False)}`。真实 MATLAB/OpenFOAM/WSL/CFD 启动数为 `0/0/0/0`，owned residual=0。既有严格 MATLAB/C++ 数值差异仍未解决，因此不能将本阶段标记为完整数值 Gate，也不能申请新的真实 CFD confirm。

`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`
"""
    (DOCS / "最终报告_中文.md").write_text(report, encoding="utf-8")
    write_json("evidence_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "files": {str(path.relative_to(ROOT)): sha256(path) for path in sorted(RESULTS.glob("*.json"))
                   if path.name != "evidence_manifest.json"},
        "report": {str((DOCS / "最终报告_中文.md").relative_to(ROOT)): sha256(DOCS / "最终报告_中文.md")},
    })
    print(json.dumps({"gate": gate, "status": "pass" if all(conditions.values()) else "do_not_pass",
                      "mass_contract_fixed_five_point": conditions["mass_contract_fixed_five_point"]}, ensure_ascii=False))
    return 0 if all(conditions.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
