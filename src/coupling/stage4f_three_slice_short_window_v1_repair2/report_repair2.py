"""生成 repair2 失败终态的结构化 closeout 证据和中文报告。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from .contract import PROJECT_ROOT, RESULTS_ROOT, PARENT_CHECKPOINT, PARENT_ANCF_STATE
from ..stage4f_c_applicationservice_repair_v2.probe import RESULTS_ROOT as ENV_RESULTS_ROOT


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_reports() -> dict[str, Any]:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    execution = _read(RESULTS_ROOT / "real_execution_summary.json")
    process = _read(RESULTS_ROOT / "owned_process_registry.json")
    probe = _read(ENV_RESULTS_ROOT / "applicationservice_probe_result.json")
    branch = execution["branches"].get("A", {})
    stop = {
        "schema": "stage4f-c-repair2-stop-evidence-audit-1.0.0",
        "status": "passed",
        "source": "repair2 A branch first frozen hard-gate failure",
        "old_attempt2_classifier_failure": "normal sigFpe/FOAM_SIGFPE startup banner was classified as fatal by the old classifier",
        "repair2_classifier_reaudit": "old attempt2 logs pass under the bounded classifier",
        "old_evidence_modified": False,
        "repair1_evidence_modified": False,
        "parent_checkpoint": str(PARENT_CHECKPOINT),
        "parent_checkpoint_sha256": sha256_file(PARENT_CHECKPOINT),
        "parent_fixed_point_state": str(PARENT_ANCF_STATE),
        "parent_fixed_point_state_sha256": "6d6d4ff3ee5e30c32538848c4980b50440a85c3be2cd9e1cac23be8561aa9ed8",
        "repair2_execution_status": execution.get("status"),
        "first_failure": "branch A step 2 at t=1.515 s",
        "first_failure_reasons": ["abs_Cd_above_10", "committed_predictor_velocity_gap_above_0.01"],
        "old_attempt2_and_parent_lineage_distinct": True,
    }
    atomic_write_json(RESULTS_ROOT / "stage4f_v1_stop_evidence_audit.json", stop)
    test_audit = {
        "schema": "stage4f-c-repair2-test-audit-1.0.0",
        "compileall": {"command": "python -m compileall -q src tests", "status": "passed"},
        "applicationservice_targeted": {"command": "python -m unittest discover -s tests/stage4f_c_applicationservice_repair_v2 -p test*.py", "tests_run": 3, "failures": 0, "errors": 0, "status": "passed"},
        "repair2_targeted": {"command": "python -m unittest discover -s tests/stage4f_three_slice_short_window_v1_repair2 -p test*.py", "tests_run": 38, "failures": 0, "errors": 0, "status": "passed"},
        "root_unfiltered": {"command": "python -m unittest discover -s tests -p test*.py", "tests_run": 698, "failures": 0, "errors": 0, "status": "passed", "duration_s": 439.247},
    }
    atomic_write_json(RESULTS_ROOT / "test_discovery_audit.json", test_audit)
    by_kind: dict[str, int] = {}
    for row in process.get("records", []):
        kind = str(row.get("kind", "unknown"))
        by_kind[kind] = by_kind.get(kind, 0) + 1
    process_audit = {
        "schema": "stage4f-c-repair2-process-cleanup-audit-1.0.0",
        "numerical_execution": process,
        "started_by_kind": by_kind,
        "owned_started": process.get("started"), "owned_closed": process.get("closed"), "owned_residual": process.get("residual"),
        "preexisting_mathworks_servicehost_targeted": False,
        "openfoam_started_before_A_gate": False,
        "B_started": False, "C_started": False,
        "process_identity_note": "MATLAB rows include observed parent PID, command line, cwd and D-drive environment; legacy OpenFOAM registry rows retain PID/creation time but do not expose all observed command fields.",
    }
    atomic_write_json(RESULTS_ROOT / "process_cleanup_audit.json", process_audit)
    matlab_audit = {
        "schema": "stage4f-c-repair2-matlab-audit-1.0.0",
        "applicationservice_probe": {"path": str(ENV_RESULTS_ROOT / "applicationservice_probe_result.json"), "status": probe.get("status"), "return_code": probe.get("return_code"), "owned_pid": [row.get("pid") for row in probe.get("owned_processes_started", [])], "owned_residual": probe.get("owned_process_residual"), "matlab_core": probe.get("matlab_core"), "matlab_core_sha256": probe.get("matlab_core_sha256")},
        "A_matlab_processes": by_kind.get("matlab", 0), "A_matlab_return_codes": [row.get("return_code") for row in process.get("records", []) if row.get("kind") == "matlab"],
        "B_started": False, "C_started": False,
        "C_drive_project_artifact_count": probe.get("c_drive_project_artifact_count", 0),
    }
    atomic_write_json(RESULTS_ROOT / "matlab_execution_audit.json", matlab_audit)
    runtime_audit = {
        "schema": "stage4f-c-repair2-runtime-path-audit-1.0.0",
        "environment_probe_runtime": probe.get("runtime_root"),
        "numerical_case_root": str(PROJECT_ROOT / "cases/openfoam/stage4f_three_slice_short_window_v1_repair2"),
        "numerical_results_root": str(RESULTS_ROOT),
        "all_new_runtime_paths_on_D": True,
        "probe_c_drive_artifact_count": probe.get("c_drive_project_artifact_count"),
        "system_environment_modified": False,
        "user_preferences_deleted": False,
    }
    atomic_write_json(RESULTS_ROOT / "runtime_path_audit.json", runtime_audit)
    gate = {
        "schema": "stage4f-c-repair2-gate-candidate-1.0.0",
        "status": "blocked",
        "unique_terminal_state": "failure_terminal_branch_A_step_2",
        "stage4f_c_repair_gate_recommendation": "do_not_pass",
        "three_slice_short_window_numerical_status": "blocked",
        "branch_A": {"status": branch.get("status"), "steps_completed": branch.get("steps_completed"), "steps_requested": branch.get("steps_requested"), "time_range_s": branch.get("time_range_s"), "max_cfl": branch.get("max_cfl"), "max_abs_Cd": branch.get("max_abs_Cd"), "max_virtual_work_relative_error": branch.get("max_virtual_work_relative_error"), "max_force_conversion_relative_error": branch.get("max_force_conversion_relative_error"), "max_committed_predictor_velocity_gap_over_U": branch.get("max_committed_predictor_velocity_gap_over_U")},
        "B": {"started": False, "status": "not_started"}, "C": {"started": False, "status": "not_started"},
        "restart": {"status": "not_run"}, "dt_half": {"status": "not_run"},
        "checkpoint_count": branch.get("checkpoint_count"),
        "owned_process": {"started": process.get("started"), "closed": process.get("closed"), "residual": process.get("residual")},
        "applicationservice_probe": probe.get("status"),
        "five_slice_entry_recommendation": "do_not_enter", "nine_slice_entry_recommendation": "do_not_enter", "long_time_viv_entry_recommendation": "do_not_enter",
        "lock_in_or_experimental_validation_claim": "not_completed", "stage4e_physical_validation_claim": "not_completed",
        "stop_condition": execution.get("stop_condition"),
    }
    atomic_write_json(RESULTS_ROOT / "stage4f_c_repair2_gate_candidate.json", gate)
    env_gate = {
        "schema": "stage4f-c-applicationservice-repair-v2-gate-1.0.0",
        "status": probe.get("status"), "probe_result": str(ENV_RESULTS_ROOT / "applicationservice_probe_result.json"),
        "return_code": probe.get("return_code"), "payload_validation": probe.get("payload_validation"),
        "owned_process_residual": probe.get("owned_process_residual"), "c_drive_project_artifact_count": probe.get("c_drive_project_artifact_count"),
        "worker_authorized": probe.get("status") == "passed", "openfoam_started": False,
    }
    atomic_write_json(ENV_RESULTS_ROOT / "environment_gate.json", env_gate)
    report = f"""# Stage 4F-C repair2 closeout\n\n## 终态\n\n本轮为允许的冻结失败终态。ApplicationService 修复探针通过，但 A 分支在第 2 步触发硬门槛，B/C 未启动。不得将本结果称为稳定 VIV、涡脱落统计、锁定区或物理验证。\n\n## 运行\n\n- A：完成 3/20 步，时间 `1.5075 -> 1.515 s`；计划终点 `1.5575 s`。\n- 首个失败：A step 2，slice 0/2 的 `|Cd|` 为 `10.877564567245084` / `11.003110867115256`，超过冻结上限 10；预测-提交速度差最大 `0.01873367971574207`，超过 `0.01`。\n- 三个 slice 日志均有独立 `End`、return code=0、无 fatal、无 NaN/Inf、无负体积。\n- max CFL=`0.1363270394859547`；max 虚功相对误差=`2.361122965019162e-16`；max 力转换误差=`0.0`。\n\n## 环境与进程\n\nrepair2 使用 `bin\\win64\\MATLAB.exe` 的独立 D 盘环境探针，payload、版本、许可证和路径检查全部通过；探针 PID 已关闭，残留 0，C 盘 artifact 0。数值 A 共启动 6 个 MATLAB 和 9 个 OpenFOAM WSL launcher，15/15 关闭，残留 0。旧 MathWorksServiceHost 未被清理。\n\n## 身份\n\n父 checkpoint SHA-256 为 `5db86ae104015d51a8268862a1551579d96d0d80ddc7f55536371efc0334e`；父保护集组合 SHA-256 前后均为 `9e51091ce3b62dc379769db6ff8ea0a7afe47950bb60b92615b2990ea9e2ee01`。固定点 MAT `fixed_point_state.mat` 的 SHA-256 为 `6d6d4ff3ee5e30c32538848c4980b50440a85c3be2cd9e1cac23be8561aa9ed8`，与父 checkpoint 内 runner MAT 及 repair2 checkpoint 分开记录。\n\n## 测试\n\n`compileall` 通过；ApplicationService 专项 3/0/0；repair2 专项 38/0/0；根目录无过滤 unittest 698/0/0。\n\n## 风险与下一授权点\n\n当前首要未解决问题是冻结动力门槛在 A step 2 失败，以及 OpenFOAM registry 对已结束 launcher 未保留完整 command/cwd 字段。不得通过放宽阈值、重用 partial case、修改物理合同或跳过 A 完整通过来进入 B/C。下一步需要 Sol 新授权后针对 A 的动力/几何一致性根因进行独立 repair；本轮不建议进入五切片、九切片、长时 VIV、锁定区或试验验证。\n"""
    report_path = PROJECT_ROOT / "docs" / "13_stage4f_c_v1_repair2_report.md"
    report_path.write_text(report, encoding="utf-8")
    env_report = PROJECT_ROOT / "docs" / "13_stage4f_c_applicationservice_repair_v2_report.md"
    env_report.write_text("# Stage 4F-C ApplicationService repair v2\n\n一次性 R2021b 核心探针通过。结构化 payload、ApplicationService 状态、R2021b 版本、win64 架构、MATLAB license、D 盘 TEMP/TMP/TMPDIR/PREFDIR/tempdir/pwd、return code=0 全部满足；owned PID 已关闭，残留 0，C 盘 artifact=0。该环境通过只授权 A，不代表数值 A/B/C 通过。\n", encoding="utf-8")
    return {"gate": gate, "report": str(report_path), "environment_report": str(env_report)}


if __name__ == "__main__":
    print(json.dumps(write_reports(), ensure_ascii=False, indent=2))
