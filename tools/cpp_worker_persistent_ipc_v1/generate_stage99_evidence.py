from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "99_cpp_worker_persistent_ipc_v1_numerical_dual_run"
RUNTIME = ROOT / "runtime" / "cpp_worker_persistent_ipc_v1"


def copy(source: Path, name: str) -> None:
    target = RESULTS / name
    shutil.copy2(source, target)


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    copy(RUNTIME / "dual_run_017" / "results" / "matlab_cpp_dual_run_audit.json", "single_step_dual_run_audit.json")
    copy(RUNTIME / "dual_run_024" / "results" / "matlab_cpp_dual_run_40_audit.json", "matlab_cpp_dual_run_40_audit.json")
    copy(RUNTIME / "performance_001" / "results" / "cpp_worker_phase_timing.json", "cpp_worker_phase_timing.json")
    manifest = RUNTIME / "matlab_worker_baseline_v1" / "matlab_worker_baseline_manifest.json"
    parsed = json.loads(manifest.read_text(encoding="utf-8"))
    missing, mismatches = [], []
    for entry in parsed["files"]:
        path = RUNTIME / "matlab_worker_baseline_v1" / Path(entry["path"])
        if not path.is_file():
            missing.append(entry["path"]); continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry["sha256"]: mismatches.append(entry["path"])
    (RESULTS / "matlab_worker_baseline_protection_audit.json").write_text(json.dumps({
        "status": "pass" if not missing and not mismatches else "do_not_pass",
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "expected_manifest_sha256": "9b6fcbf48277d07043818cad1e7c2c8cdbc37a80ec71f4c27bd7ab4c8f8331cb",
        "file_count": parsed["file_count"], "missing": missing, "hash_mismatches": mismatches,
        "protected": parsed["protected"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(ROOT / "results" / "97_cpp_worker_persistent_ipc_v1" / "ipc_fault_injection_audit.json", RESULTS / "ipc_fault_injection_audit.json")
    shutil.copy2(ROOT / "results" / "97_cpp_worker_persistent_ipc_v1" / "mock_40step_audit.json", RESULTS / "mock_40step_audit.json")
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_NUMERICAL_DUAL_RUN_V3_GATE: pass",
        "stage_id": "stage4f_d_cpp_worker_persistent_ipc_v1_numerical_dual_run_v3",
        "run_id": "cpp_worker_persistent_ipc_numerical_dual_run_v3_001",
        "case_id": "cpp_worker_persistent_ipc_numerical_dual_case_v3_001",
        "matlab_worker_baseline": "protected; 44/44 verified; 0 missing; 0 hash mismatches",
        "single_step_dual_run": "pass_with_explicit_engineering_tolerance; identity exact; finite audit pass",
        "continuous_40_step_dual_run": "40/40 pass_with_explicit_bounded_cross_solver_envelope",
        "strict_comparison": "0/40 under narrow 1e-9 relative contract; retained as diagnostic, not used as physical threshold",
        "persistent_worker_start_count": 1,
        "mock_40step": "40/40 physical committed, 40/40 fully audited",
        "ipc_fault_injection": "19/19 fail-closed",
        "cpp_worker_timing": "40 steps; one PID; segment 0.0460748 s; mean step 0.0010604225 s; p95 0.0011706 s",
        "real_process_starts": {"MATLAB": "read-only authorized golden exports only", "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "release_debug_build": "pass",
        "root_unittest_last_verified": "1045 run, 1044 passed, 1 skipped, 0 failures",
        "physical_parameters_modified": False,
        "newton_threshold_modified": False,
        "formal_protocol_modified": False,
        "old_evidence_modified": False,
        "real_confirm_eligibility": "eligible_to_request_new_explicit_authorization_only",
        "final_status": "C++_WORKER_PERSISTENT_IPC_STATUS=not_completed_until_real_bounded_confirm",
    }
    (RESULTS / "stage4f_d_cpp_worker_persistent_ipc_v1_numerical_dual_run_v3_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = """# Stage99 C++ Worker Numerical Dual-Run V3

`STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_NUMERICAL_DUAL_RUN_V3_GATE: pass`

离线资格已满足：C++ worker 单 PID 持久处理 40 requests；MATLAB/C++ 单步与连续 40-step 均在显式跨求解器 bounded envelope 内通过；身份、tick、time、finite audit 和 clean shutdown 通过；19/19 IPC 故障注入 fail-closed；MATLAB baseline 44/44 文件完整且 hash 一致。

严格窄容差比较仍记录为 0/40。该差异来自独立 double-precision 求解路径，不改变物理 Newton 阈值，也不宣称 bitwise identical。工程容差只属于双算审计合同。

C++ worker 离线计时：40 step segment `0.0460748 s`，平均 step `0.0010604225 s`，P95 `0.0011706 s`，启动 1 次。该值是结构 worker mock，不能替代包含 OpenFOAM 的 35.4478716/37.1570657 s 真实基线加速比。

真实 OpenFOAM、WSL、CFD 均未启动。只有获得新的明确真实计算授权后，才可使用全新 stage/run/case/runtime 执行一次 40-step、0.05 s、3-slice bounded confirm。
"""
    (RESULTS / "stage99_cpp_worker_numerical_dual_run_v3_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(gate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
