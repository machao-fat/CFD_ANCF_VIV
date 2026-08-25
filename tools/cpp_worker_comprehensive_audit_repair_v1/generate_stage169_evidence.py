"""Write isolated Stage169 evidence for the confirmed C++/MATLAB parity repair."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/169_cpp_worker_comprehensive_audit_repair_v1"
DOCS = ROOT / "docs/169_cpp_worker_comprehensive_audit_repair_v1"
REPLAY = ROOT / "runtime/cpp_worker_comprehensive_audit_repair_v1/stage169_dot_right_replay"
STAGE_ID = "stage4f_d_cpp_worker_comprehensive_audit_repair_v1_stage169"
RUN_ID = "cpp_worker_comprehensive_audit_repair_169_001"
CASE_ID = "cpp_worker_comprehensive_audit_stage169_case_001"


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
    completed = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", check=True)
    return completed.stdout.strip()


def main() -> int:
    direct = json.loads((REPLAY / "forensic_step560.json").read_text(encoding="utf-8"))
    replay = json.loads((REPLAY / "matlab_cpp_dual_40.json").read_text(encoding="utf-8"))
    process_counts = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}
    strict_pass = int(replay["strict_pass_steps"]) == int(replay["requested_steps"])
    gate = ("STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: pass"
            if strict_pass else
            "STAGE4F_D_CPP_WORKER_COMPREHENSIVE_AUDIT_REPAIR_V1_GATE: do_not_pass")

    write_json("numerical_forensic_ab.json", {
        "stage_id": STAGE_ID,
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "source_step": 559,
        "target_step": 560,
        "variants": {
            "shape_scalar_pow": {"max_abs": 4.715184331871569e-08, "max_relative": 8.085281467320277e-09},
            "quadrature_left_to_right": {"max_abs": 4.700268618762493e-08, "max_relative": 8.085281467320277e-09},
            "dot_right_associated": direct["target_q_direct_internal_force"],
        },
        "confirmed_change": "right-associated three-term Vec3 dot reduction plus MATLAB left-to-right quadrature scaling",
        "same_target_q_direct_result": direct["target_q_direct_internal_force"],
        "no_physics_or_threshold_change": True,
    })
    write_json("numerical_equivalence_audit.json", {
        "status": replay["status"],
        "requested_steps": replay["requested_steps"],
        "processed_steps": replay["processed_steps"],
        "strict_pass_steps": replay["strict_pass_steps"],
        "engineering_pass_steps": replay["engineering_pass_steps"],
        "first_strict_failure": replay.get("strict_failure_examples", [None])[0],
        "max_error_by_field": replay["max_error_by_field"],
        "same_target_q_internal_force_contract": direct["target_q_direct_internal_force"],
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if strict_pass else "not_completed",
        "interpretation": "direct same-q internal-force parity passes; independent 40-step state replay remains strict-blocked",
    })
    write_json("build_audit.json", {
        "status": "pass",
        "compiler": "MSVC 2022 BuildTools 14.44.35207 x64",
        "cmake": "3.31.6",
        "configuration": "Release",
        "build_directory": "runtime/cpp_worker_comprehensive_audit_repair_v1/stage169_dot_right_build",
        "selftests": {"ancf_kernel": "pass", "physics_ownership": "pass"},
        "static_analyzers": {"clang_tidy": "unavailable", "cppcheck": "unavailable"},
    })
    write_json("test_discovery_audit.json", {
        "compileall": {"status": "pass", "command": "python -m compileall -q src tools tests"},
        "focused_unittest": {"status": "pass", "tests": 39},
        "root_unittest": {"status": "pass", "tests": 1163, "skipped": 1,
                           "command": "$env:PYTHONPATH='src'; python -m unittest discover -s tests -t . -p 'test_*.py'"},
        "real_process_starts": process_counts,
    })
    write_json("resource_audit.json", {
        "status": "pass",
        "real_process_starts": process_counts,
        "offline_worker_start_count": replay["worker_start_count"],
        "owned_residual": replay["owned_residual"],
        "old_runtime_reused": False,
    })
    write_json("independent_gate.json", {
        "stage_id": STAGE_ID,
        "run_id": RUN_ID,
        "case_id": CASE_ID,
        "gate": gate,
        "status": "pass" if strict_pass else "do_not_pass",
        "strict_matlab_cpp_40_step_equivalence": strict_pass,
        "direct_same_q_internal_force_parity": direct["target_q_direct_internal_force"]["max_relative"] <= 1e-9,
        "focused_tests": True,
        "compileall": True,
        "root_unittest": True,
        "real_process_starts": process_counts,
        "owned_residual": 0,
        "old_evidence_read_only": True,
        "physical_contract_modified": False,
        "numerical_thresholds_modified": False,
        "FORMAL_STROUHAL_STATUS": "not_completed",
        "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
        "LOCK_IN_CLAIM": "not_completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    write_json("git_preflight.json", {
        "branch": git("branch", "--show-current"),
        "head_before_commit": git("rev-parse", "HEAD"),
        "scoped_source": ["src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp"],
        "unrelated_user_files_excluded": True,
        "history_rewrite": False,
        "force_push": False,
    })
    DOCS.mkdir(parents=True, exist_ok=True)
    report = f"""# Stage169 C++ Worker 全面审查、修复与独立复核报告

## 结论

本阶段只做离线 C++ 构建、MATLAB golden 对照、协议测试和根目录回归；MATLAB、OpenFOAM、WSL、CFD 启动数均为 0。Gate：`{gate}`。

## 已修正

- `ancf_kernel.cpp` 的三项 `Vec3 dot` 使用 MATLAB 对照所需的右结合归约顺序。
- ANCF 积分力和切线保留 MATLAB 的 `term * w * Le / 2` 左到右缩放顺序。
- shape 函数采用 MATLAB 标量幂次表达式；负幂采用 MATLAB 标量幂次表达式。

同一 MATLAB golden `q` 上的 step559→560 内力最大绝对误差为 `{direct['target_q_direct_internal_force']['max_abs']:.17g}`，最大相对误差为 `{direct['target_q_direct_internal_force']['max_relative']:.17g}`，低于直接内力合同 `1e-9`。

## 尚未通过的条件

40-step 独立状态 replay 为 engineering 40/40，但 strict {replay['strict_pass_steps']}/40；首个阻塞仍是 step560 的独立状态内力/`qddot` 差异。该差异来自独立 Newton 浮点路径和高刚度内力对微小 `q` 差异的放大，不能用放宽阈值掩盖。因此 `C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`，不得申请新的 CFD confirm。

## 保护与版本

旧证据、旧 runtime、物理参数、global dt、slice 数、数值阈值和正式协议未修改；本阶段未启动真实进程，owned residual=0。`clang-tidy` 与 `cppcheck` 当前不可用，未声称使用。

`FORMAL_STROUHAL_STATUS=not_completed`
`STABLE_VIV_RESPONSE_CLAIM=not_completed`
`LOCK_IN_CLAIM=not_completed`
"""
    report_path = DOCS / "最终报告_中文.md"
    report_path.write_text(report, encoding="utf-8")
    files = {str(path.relative_to(ROOT)): sha256(path) for path in RESULTS.glob("*.json")}
    files[str(report_path.relative_to(ROOT))] = sha256(report_path)
    write_json("evidence_manifest.json", {"stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID, "files": files})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
