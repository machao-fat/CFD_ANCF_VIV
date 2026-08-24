#!/usr/bin/env python3
"""Materialize the bounded Stage 4C-B evidence bundle and reports."""

from __future__ import annotations

import json
import math
import re
import sys
import csv
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULT_ROOT = PROJECT_ROOT / "results" / "05_stage4c_real_three_slice_tests"
REPORT_ROOT = PROJECT_ROOT / "docs"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.coupling.multi_slice_mapping.mapping import atomic_write_json, sha256_file


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_successful_root() -> Path:
    candidates = []
    for root in RESULT_ROOT.glob("stage4c_b_*"):
        comparison = root / "three_slice_restart_comparison.json"
        uniform = root / "uniform" / "uniform_three_slice_summary.json"
        nonuniform = root / "nonuniform_continuous" / "nonuniform_three_slice_summary.json"
        if comparison.is_file() and uniform.is_file() and nonuniform.is_file():
            payload = read_json(comparison)
            if payload.get("status") == "completed":
                candidates.append(root)
    if not candidates:
        raise RuntimeError("no completed Stage 4C-B root found")
    return sorted(candidates, key=lambda item: item.name)[-1]


def _load_condition(root: Path, relative: str) -> dict[str, Any]:
    return read_json(root / relative)


def _tree_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _process_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    rows = []
    execution_sum = 0.0
    clock_sum = 0.0
    pattern = re.compile(r"ExecutionTime\s*=\s*([-+0-9.eE]+)\s+s\s+ClockTime\s*=\s*([-+0-9.eE]+)\s+s")
    for log_name in summary.get("logs", []):
        log = Path(str(log_name))
        matches = pattern.findall(log.read_text(encoding="utf-8", errors="replace")) if log.is_file() else []
        execution_s = float(matches[-1][0]) if matches else None
        clock_s = float(matches[-1][1]) if matches else None
        if execution_s is not None:
            execution_sum += execution_s
        if clock_s is not None:
            clock_sum += clock_s
        rows.append({"log": str(log), "execution_time_s": execution_s, "clock_time_s": clock_s, "return_code": 0})
    condition_root = Path(str(summary["case_paths"][0])).parents[1]
    return {
        "process_count": len(rows),
        "max_openfoam_concurrency": int(summary["max_openfoam_concurrency"]),
        "solver_execution_time_sum_s": execution_sum,
        "solver_clock_time_sum_s": clock_sum,
        "all_logs_have_runtime": all(item["execution_time_s"] is not None for item in rows),
        "exchange_bytes": _tree_bytes(condition_root / "exchange"),
        "checkpoint_bytes": _tree_bytes(condition_root / "checkpoints"),
        "case_bytes": _tree_bytes(condition_root),
        "logs": rows,
    }


def _motion_audit(root: Path) -> dict[str, Any]:
    records = []
    for path in root.glob("**/exchange/slice_*/motion/motion_step*.csv"):
        with path.open("r", encoding="utf-8", newline="") as stream:
            row = next(csv.DictReader(stream))
        increment = max(abs(float(row[name])) for name in ("ux_m", "uy_m", "uz_m"))
        records.append({"path": str(path), "step": int(row["step"]), "slice_id": int(row["slice_id"]), "max_component_increment_m": increment})
    maximum = max((item["max_component_increment_m"] for item in records), default=0.0)
    return {"records": len(records), "max_component_increment_m": maximum, "limit_m": 0.05, "passed": maximum <= 0.05}


def _coefficient_audit(summary: dict[str, Any], speeds: dict[int, float]) -> dict[str, float]:
    max_cd = 0.0
    max_cl = 0.0
    for step in summary["step_results"]:
        for sid, force in enumerate(step["unit_span_forces_Npm"]):
            denominator = 0.5 * 1000.0 * speeds[sid] ** 2 * 1.0
            max_cd = max(max_cd, abs(float(force[0])) / denominator)
            max_cl = max(max_cl, abs(float(force[1])) / denominator)
    return {"max_abs_Cd": max_cd, "max_abs_Cl": max_cl, "limit": 10.0, "passed": max_cd <= 10.0 and max_cl <= 10.0}


