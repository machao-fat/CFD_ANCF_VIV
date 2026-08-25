"""Record the bounded Stage185 MATLAB trace failure without retrying MATLAB."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/185_cpp_worker_matlab_intermediate_trace_repair_v1"
DOCS = ROOT / "docs/185_cpp_worker_matlab_intermediate_trace_repair_v1"


def write(name: str, value: object) -> None:
    (RESULTS / name).write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    stage = "stage4f_d_cpp_worker_matlab_intermediate_trace_repair_v1"
    run = "cpp_worker_matlab_intermediate_trace_001"
    case = "cpp_worker_matlab_intermediate_trace_case_001"
    contract = {
        "stage_id": stage,
        "run_id": run,
        "case_id": case,
        "source_step": 559,
        "target_step": 560,
        "source_time_s": 2.2075,
        "target_time_s": 2.20875,
        "source_integer_tick": 2207500000,
        "target_integer_tick": 2208750000,
        "global_dt_s": 0.00125,
        "required_gauss_order": 5,
        "required_max_newton": 50,
        "required_case_local_bridge_step": 1,
        "protected_contract_changed": False,
        "status": "mismatch_audit_required",
    }
    write("numerical_contract_manifest.json", contract)
    write("matlab_step560_trace_manifest.json", {
        "stage_id": stage, "status": "do_not_pass",
        "matlab_export_attempted": True, "matlab_start_count": 1,
        "export_script": "tools/cpp_worker_matlab_intermediate_trace_repair_v1/export_step560_matlab_intermediate_trace.m",
        "failure_classification": "source_checkpoint_not_found",
        "raw_error": "expected exactly one matching source, found 0",
        "candidate_committed_mat_count": 20,
        "matching_step559_contract_count": 0,
        "trace_written": False,
        "matlab_process_cleanup": "completed",
    })
    write("cpp_step560_trace_manifest.json", {
        "stage_id": stage, "status": "not_started_after_matlab_export_failure",
        "cpp_trace_generated": False,
        "reason": "verification sequence stopped at MATLAB trace export",
        "old_stage184_trace_reused": False,
    })
    write("step560_first_difference_audit.json", {
        "stage_id": stage,
        "status": "not_evaluable",
        "first_difference": None,
        "reason": "MATLAB intermediate trace unavailable; no C++ comparison performed",
        "strict_matlab_cpp_steps_passed": 0,
        "strict_matlab_cpp_steps_total": 40,
        "old_evidence_reference": "Stage184 remains do_not_pass and read-only",
    })
    write("internal_force_forensic_comparison.json", {
        "stage_id": stage, "status": "not_evaluable",
        "comparison_performed": False,
        "reason": "no same-schema MATLAB Gauss trace",
        "old_stage184_observation": {
            "internal_force_abs_error": 4.866160452365875e-07,
            "internal_force_relative_error": 4.891825378743019e-08,
            "source": "read-only Stage184 evidence",
        },
    })
    write("numerical_repair_manifest.json", {
        "stage_id": stage, "status": "not_started",
        "first_difference_confirmed": False,
        "cpp_files_modified": [],
        "physics_parameters_modified": False,
        "thresholds_modified": False,
        "matlab_reference_modified": False,
    })
    replay = {
        "stage_id": stage, "status": "not_started_after_fail_closed_export",
        "steps_total": 40, "steps_processed": 0,
        "worker_start_count": 0, "owned_residual": 0,
        "reason": "verification sequence stopped before replay",
    }
    write("replay_10step_audit.json", {**replay, "steps_total": 10})
    write("replay_40step_audit.json", replay)
    write("test_and_build_audit.json", {
        "stage_id": stage, "status": "not_started_after_fail_closed_export",
        "compileall": "not_run", "cmake_release": "not_run",
        "w4": "not_run", "analyze": "not_run",
        "specialized_tests": "not_run", "root_unittest": "not_run",
    })
    write("process_cleanup_audit.json", {
        "stage_id": stage,
        "matlab_start_count": 1,
        "matlab_os_processes_cleaned": [32604, 38900],
        "openfoam_start_count": 0, "wsl_start_count": 0, "cfd_start_count": 0,
        "owned_worker_start_count": 0, "owned_residual": 0,
        "cleanup_status": "pass",
        "unowned_existing_processes_untouched": True,
    })
    write("independent_gate.json", {
        "stage_id": stage, "run_id": run, "case_id": case,
        "gate": "STAGE4F_D_CPP_WORKER_MATLAB_INTERMEDIATE_TRACE_REPAIR_V1_GATE: do_not_pass",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "reason": "MATLAB source checkpoint for exact step559 contract is unavailable; first difference cannot be established",
        "real_process_starts": {"MATLAB": 1, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "old_evidence_modified": False,
        "old_runtime_reused": False,
        "cfd_started": False,
    })
    report = f"""# Stage185 MATLAB 中间量 trace 修复报告

## 结论

MATLAB trace 导出未成功，阶段按 fail-closed 停止。唯一一次 MATLAB 启动执行了独立导出脚本，脚本在源 checkpoint 合同检查处返回：`expected exactly one matching source, found 0`。

仓库只读扫描发现 20 个 `committed.mat`，其状态为 step 0--3 或 step 20；没有 step 559、time=2.2075 s、Gauss=5、max_newton=50、dt=0.00125 s 的可加载 MATLAB state。因此不能用旧 JSON fixture 冒充 MATLAB 中间量，也没有执行 C++ 对照或代码修复。

## 进程与保护

- MATLAB 启动：1 次（batch 外壳产生的两个本次进程已清理）。
- OpenFOAM=0，WSL=0，CFD=0；owned residual=0。
- Stage1--184 旧证据、旧 runtime、MATLAB 参考实现、物理参数和阈值未修改。
- Stage184 的 `do_not_pass` 状态保持不变。

## Gate

`STAGE4F_D_CPP_WORKER_MATLAB_INTERMEDIATE_TRACE_REPAIR_V1_GATE: do_not_pass`

`C++_ANCF_NUMERICAL_CORE_STATUS=not_completed`

需要新的合法 step559 MATLAB source checkpoint（或新的明确 MATLAB 导出授权/输入合同）后，才能再次进行同 schema 中间量导出。当前不具备 CFD confirm 申请资格。
"""
    (DOCS / "report_zh.md").write_text(report, encoding="utf-8")
    files = sorted(p for p in RESULTS.iterdir() if p.is_file())
    hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    write("changed_file_hashes.json", {"algorithm": "SHA256", "stage_id": stage, "files": hashes})
    print(json.dumps({"status": "do_not_pass", "gate": "STAGE4F_D_CPP_WORKER_MATLAB_INTERMEDIATE_TRACE_REPAIR_V1_GATE: do_not_pass", "files": len(files)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
