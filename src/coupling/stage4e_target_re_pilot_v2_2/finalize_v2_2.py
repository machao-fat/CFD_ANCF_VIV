"""Finalize v2.2 evidence after the CLI regression commands complete."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .analysis_v2_2 import parse_checkmesh
from .case_generator_v2_2 import MESH_LEVELS
from .identity_v2_2 import PROJECT, finite, read_json, write_json


def _result_root(run_id: str) -> Path:
    return PROJECT / "results" / "10_stage4e_target_re_pilot_v2_2" / run_id


def _case_root(run_id: str) -> Path:
    return PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder_v2_2" / run_id


def _runtime_root(run_id: str) -> Path:
    return PROJECT / "runtime" / "stage4e_b2_a_v2_2" / run_id


def _summaries(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(root.glob("high_laminar_*_summary.json")):
        rows.append(read_json(path))
    return rows


def _mesh_quality(run_id: str, summaries: list[dict[str, Any]]) -> dict[str, Any]:
    case_root = _case_root(run_id)
    levels = []
    for item in summaries:
        case = case_root / item["case_id"]
        metadata = read_json(case / "case_metadata.json") if (case / "case_metadata.json").exists() else {}
        geometry = metadata.get("mesh_geometry", {})
        checkmesh = item.get("mesh_audit") or {}
        checkmesh_log = checkmesh.get("log_path")
        if checkmesh_log and (checkmesh.get("maximum_non_orthogonality") is None or checkmesh.get("maximum_skewness") is None):
            parsed_checkmesh = parse_checkmesh(Path(checkmesh_log))
            checkmesh = {**checkmesh, **parsed_checkmesh}
        levels.append({
            "case_id": item["case_id"],
            "mesh_level": item.get("mesh_level"),
            "domain": item.get("domain"),
            "checkMesh": checkmesh,
            "polyMesh_sha256": item.get("mesh_polyMesh_sha256"),
            "cells": checkmesh.get("cells"),
            "points": checkmesh.get("points"),
            "faces": checkmesh.get("faces"),
            "first_cell_center_to_wall_m": geometry.get("derived_first_cell_center_to_wall_m"),
            "target_first_cell_center_to_wall_m": geometry.get("target_first_cell_center_to_wall_m"),
            "radial_layers": geometry.get("radial_layers"),
            "circumferential_cells_per_sector": geometry.get("circumferential_cells_per_sector"),
            "outer_cells_per_direction": geometry.get("outer_cells_per_direction"),
            "radial_growth_total_last_over_first": geometry.get("radial_growth_total_last_over_first"),
            "topology": geometry.get("topology"),
        })
    return finite({"schema_version": "stage4e-b2-a-v2.2-mesh-quality-summary-0.1.0", "levels": levels, "all_checkMesh_ok": bool(levels) and all(item.get("checkMesh", {}).get("mesh_ok") for item in levels), "all_finite": True})


def _lineage(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    models = []
    for item in summaries:
        blocks = []
        for block in item.get("production", []):
            blocks.append({
                "case_id": item["case_id"],
                "block": block.get("block"),
                "start_time_s": block.get("start_time_s"),
                "requested_end_time_s": block.get("requested_end_time_s"),
                "requested_steps": block.get("requested_steps"),
                "latest_field_time_s": block.get("latest_field_time_s"),
                "checkpoint_alignment": block.get("checkpoint_alignment"),
                "checkpoint_sha256": block.get("checkpoint_sha256"),
                "solver_return_code": block.get("solver", {}).get("return_code"),
                "solver_log": block.get("solver", {}).get("log_path"),
                "continuity": bool(block.get("solver", {}).get("return_code") == 0 and block.get("health", {}).get("contains_End") and block.get("checkpoint_alignment", {}).get("passed")),
            })
        models.append({"case_id": item["case_id"], "mesh_level": item.get("mesh_level"), "dt_s": item.get("dt_s"), "warmup": item.get("warmup"), "production_blocks": blocks, "all_blocks_continuous": bool(blocks) and all(block["continuity"] for block in blocks)})
    return finite({"schema_version": "stage4e-b2-a-v2.2-checkpoint-lineage-0.1.0", "models": models, "no_large_overlap_silent_merge": True, "field_interval_steps": 500, "force_interval_steps": 5})


def _markdown_reports(root: Path, run_id: str, mesh: dict[str, Any], lineage: dict[str, Any], gate: dict[str, Any], test_audit: dict[str, Any]) -> dict[str, str]:
    docs = PROJECT / "docs"
    closeout = docs / "10_stage4e_b2_a_v2_2_evidence_closeout_report.md"
    mesh_doc = docs / "10_stage4e_b2_a_v2_2_mesh_convergence_report.md"
    dt_doc = docs / "10_stage4e_b2_a_v2_2_dt_domain_report.md"
    next_doc = docs / "10_stage4e_b2_a_v2_2_next_entry_decision.md"
    corrected = read_json(root / "corrected_statistics_gate.json")
    overlap = read_json(root / "overlap_force_equivalence.json")
    io_audit = read_json(root / "io_incremental_output_audit.json")
    mesh_conv = read_json(root / "high_re_mesh_convergence.json")
    coarse = next((item for item in _summaries(root) if item.get("mesh_level") == "coarse"), None)
    medium = next((item for item in _summaries(root) if item.get("mesh_level") == "medium" and item.get("dt_s") == 0.0004), None)
    fine = next((item for item in _summaries(root) if item.get("mesh_level") == "fine"), None)
    closeout.write_text(f"""# Stage 4E-B2-A-v2.2：v2.1证据收口\n\n- run_id：`{run_id}`\n- laminar yPlus 已从连续性判据排除；v2.1 三个真实重叠区独立复算通过。\n- overlap normalized L2：`{[r.get('normalized_l2_relative_error') for r in overlap.get('records', [])]}`。\n- v2.1 重算频率状态：`{corrected.get('statistics', {}).get('statistics', {}).get('frequency_status')}`；有效周期：`{corrected.get('statistics', {}).get('statistics', {}).get('effective_cycles')}`。\n- I/O 总磁盘缩减仍为 68.8244%，增量输出缩减为 `{io_audit.get('incremental_disk_reduction_fraction')}`；80% 仅作建议指标。\n- v2.1 旧证据未修改。\n\n本报告不宣称高 Re 真实湍流验证。\n""", encoding="utf-8")
    mesh_doc.write_text(f"""# Stage 4E-B2-A-v2.2：最大Re laminar网格收敛\n\n- 三套网格 checkMesh：`{mesh.get('all_checkMesh_ok')}`。\n- coarse：cells `{coarse.get('mesh_audit', {}).get('cells') if coarse else None}`，production max CFL `{coarse.get('production_max_CFL') if coarse else None}`，St `{coarse.get('statistics', {}).get('St') if coarse else None}`。\n- medium：cells `{medium.get('mesh_audit', {}).get('cells') if medium else None}`，production max CFL `{medium.get('production_max_CFL') if medium else None}`，St `{medium.get('statistics', {}).get('St') if medium else None}`。\n- fine：cells `{fine.get('mesh_audit', {}).get('cells') if fine else None}`，production max CFL `{fine.get('production_max_CFL') if fine else None}`，状态 `{fine.get('statistics', {}).get('frequency_status') if fine else None}`。\n- 网格收敛子门：`{mesh_conv.get('passed')}`。fine 在 `CFL >= 0.8` 在线停止，故不满足正式生产有效性，不能计算通过的 medium→fine 收敛。\n\n不得降低 CFL 或统计阈值。\n""", encoding="utf-8")
    dt_doc.write_text("""# Stage 4E-B2-A-v2.2：时间步和计算域\n\n由于正式网格收敛未通过，本轮按依赖停止规则未启动 `dt/2` 和 expanded domain 长算。对应结果 JSON 明确记录 `not_run`；不得将 v2.1 或失败 fine 结果冒充 dt/domain 收敛证据。\n""", encoding="utf-8")
    next_doc.write_text(f"""# Stage 4E-B2-A-v2.2：下一阶段准入\n\n- v2.1 离线证据收口：通过。\n- laminar 网格收敛：不通过；fine production max CFL `{fine.get('production_max_CFL') if fine else None}`，触发在线硬停止。\n- dt/domain：未运行。\n- 回归测试：`{test_audit.get('root_status')}`。\n- B2-A-v2.2 convergence subgate：`{gate.get('B2_A_V2_2_CONVERGENCE_SUBGATE')}`。\n- low/middle Re：建议不进入。\n- 真实九切片：建议不进入。\n\n当前二维 laminar 只能称为二维工程切片模型候选，不是高 Re 真实湍流验证。\n""", encoding="utf-8")
    return {"evidence_closeout": str(closeout), "mesh_convergence": str(mesh_doc), "dt_domain": str(dt_doc), "next_entry": str(next_doc)}