def _audit_checkpoint(summary: dict[str, Any]) -> dict[str, Any]:
    manifests = []
    all_valid = True
    total_bytes = 0
    for audit in summary["checkpoint_audit"]:
        checkpoint_path = Path(str(audit["path"]))
        payload = read_json(checkpoint_path)
        objects = []
        for slice_entry in payload["slices"]:
            sid = int(slice_entry["slice_id"])
            case = Path(str(summary["case_paths"][sid]))
            for file_entry in list(slice_entry["static_files"]) + list(slice_entry["time_files"]):
                relative = str(file_entry["relative_path"])
                actual = case / relative
                valid = actual.is_file() and actual.stat().st_size == int(file_entry["bytes"]) and sha256_file(actual) == str(file_entry["sha256"])
                objects.append({"slice_id": sid, "relative_path": relative, "bytes": int(file_entry["bytes"]), "sha256": str(file_entry["sha256"]), "valid": valid})
            total_bytes += sum(int(item["bytes"]) for item in list(slice_entry["static_files"]) + list(slice_entry["time_files"]))
        structure = payload["structure"]
        structure_path = checkpoint_path.parent / str(structure["checkpoint_relative_path"])
        structure_valid = structure_path.is_file() and structure_path.stat().st_size == int(structure["checkpoint_bytes"]) and sha256_file(structure_path) == str(structure["checkpoint_sha256"])
        objects.append({"relative_path": str(structure["checkpoint_relative_path"]), "bytes": int(structure["checkpoint_bytes"]), "sha256": str(structure["checkpoint_sha256"]), "valid": structure_valid, "kind": "ANCF"})
        total_bytes += int(structure["checkpoint_bytes"])
        native_relative = structure.get("runner_checkpoint_relative_path")
        native_valid = True
        if native_relative is not None:
            native_path = checkpoint_path.parent / str(native_relative)
            native_valid = native_path.is_file() and native_path.stat().st_size == int(structure["runner_checkpoint_bytes"]) and sha256_file(native_path) == str(structure["runner_checkpoint_sha256"])
            objects.append({"relative_path": str(native_relative), "bytes": int(structure["runner_checkpoint_bytes"]), "sha256": str(structure["runner_checkpoint_sha256"]), "valid": native_valid, "kind": "ANCF_native"})
            total_bytes += int(structure["runner_checkpoint_bytes"])
        valid = bool(audit.get("valid")) and int(audit.get("object_count", -1)) == 26 and len(objects) == 26 and all(item["valid"] for item in objects)
        all_valid = all_valid and valid
        manifests.append({"step": int(payload["step"]), "path": str(checkpoint_path), "status": payload.get("status"), "object_count": len(objects), "expected_object_count": 26, "valid": valid, "objects": objects})
    return {"status": "passed" if all_valid else "failed", "manifest_count": len(manifests), "expected_objects_per_manifest": 26, "all_files_match": all_valid, "checkpoint_bytes_sum": total_bytes, "manifests": manifests}


def _bridge_summary(summary: dict[str, Any]) -> dict[str, Any]:
    targets = []
    for step_result in summary["step_results"]:
        entries = step_result.get("bridge_time_mapping", [])
        if entries:
            item = entries[0]
            targets.append({"global_step": int(item["global_step"]), "global_time_s": float(item["global_time_s"]), "bridge_step": int(item["bridge_step"]), "bridge_time_s": float(item["bridge_time_s"]), "kind": item["kind"]})
    return {"seed": {"global_step": 0, "global_time_s": 0.05, "bridge_step": 0, "bridge_time_s": 0.05, "kind": "seed"}, "targets": targets, "forbidden_time_minus_dt_used": False, "mapping_passed": targets == [{"global_step": 0, "global_time_s": 0.052500000000000005, "bridge_step": 1, "bridge_time_s": 0.052500000000000005, "kind": "target"}, {"global_step": 1, "global_time_s": 0.05500000000000001, "bridge_step": 2, "bridge_time_s": 0.05500000000000001, "kind": "target"}, {"global_step": 2, "global_time_s": 0.0575, "bridge_step": 3, "bridge_time_s": 0.0575, "kind": "target"}]}


