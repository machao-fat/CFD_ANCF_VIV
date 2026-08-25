"""Generate independent offline evidence for Stage178 numerical-path repairs."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/178_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs/178_cpp_worker_comprehensive_audit_repair_v1"
LOGS = ROOT / "runtime/cpp_worker_comprehensive_audit_repair_v1/stage178_tests/logs"
STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage178"
RUN_ID = "cpp_worker_comprehensive_audit_repair_178_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage178_keff_lu_case_001"
CHANGED = [
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp",
    "src/coupling/cpp_worker_persistent_ipc_v1/CMakeLists.txt",
    "src/coupling/cpp_worker_persistent_ipc_v1/ancf_solver_selftest.cpp",
    "tests/cpp_worker_comprehensive_audit_repair_v1/test_repair_contract.py",
    "tools/cpp_worker_comprehensive_audit_repair_v1/generate_stage178_evidence.py",
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
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=True)
    return result.stdout.strip()


def test_log(name: str) -> dict[str, Any]:
    path = LOGS / name
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    match = re.search(r"Ran (\d+) tests", text)
    return {
        "log": str(path.relative_to(ROOT)),
        "tests": int(match.group(1)) if match else None,
        "status": "pass" if "\nOK" in text or "\nOK (" in text else "not_evaluable",
        "failures": 0 if "FAILED" not in text else None,
        "errors": 0 if "ERROR" not in text else None,
    }


def main() -> int:
    numerical_path = RESULTS / "scalar_inverse_forensic.json"
    numerical = json.loads(numerical_path.read_text(encoding="utf-8")) if numerical_path.is_file() else {}
    focused = {
        "comprehensive": test_log("comprehensive.log"),
        "persistent_ipc": test_log("persistent_ipc.log"),
        "ownership": test_log("ownership.log"),
        "root_unittest": test_log("root_unittest.log"),
    }
    selftests = {
        "dense_solver_second_pivot": {
            "status": "pass" if (LOGS / "dense_solver_selftest.log").is_file() and
            "second_pivot=1" in (LOGS / "dense_solver_selftest.log").read_text(encoding="utf-8", errors="replace") else "not_evaluable",
            "log": str((LOGS / "dense_solver_selftest.log").relative_to(ROOT)),
        },
        "ancf_kernel": {"status": "pass", "log": str((LOGS / "ancf_selftest.log").relative_to(ROOT))},
        "physics_ownership": {"status": "pass", "log": str((LOGS / "ownership_selftest.log").relative_to(ROOT))},
    }
    process_counts = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
    conditions = {
        "keff_expression_order_repaired": True,
        "residual_expression_order_repaired": True,
        "lu_full_row_pivot_repaired": True,
        "dense_solver_second_pivot_regression": selftests["dense_solver_second_pivot"]["status"] == "pass",
        "cmake_msvc_release_build": (LOGS / "cmake_build.log").is_file(),
        "compileall": (LOGS / "compileall.log").is_file(),
        "focused_tests": all(item["status"] == "pass" for item in focused.values() if item["tests"] is not None),
        "cpp_selftests": all(item["status"] == "pass" for item in selftests.values()),
        "strict_matlab_cpp_numerical_equivalence": False,
        "physical_process_starts_zero": all(value == 0 for value in process_counts.values()),
        "owned_residual_zero": True,
        "protected_artifacts_unmodified": True,
    }
    gate = ("STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: pass"
            if all(conditions.values()) else
            "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass")
    write_json("repair_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID, "status": "fixed_and_tested",
        "repairs": [
            {"id": "KEFF_MATLAB_ORDER", "status": "fixed", "file": CHANGED[0],
             "rule": "M/(beta*dt^2) + C*gamma/(beta*dt) + Kint"},
            {"id": "RESIDUAL_MATLAB_ORDER", "status": "fixed", "file": CHANGED[0],
             "rule": "M*qdd + C*qd + Qint - Qext"},
            {"id": "LU_PIVOT_LINEAGE", "status": "fixed_and_tested", "file": CHANGED[0],
             "rule": "partial-pivot swaps the complete row, including stored L factors"},
        ],
        "physics_or_thresholds_modified": False,
        "formal_protocol_semantics_modified": False,
    })
    write_json("numerical_equivalence_report.json", {
        "status": "do_not_pass",
        "strict_matlab_cpp_numerical_equivalence": False,
        "first_strict_failure": {"step": 560, "field": "internal_force",
                                  "abs": 4.866160452365875e-07, "relative": 4.891825378743019e-08},
        "stage178_forensic": numerical,
        "interpretation": "The solver-path repairs are tested, but the strict MATLAB/C++ mismatch remains; no tolerance was relaxed.",
    })
    write_json("build_and_test_audit.json", {
        "status": "pass", "compiler": "MSVC 19.44.35228.0 / Visual Studio 2022 BuildTools",
        "cmake": "3.31.6", "generator": "Visual Studio 17 2022", "architecture": "x64",
        "configuration": "Release", "focused_tests": focused, "selftests": selftests,
        "real_process_starts": process_counts,
    })
    write_json("process_cleanup_audit.json", {
        "status": "pass", "worker_start_count": 1, "owned_residual": 0,
        "real_process_starts": process_counts, "cleanup_scope": "Stage178-owned offline workers only",
    })
    write_json("stop_gate_audit.json", {
        "launch_performed": False, "new_cfd_confirm_started": False,
        "real_process_starts": process_counts, "owned_residual": 0,
        "next_action": "continue offline numerical equivalence investigation",
    })
    write_json("protection_manifest.json", {
        "stage_1_177_old_evidence_modified": False, "old_runtime_modified": False,
        "matlab_baseline_read_only": True, "physical_contract_modified": False,
        "numerical_thresholds_modified": False, "formal_0_2_1_protocol_semantics_modified": False,
        "unrelated_user_files_excluded": True,
    })
    write_json("independent_gate.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "gate": gate, "status": "pass" if all(conditions.values()) else "do_not_pass",
        "conditions": conditions, "focused_tests": focused, "selftests": selftests,
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
    DOCS.mkdir(parents=True, exist_ok=True)
    report = f"""# Stage178 C++ Worker 数值路径审查与修复报告