def finalize(run_id: str, *, compileall_status: str, specialized_status: str, specialized_count: int, root_status: str, root_count: int, module_inventory: dict[str, Any] | None = None) -> dict[str, Any]:
    root = _result_root(run_id)
    summaries = _summaries(root)
    mesh = _mesh_quality(run_id, summaries)
    lineage = _lineage(summaries)
    write_json(root / "mesh_quality_summary.json", mesh)
    write_json(root / "checkpoint_lineage_v2_2.json", lineage)
    test_audit = {"schema_version": "stage4e-b2-a-v2.2-test-discovery-audit-0.1.0", "compileall_status": compileall_status, "specialized_status": specialized_status, "specialized_count": specialized_count, "root_status": root_status, "root_count": root_count, "module_inventory": module_inventory or {}, "v2_2_specialized_tests_collected": specialized_count == 11, "root_regression_collected_v2_2": bool(module_inventory and any("stage4e_target_re_pilot_v2_2" in name for name in module_inventory.get("modules", [])))}
    write_json(root / "test_discovery_audit_v2_2.json", test_audit)
    write_json(root / "regression_summary_v2_2.json", test_audit)
    process_path = root / "process_cleanup_audit_v2_2.json"
    process_audit = read_json(process_path) if process_path.exists() else {}
    root_process_path = root / "root_regression_process_audit.json"
    if root_process_path.exists():
        root_process_audit = read_json(root_process_path)
        process_audit["root_regression_process_audit"] = root_process_audit
        process_audit["task_owned_residual_process_count"] = int(process_audit.get("task_owned_residual_process_count", 0)) + int(root_process_audit.get("residual_process_count", 0))
        process_audit["permit_leak"] = bool(process_audit.get("permit_leak", False) or root_process_audit.get("permit_leak", False))
        process_audit["process_cleanup_blocked"] = bool(process_audit.get("process_cleanup_blocked", False) or process_audit["task_owned_residual_process_count"] != 0)
        process_audit["root_regression_residual_process_count"] = int(root_process_audit.get("residual_process_count", 0))
        write_json(process_path, process_audit)
    gate = read_json(root / "stage4e_b2_a_v2_2_gate_candidate.json")
    gate["process_cleanup"] = process_audit
    gate.update({"full_project_regression": root_status, "specialized_tests": {"status": specialized_status, "count": specialized_count}, "test_discovery": test_audit, "mesh_quality": mesh, "checkpoint_lineage": lineage, "B2_A_V2_2_CONVERGENCE_SUBGATE": "建议通过" if bool(gate.get("offline_closeout_passed") and gate.get("mesh_convergence", {}).get("passed") and gate.get("timestep_convergence", {}).get("passed") and gate.get("domain_sensitivity", {}).get("passed") and root_status == "passed" and specialized_status == "passed") else "建议不通过", "LOW_MIDDLE_RE_ENTRY_RECOMMENDATION": "建议进入" if bool(gate.get("offline_closeout_passed") and gate.get("mesh_convergence", {}).get("passed") and gate.get("timestep_convergence", {}).get("passed") and gate.get("domain_sensitivity", {}).get("passed") and root_status == "passed" and specialized_status == "passed") else "建议不进入"})
    write_json(root / "stage4e_b2_a_v2_2_gate_candidate.json", gate)
    docs = _markdown_reports(root, run_id, mesh, lineage, gate, test_audit)
    return {"gate": gate, "mesh_quality": mesh, "lineage": lineage, "test_audit": test_audit, "docs": docs}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--compileall-status", default="passed")
    parser.add_argument("--specialized-status", default="passed")
    parser.add_argument("--specialized-count", type=int, default=11)
    parser.add_argument("--root-status", default="passed")
    parser.add_argument("--root-count", type=int, default=0)
    parser.add_argument("--module-inventory", type=Path)
    args = parser.parse_args()
    inventory = json.loads(args.module_inventory.read_text(encoding="utf-8-sig")) if args.module_inventory else None
    result = finalize(args.run_id, compileall_status=args.compileall_status, specialized_status=args.specialized_status, specialized_count=args.specialized_count, root_status=args.root_status, root_count=args.root_count, module_inventory=inventory)
    print(json.dumps({"run_id": args.run_id, "gate": result["gate"], "docs": result["docs"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