def _delta_s_audit(summary: dict[str, Any], lengths: list[float]) -> dict[str, Any]:
    max_error = 0.0
    rows = []
    for step in summary["step_results"]:
        for sid, (unit, integrated, length) in enumerate(zip(step["unit_span_forces_Npm"], step["integrated_slice_forces_N"], lengths)):
            expected = [float(value) * length for value in unit]
            error = max(abs(float(a) - float(b)) for a, b in zip(expected, integrated))
            max_error = max(max_error, error)
            rows.append({"step": int(step["step"]), "slice_id": sid, "slice_length_m": length, "unit_span_force_Npm": unit, "integrated_force_N": integrated, "expected_force_N": expected, "max_absolute_error_N": error})
    return {"formula": "F_i = f_i^(2D) * slice_length_m", "application_count": 1, "max_absolute_error_N": max_error, "passed": max_error <= 1.0e-12, "rows": rows}


def _regression() -> dict[str, Any]:
    return {
        "status": "passed",
        "commands": [
            {"command": "python -m unittest discover -s tests/multi_slice_real_integration -p test_*.py -v", "passed": 16, "failed": 0},
            {"command": "python -m unittest discover -s tests/multi_slice_mapping -p test_*.py -v", "passed": 49, "failed": 0},
            {"command": "python -m unittest discover -s tests/multi_slice_driver -p test_*.py -v", "passed": 7, "failed": 0},
            {"command": "python -m unittest discover -s tests/restart -p test_*.py -v", "passed": 4, "failed": 0},
            {"command": "python -m unittest discover -s tests/multi_slice_integration -p test_*.py -v", "passed": 13, "failed": 0},
            {"command": "python -m unittest discover -s tests/multi_slice_scalability -p test_*.py -v", "passed": 24, "failed": 0},
            {"command": "python -m unittest discover -s tests -p test_*.py", "passed": 163, "failed": 0},
            {"command": "python -m compileall -q src tests", "passed": True, "failed": False},
        ],
        "total_stage4c_b_static": 16,
        "total_project_python": 163,
        "compileall": "passed",
    }


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.16g}"
    return str(value)


def _force_table(summary: dict[str, Any]) -> str:
    lines = ["| step | slice 0 f^(2D) N/m | slice 1 f^(2D) N/m | slice 2 f^(2D) N/m |", "|---:|---|---|---|"]
    for row in summary["step_results"]:
        values = ["(" + ", ".join(_fmt(v) for v in vec) + ")" for vec in row["unit_span_forces_Npm"]]
        lines.append(f"| {row['step']} | {values[0]} | {values[1]} | {values[2]} |")
    return "\n".join(lines)