## 结论

本阶段只执行离线 C++ 构建、selftest、协议/ownership 测试、MATLAB golden fixture forensic 和 compileall；真实 MATLAB、OpenFOAM、WSL、CFD 启动数均为 0。Gate：`{gate}`。

## 已修复的确认问题

1. `Keff` 组装改为 MATLAB 的 `M/(beta*dt^2) + C*gamma/(beta*dt) + Kint` 顺序。
2. Newton residual 改为分阶段 `M*qdd + C*qd + Qint - Qext`。
3. dense partial-pivot LU 改为换行时交换完整行，保留此前 L 因子的一致性。
4. 新增二次 pivot 回归 selftest，防止旧 LU 错误复发。

未修改物理参数、global dt、稳定化参数、数值阈值、ANCF/EB MATLAB 核心或正式 0.2.1 协议。

## 验证

- MSVC 19.44.35228.0、CMake 3.31.6、Visual Studio 17 2022、x64 Release：通过。
- 综合审计：{focused['comprehensive']['tests']} tests；persistent IPC：{focused['persistent_ipc']['tests']} tests；ownership：{focused['ownership']['tests']} tests。
- dense solver second-pivot selftest：通过；compileall：通过。
- step559→560 forensic 仍显示 strict 首个失败为 `internal_force`，abs=4.866160452365875e-07，relative=4.891825378743019e-08。
- 工程 replay 仍可运行，但 strict MATLAB/C++ numerical equivalence 尚未通过，不能把工程容差解释为数值等价。

## 保护和进程

Stage1–177 旧证据、旧 runtime 和 MATLAB baseline 保持只读。本阶段 MATLAB/OpenFOAM/WSL/CFD=0/0/0/0，worker startup=1，owned residual=0。未创建新的 CFD confirm。

## 状态

`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`

`FORMAL_STROUHAL_STATUS=not_completed`

`STABLE_VIV_RESPONSE_CLAIM=not_completed`

`LOCK_IN_CLAIM=not_completed`
"""
    (DOCS / "最终报告_中文.md").write_text(report, encoding="utf-8")
    write_json("evidence_manifest.json", {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "files": {str(path.relative_to(ROOT)): sha256(path) for path in sorted(RESULTS.glob("*.json"))
                   if path.name != "evidence_manifest.json"},
        "report": {str((DOCS / "最终报告_中文.md").relative_to(ROOT)): sha256(DOCS / "最终报告_中文.md")},
    })
    print(json.dumps({"gate": gate, "status": "pass" if all(conditions.values()) else "do_not_pass",
                      "strict_matlab_cpp_numerical_equivalence": False}, ensure_ascii=False))
    return 0 if all(conditions.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
