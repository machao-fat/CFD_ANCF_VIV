from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "98_cpp_worker_persistent_ipc_v1_dual_run"
DUAL = ROOT / "runtime" / "cpp_worker_persistent_ipc_v1" / "dual_run_018"
ONE_STEP = ROOT / "runtime" / "cpp_worker_persistent_ipc_v1" / "dual_run_017" / "results" / "matlab_cpp_dual_run_audit.json"


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    for source, name in ((ONE_STEP, "single_step_dual_run_audit.json"),
                         (DUAL / "results" / "matlab_cpp_dual_run_40_audit.json", "dual_run_40_fail_closed_audit.json")):
        shutil.copy2(source, RESULTS / name)
    (RESULTS / "dual_run_40_drift_diagnostic.json").write_text(json.dumps({
        "status": "diagnostic_only_not_gate",
        "steps_processed": 40,
        "worker_start_count": 1,
        "worker_return_code": 0,
        "owned_residual": 0,
        "max_abs_drift": {"q": 6.78133835765593e-05, "qdot": 0.002736663704228093,
                          "qddot": 0.46495722486383784, "internal_force": 432.7226739825237},
        "sample_steps": {
            "1": {"q": 2.2886073782618643e-08, "qdot": 3.661771805357761e-05, "qddot": 0.05858834888572417},
            "10": {"q": 3.877232243182371e-06, "qdot": 0.0006537883266766187, "qddot": 0.18408392110647043},
            "40": {"q": 6.78133835765593e-05, "qdot": 0.002736663704228093, "qddot": 0.46495722486383784},
        },
        "interpretation": "persistent transport and identity continuity passed; continuous MATLAB/C++ numerical equivalence remains incomplete",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_DUAL_RUN_V2_GATE: do_not_pass",
        "stage_id": "stage4f_d_cpp_worker_persistent_ipc_v1_dual_run_v2",
        "run_id": "cpp_worker_persistent_ipc_dual_run_v2_001",
        "case_id": "cpp_worker_persistent_ipc_dual_case_v2_001",
        "persistent_ipc": "pass",
        "slice_position_mapping": "pass; MATLAB s_ref_m propagated in binary model schema",
        "single_step_dual_run": "pass_with_engineering_tolerance; strict_contract_not_pass",
        "continuous_40_step_dual_run": "do_not_pass; fail_closed_at_step_2",
        "diagnostic_40_step": "40 processed by one C++ PID; drift exceeds current dual-run contract",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "real_process_starts": {"MATLAB": "authorized_direct_probe_and_golden_exports_only", "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "root_unittest": "1045 run, 1044 passed, 1 skipped, 0 failures",
        "specialized_cpp_tests": "14 passed",
        "release_debug_build": "pass",
        "protected_old_evidence": "unchanged/read-only",
        "next_step": "repair and revalidate continuous MATLAB/C++ numerical equivalence; no CFD authorization",
    }
    (RESULTS / "stage4f_d_cpp_worker_persistent_ipc_v1_dual_run_v2_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = """# Stage98 C++ Worker Persistent IPC Dual-Run V2

## 结论

`STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_DUAL_RUN_V2_GATE: do_not_pass`

持久二进制 IPC、单 PID 连续请求、身份映射和精确 `s_ref_m` 已通过离线验证。单步 MATLAB/C++ 结果只在明确记录的工程容差下通过，严格双算合同仍未通过。连续 40 step 诊断中 C++ worker 处理了 40 个请求且 clean shutdown，但 fail-closed 运行在第 2 步停止；独立诊断显示 step 40 的最大漂移为 q=`6.78e-5`、qdot=`2.74e-3`、qddot=`4.65e-1`、内力=`432.7 N`。

## 保护与进程

Stage 1–96、MATLAB worker baseline、confirm025 和旧 runtime 未修改。当前阶段只读 MATLAB 探针/golden 导出由用户授权执行；OpenFOAM、WSL、CFD 启动数均为 0。C++ worker owned residual 为 0。

## 下一步

继续修复 C++/MATLAB 数值一致性并重新执行独立双算。在该 Gate 通过并获得新的明确授权前，不得启动真实 CFD、Stage75、E5-B/E5-C 或任何扩大范围的研究计算。
"""
    (RESULTS / "stage98_cpp_worker_persistent_ipc_dual_run_v2_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(gate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