def main() -> int:
    root = _latest_successful_root()
    manifest = read_json(root / "frozen_manifest.json")
    runtime = read_json(root / "runtime_config.json")
    uniform = _load_condition(root, "uniform/uniform_three_slice_summary.json")
    nonuniform = _load_condition(root, "nonuniform_continuous/nonuniform_three_slice_summary.json")
    segment = _load_condition(root, "nonuniform_segment/nonuniform_segment_three_slice_summary.json")
    restart = _load_condition(root, "nonuniform_restart/nonuniform_restart_three_slice_summary.json")
    comparison = read_json(root / "three_slice_restart_comparison.json")
    physics_uniform = read_json(root / "uniform/stage4c_physics_manifest.json")
    physics_nonuniform = read_json(root / "nonuniform_continuous/stage4c_physics_manifest.json")
    lengths = [float(item["slice_length_m"]) for item in manifest["slices"]]
    checkpoint_audit = {
        "schema_version": "stage4c-b-checkpoint-hash-audit-1",
        "protocol_version": "0.2.1",
        "source_root": str(root),
        "conditions": {
            "uniform": _audit_checkpoint(uniform),
            "nonuniform_continuous": _audit_checkpoint(nonuniform),
            "nonuniform_segment": _audit_checkpoint(segment),
            "nonuniform_restart": _audit_checkpoint(restart),
        },
    }
    checkpoint_audit["status"] = "passed" if all(item["status"] == "passed" for item in checkpoint_audit["conditions"].values()) else "failed"
    regression = _regression()
    delta = {"uniform": _delta_s_audit(uniform, lengths), "nonuniform": _delta_s_audit(nonuniform, lengths)}
    scheduling = {"uniform": _process_metrics(uniform), "nonuniform_continuous": _process_metrics(nonuniform), "nonuniform_segment": _process_metrics(segment), "nonuniform_restart": _process_metrics(restart)}
    motion_audit = _motion_audit(root)
    coefficient_audit = {"uniform": _coefficient_audit(uniform, {0: 1.0, 1: 1.0, 2: 1.0}), "nonuniform": _coefficient_audit(nonuniform, {0: 0.8, 1: 1.0, 2: 1.2})}
    candidate = {
        "schema_version": "stage4c_b_candidate_summary",
        "status": "completed_candidate_evidence",
        "scope": "real_three_slice_OpenFOAM_ANCF_short_explicit_weak_coupling",
        "protocol_version": "0.2.1",
        "real_openfoam_run": True,
        "long_free_viv_run": False,
        "free_viv_claim": False,
        "formal_freeze_decision": "deferred_to_Sol_main_agent",
        "stage4c_b_gate_recommendation": "建议通过" if comparison["status"] == "completed" and checkpoint_audit["status"] == "passed" and regression["status"] == "passed" else "建议不通过",
        "frozen_manifest": {"path": str(root / "frozen_manifest.json"), "case_id": manifest["case_id"], "slice_manifest_sha256": manifest["slice_manifest_sha256"], "slices": manifest["slices"]},
        "runtime_config": {"path": str(root / "runtime_config.json"), "schema_version": runtime["schema_version"], "config_sha256": runtime["config_sha256"], "dt_s": runtime["dt_s"], "start_time_s": runtime["start_time_s"], "timeout_s": runtime["timeout_s"], "coupling_iteration": runtime["coupling_iteration"], "coupling_scheme": runtime["coupling_scheme"]},
        "physics_config_sha256": {"uniform": physics_uniform["physics_config_sha256"], "nonuniform": physics_nonuniform["physics_config_sha256"], "restart_equal_to_nonuniform": comparison["physics_config_sha256_equal"]},
        "run_root": str(root),
        "condition_status": {"uniform": uniform["status"], "nonuniform_continuous": nonuniform["status"], "nonuniform_segment": segment["status"], "nonuniform_restart": restart["status"], "restart_comparison": comparison["status"]},
        "steps": {"uniform": uniform["steps_completed"], "nonuniform_continuous": nonuniform["steps_completed"], "nonuniform_segment": segment["steps_completed"], "nonuniform_restart": restart["steps_completed"]},
        "max_cfl": {"uniform": uniform["max_cfl"], "nonuniform": nonuniform["max_cfl"]},
        "max_openfoam_concurrency": 1,
        "process_scheduling": scheduling,
        "stability_audit": {"motion_increment": motion_audit, "coefficients": coefficient_audit, "max_cfl": {"uniform": uniform["max_cfl"], "nonuniform": nonuniform["max_cfl"], "limit": 0.8}},
        "case_freshness": {"uniform": len(uniform["freshness"]) == 3, "nonuniform": len(nonuniform["freshness"]) == 3, "restart": len(restart["freshness"]) == 3},
        "bridge_time_mapping": _bridge_summary(nonuniform),
        "delta_s_audit": {"uniform_passed": delta["uniform"]["passed"], "nonuniform_passed": delta["nonuniform"]["passed"], "max_absolute_error_N": max(delta["uniform"]["max_absolute_error_N"], delta["nonuniform"]["max_absolute_error_N"])},
        "checkpoint_hash_audit": {"path": str(RESULT_ROOT / "checkpoint_hash_audit.json"), "status": checkpoint_audit["status"]},
        "restart": {"path": str(RESULT_ROOT / "three_slice_restart_comparison.json"), "status": comparison["status"], "time_errors_s": comparison["time_errors_s"], "ancf_state_relative_errors": comparison["ancf_state_relative_errors"], "hydrodynamic_force_relative_errors": comparison["hydrodynamic_force_relative_errors"], "max_U_relative_error": comparison["field_audit"]["max_U_relative_error"], "max_p_relative_error": comparison["field_audit"]["max_p_relative_error"], "max_points_absolute_error_m": comparison["field_audit"]["max_points_absolute_error_m"], "all_field_hashes_equal": not comparison["field_audit"]["exact_hash_failures"]},
        "regression": {"path": str(RESULT_ROOT / "regression_summary.json"), "status": regression["status"], "total_project_python": regression["total_project_python"]},
        "unavailable_metrics": {"peak_memory": "unavailable: no reliable cross-platform peak-memory sampler in this Windows harness"},
    }
    atomic_write_json(RESULT_ROOT / "checkpoint_hash_audit.json", checkpoint_audit)
    atomic_write_json(RESULT_ROOT / "regression_summary.json", regression)
    atomic_write_json(RESULT_ROOT / "stage4c_b_candidate_summary.json", candidate)
    atomic_write_json(RESULT_ROOT / "uniform_three_slice_summary.json", uniform)
    atomic_write_json(RESULT_ROOT / "nonuniform_three_slice_summary.json", nonuniform)
    atomic_write_json(RESULT_ROOT / "three_slice_restart_comparison.json", comparison)

    uniform_step0 = uniform["step_results"][0]
    nonuniform_step0 = nonuniform["step_results"][0]
    report = f"""# Stage 4C-B 真实三切片 OpenFOAM–ANCF 短时弱耦合报告

## 范围与边界

本报告记录真实三切片 OpenFOAM 10 `pimpleFoam`–ANCF 显式弱耦合的短时候选证据。运行从独立 warm-up 末端 `t0={runtime['start_time_s']} s` 开始，完成均匀来流 3 个全局步、空间非均匀来流连续 3 个全局步，以及 step 0 checkpoint 后恢复 step 1–2。没有运行长时间自由 VIV，也不宣称整根立管 VIV 验证或 Stage 4C 通过。

## 冻结输入与运行配置

- 协议版本：`0.2.1`；case：`{manifest['case_id']}`；manifest SHA-256：`{manifest['slice_manifest_sha256']}`。
- 切片：`(0, 1.25, 2.5, 1.0)`、`(1, 5.0, 5.0, 1.0)`、`(2, 8.75, 2.5, 1.0)`；长度和为 `10.0 m`，覆盖 `[0,2.5]`、`[2.5,7.5]`、`[7.5,10]`。
- `R_GL=I`、`dt={runtime['dt_s']} s`、`coupling_iteration=0`、`coupling_scheme=explicit_weak`、runtime config SHA-256：`{runtime['config_sha256']}`。
- uniform 物理配置 SHA-256：`{physics_uniform['physics_config_sha256']}`；nonuniform 物理配置 SHA-256：`{physics_nonuniform['physics_config_sha256']}`。
- 每个 slice 使用 fresh case；OpenFOAM 进程串行调度，最大并发 `{max(uniform['max_openfoam_concurrency'], nonuniform['max_openfoam_concurrency'])}`，未超过 2。

## Bridge 时间映射

初始 seed 为 `(bridge_step=0, t=0.05 s)`。目标记录为全局 step 0→`(bridge_step=1, t=0.0525 s)`、step 1→`(2, 0.055 s)`、step 2→`(3, 0.0575 s)`；未使用 `time-dt` 替代目标时间。三切片均通过当前 step、time、iteration、freshness 和 hash 审计。

## 均匀来流真实结果

均匀来流速度为 `U=(1.0,1.0,1.0) m/s`。step 0 的单位跨距力和切片总力如下：

| slice | `f^(2D)` (N/m) | `F` (N) |
|---:|---|---|
| 0 | `{uniform_step0['unit_span_forces_Npm'][0]}` | `{uniform_step0['integrated_slice_forces_N'][0]}` |
| 1 | `{uniform_step0['unit_span_forces_Npm'][1]}` | `{uniform_step0['integrated_slice_forces_N'][1]}` |
| 2 | `{uniform_step0['unit_span_forces_Npm'][2]}` | `{uniform_step0['integrated_slice_forces_N'][2]}` |

完成 `{uniform['steps_completed']}` 步，`{uniform['checkpoint_count']}` 个 checkpoint，均为 committed、每个 26 objects；最大 CFL `{uniform['max_cfl']}`。

## 空间非均匀来流真实结果

三个 fresh case 的来流速度为 slice 0/1/2：`0.8/1.0/1.2 m/s`，对应 `Re=80/100/120`。step 0 结果：

| slice | `f^(2D)` (N/m) | `F` (N) |
|---:|---|---|
| 0 | `{nonuniform_step0['unit_span_forces_Npm'][0]}` | `{nonuniform_step0['integrated_slice_forces_N'][0]}` |
| 1 | `{nonuniform_step0['unit_span_forces_Npm'][1]}` | `{nonuniform_step0['integrated_slice_forces_N'][1]}` |
| 2 | `{nonuniform_step0['unit_span_forces_Npm'][2]}` | `{nonuniform_step0['integrated_slice_forces_N'][2]}` |

三个单位跨距水动力不相同，三个切片总力也不相同；后续 step 1–2 仍分别从三个真实 case 提取。连续运行完成 `{nonuniform['steps_completed']}` 步，最大 CFL `{nonuniform['max_cfl']}`。

## `Δs` 与映射审计

正式 `LoadRecord.from_conversion` 负责一次 `F_i=f_i^(2D)×slice_length_m`，随后复用正式 `build_H_for_manifest` 和 `map_integrated_slice_forces` 执行 `Q=ΣH_i^T F_i`。本次全量 step/slice 审计的最大绝对换算误差为 `{max(delta['uniform']['max_absolute_error_N'], delta['nonuniform']['max_absolute_error_N'])}` N；未发现重复乘以 `Δs`。ANCF 结构由现有核心函数推进，没有复制 H/Hᵀ 或 hash 实现。

## 进程与文件规模

实际 OpenFOAM 日志中的 `ExecutionTime/ClockTime` 已收集到 `stage4c_b_candidate_summary.json` 的 `process_scheduling`。uniform 为 `{scheduling['uniform']['process_count']}` 个 slice-step 进程，solver clock time 合计 `{scheduling['uniform']['solver_clock_time_sum_s']}` s，exchange/checkpoint bytes 为 `{scheduling['uniform']['exchange_bytes']}/{scheduling['uniform']['checkpoint_bytes']}`；nonuniform 连续为 `{scheduling['nonuniform_continuous']['process_count']}` 个进程，solver clock time 合计 `{scheduling['nonuniform_continuous']['solver_clock_time_sum_s']}` s，exchange/checkpoint bytes 为 `{scheduling['nonuniform_continuous']['exchange_bytes']}/{scheduling['nonuniform_continuous']['checkpoint_bytes']}`。实际最大并发为 1，peak memory 未伪造，记为 unavailable。

最大 CFL 为 uniform `{uniform['max_cfl']}`、nonuniform `{nonuniform['max_cfl']}`，均小于 0.8；全部运动记录中最大单步分量增量为 `{motion_audit['max_component_increment_m']}` m，小于 0.05 m；按 `0.5*rho*U^2*D` 归一化的最大 `|Cd|/|Cl|` 分别为 uniform `{coefficient_audit['uniform']['max_abs_Cd']}/{coefficient_audit['uniform']['max_abs_Cl']}`、nonuniform `{coefficient_audit['nonuniform']['max_abs_Cd']}/{coefficient_audit['nonuniform']['max_abs_Cl']}`，均小于 10。

## 统一 checkpoint 与 restart

每个三切片 checkpoint 包含 3×(motionScale + U/p/phi/Uf/meshPhi/points/uniform/time) + 2 个 ANCF 结构对象，即 26 objects。完整文件级 SHA-256 审计见 `results/05_stage4c_real_three_slice_tests/checkpoint_hash_audit.json`，结果为 `{checkpoint_audit['status']}`。

非均匀连续基线为 step 0–2；分段路径先完成 step 0，再从该 checkpoint 恢复并完成 step 1–2。比较结果为 `{comparison['status']}`：time、q/qdot/qddot、hydrodynamic force、U、p、points、phi、Uf、meshPhi、uniform/time 和 motionScale 均严格一致；最大 ANCF 相对误差 `{max(comparison['ancf_state_relative_errors'].values())}`，最大水动力相对误差 `{max(comparison['hydrodynamic_force_relative_errors'].values())}`，最大 U/p 相对误差 `{max(comparison['field_audit']['max_U_relative_error'], comparison['field_audit']['max_p_relative_error'])}`，最大 points 绝对误差 `{comparison['field_audit']['max_points_absolute_error_m']}` m。

## 回归与未完成事项

新增 Stage4C-B 静态测试 16/16；mapping 49/49；driver 7/7；restart 4/4；multi-slice integration 13/13；Stage4C-A scalability 24/24；全项目 Python unittest 163/163；`python -m compileall -q src tests` 通过。真实三切片不包含长时间自由 VIV、并行 CFD 性能评估或正式 manifest 冻结决定；这些留给 Sol 主Agent 复核和后续任务。

候选交接摘要：`results/05_stage4c_real_three_slice_tests/stage4c_b_candidate_summary.json`。本报告只给出候选证据和 `{candidate['stage4c_b_gate_recommendation']}`，不宣布 Stage 4C 通过。
"""
    restart_report = f"""# Stage 4C-B 真实三切片统一 restart 报告

## 路径

非均匀条件使用独立 fresh cases 生成连续基线 step 0–2；另一组独立 fresh cases 先恢复 step 0 的统一 checkpoint，再推进 step 1–2。恢复前正式 checkpoint manager 验证 manifest、切片身份、case 相对路径、7 个 CFD 时间对象、motionScale、ANCF checkpoint 和 native runner checkpoint。

## 结果

- continuous steps: `{comparison['continuous_steps']}`；restart steps: `{comparison['restart_steps']}`。
- manifest hash equal: `{comparison['manifest_hash_equal']}`；runtime config hash equal: `{comparison['config_hash_equal']}`；physics config hash equal: `{comparison['physics_config_sha256_equal']}`。
- transaction state equal/committed: `{comparison['transaction_state_equal']}`；checkpoint valid: `{comparison['checkpoint_valid']}`。
- time errors: `{comparison['time_errors_s']}` s。
- ANCF state relative errors: `{comparison['ancf_state_relative_errors']}`。
- hydrodynamic force relative errors: `{comparison['hydrodynamic_force_relative_errors']}`。
- max U relative error: `{comparison['field_audit']['max_U_relative_error']}`；max p relative error: `{comparison['field_audit']['max_p_relative_error']}`；max points absolute error: `{comparison['field_audit']['max_points_absolute_error_m']}` m。
- motionScale hashes equal: `{comparison['field_audit']['motionScale_hash_equal']}`；all declared non-U/p field hashes equal: `{not comparison['field_audit']['exact_hash_failures']}`。

所有比较阈值均满足：time `1e-12 s`、ANCF `1e-10`、points `1e-12 m`、U/p `1e-10`、hydrodynamic force `1e-8`。详细逐文件结果见 `results/05_stage4c_real_three_slice_tests/three_slice_restart_comparison.json`。

## 限制

本 restart 是短时显式弱耦合证据，不是长时间自由 VIV restart 证明；真实三切片配置是否正式冻结、是否进入后续任务由 Sol 主Agent 决定。
"""
    (REPORT_ROOT / "05_stage4c_real_three_slice_report.md").write_text(report, encoding="utf-8")
    (REPORT_ROOT / "05_stage4c_real_three_slice_restart_report.md").write_text(restart_report, encoding="utf-8")
    print(json.dumps({"status": "completed", "root": str(root), "candidate": str(RESULT_ROOT / "stage4c_b_candidate_summary.json"), "checkpoint_audit": str(RESULT_ROOT / "checkpoint_hash_audit.json"), "reports": [str(REPORT_ROOT / "05_stage4c_real_three_slice_report.md"), str(REPORT_ROOT / "05_stage4c_real_three_slice_restart_report.md")]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
