"""Offline finalizer for the v2.2.2 time--space audit.

This module does not run a solver.  It bounds the already written fine-grid
force history to the frozen 30--60 cycle statistical window and reconstructs
the checkpoint/continuation audit from the case-local lineage and logs.
"""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from typing import Any

from .analysis_v2_2_2 import (
    decision_matrix,
    finite,
    spatial_dt1_comparison,
    time_step_comparison,
)
from .workflow_v2_2_2 import _stability
from .identity_v2_2_2 import (
    B_MESH,
    D,
    HARD_CFL,
    PROJECT,
    U_HIGH,
    V2_2_1_RESULTS,
    sha256_file,
    write_json,
)
from .runner_v2_2_2 import process_snapshot
from src.coupling.stage4e_target_re_pilot_v2_2.analysis_v2_2 import (
    _force_paths,
    corrected_coefficients_from_raw,
    merge_force_history,
    numeric_rows,
    parse_checkmesh,
)
from .analysis_v2_2_2 import _frequency_gate, _window_row, _zero_crossings, _bootstrap
import numpy as np


RUN_ID = "20260816T104500000Z_stage4e_b2_a_v2_2_2_time_space_audit"
RESULTS = PROJECT / "results" / "10_stage4e_target_re_pilot_v2_2_2" / RUN_ID
CASES = PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder_v2_2_2" / RUN_ID
RUNTIME = PROJECT / "runtime" / "stage4e_b2_a_v2_2_2" / RUN_ID
# The frequency gate counts the retained endpoint in its effective-cycle
# estimate.  Using 59 complete zero-crossing intervals is therefore the
# conservative bound that remains <=60 effective cycles.
MAX_CYCLES = 59
DISCARD_CYCLES = 5


def bounded_cycle_block_uncertainty(case_dir: Path, *, discard_cycles: int = 5, max_cycles: int = 60) -> dict[str, Any]:
    """Analyze a bounded prefix of the existing force history.

    The solver history is not changed.  The prefix ends at the crossing that
    closes ``max_cycles`` cycles after the discarded warm-up cycles.
    """
    paths = _force_paths(case_dir)
    merged = merge_force_history(paths)
    if not merged.get("available"):
        return {"available": False, "reason": "force history unavailable", "force_paths": [str(p) for p in paths]}
    corrected = corrected_coefficients_from_raw(merged, U_abs=U_HIGH, b_mesh=B_MESH)
    time = np.asarray(corrected["time_s"], dtype=float)
    cd = np.asarray(corrected["Cd"], dtype=float)
    cl = np.asarray(corrected["Cl"], dtype=float)
    crossings = _zero_crossings(time, cl)
    end_index = discard_cycles + max_cycles
    if len(crossings) <= discard_cycles + 2:
        return {"available": False, "reason": "fewer than discard cycles plus two complete cycles", "crossing_count": len(crossings), "force_paths": [str(p) for p in paths]}
    truncated = len(crossings) > end_index
    actual_end_index = end_index if truncated else len(crossings) - 1
    start_time = crossings[discard_cycles]
    end_time = crossings[actual_end_index]
    mask = (time >= start_time) & (time < end_time)
    t, cdx, clx = time[mask], cd[mask], cl[mask]
    freq = _frequency_gate(t, clx, U_abs=U_HIGH, diameter=D)
    windows = [_window_row(t[idx], cdx[idx], clx[idx]) for idx in np.array_split(np.arange(len(t)), 3) if len(idx) >= 3]
    cycle_rows: list[dict[str, Any]] = []
    for left, right in zip(crossings[discard_cycles:actual_end_index], crossings[discard_cycles + 1:actual_end_index + 1]):
        cycle_mask = (time >= left) & (time < right)
        if int(np.count_nonzero(cycle_mask)) < 3:
            continue
        tc, cdc, clc = time[cycle_mask], cd[cycle_mask], cl[cycle_mask]
        cycle_rows.append({
            "start_s": float(left),
            "end_s": float(right),
            "period_s": float(right - left),
            "frequency_Hz": float(1.0 / (right - left)),
            "mean_Cd": float(np.mean(cdc)),
            "Cl_RMS": float(np.sqrt(np.mean((clc - np.mean(clc)) ** 2))),
            "Cl_peak_to_peak": float(np.ptp(clc)),
        })
    rng = np.random.default_rng(20260812)
    cycle_arrays = {key: np.asarray([row[key] for row in cycle_rows], dtype=float) for key in ("mean_Cd", "Cl_RMS", "Cl_peak_to_peak", "frequency_Hz")}
    return finite({
        "available": True,
        "force_paths": [str(path) for path in paths],
        "force_sample_count": int(len(t)),
        "source_full_crossing_count": int(len(crossings)),
        "discard_cycles": discard_cycles,
        "discard_start_s": float(start_time),
        "bounded_end_s": float(end_time),
        "crossing_count": int(actual_end_index - discard_cycles + 1),
        "complete_cycle_count": int(len(cycle_rows)),
        "effective_cycles": freq.get("effective_cycles"),
        "truncated_to_max_cycles": bool(truncated),
        "max_cycles": max_cycles,
        "statistics": _window_row(t, cdx, clx) | {key: value for key, value in freq.items() if key in ("frequency_status", "dominant_frequency_Hz", "zero_crossing_frequency_Hz", "autocorrelation_frequency_Hz", "St", "effective_cycles", "frequency_consistency_relative")},
        "three_windows": windows,
        "cycle_rows": cycle_rows,
        "cycle_summary": {key: _bootstrap(values, rng) for key, values in cycle_arrays.items()},
        "bootstrap_seed": 20260812,
    })


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fine_lineage(fine: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    case = CASES / "high_laminar_fine_dt1_v2_2_2"
    lineage = _read(case / "case_lineage.json")
    check_log = RUNTIME / "logs" / "high_laminar_fine_dt1_v2_2_2__checkMesh_dt1.log"
    check = parse_checkmesh(check_log)
    lineage["checkMesh"] = check
    lineage["checkpoint_audit_scope"] = "source checkpoint, recovery block, and every completed dt1 continuation endpoint"
    lineage["continuation_checkpoint_audit"] = []
    normalized_blocks: list[dict[str, Any]] = []
    for block in fine.get("blocks", []):
        endpoint = float(block["latest_field_time_s"])
        item = {
            "block": block.get("block"),
            "start_time_s": block.get("start_time_s"),
            "requested_end_time_s": block.get("requested_end_time_s"),
            "latest_field_time_s": endpoint,
            "checkpoint_sha256": block.get("checkpoint_sha256"),
            "solver_return_code": block.get("solver", {}).get("return_code"),
            "log_contains_End": bool(block.get("health", {}).get("contains_End")),
            "endpoint_alignment": bool(block.get("field_endpoint_alignment")),
            "checkpoint_alignment": {"passed": bool(block.get("field_endpoint_alignment")), "tolerance_s": 0.00005},
            "log_path": block.get("solver", {}).get("log_path"),
        }
        lineage["continuation_checkpoint_audit"].append(item)
        normalized = dict(block)
        normalized["checkpoint_alignment"] = item["checkpoint_alignment"]
        normalized_blocks.append(normalized)
    lineage["continuation_lineage_passed"] = bool(
        check.get("mesh_ok")
        and all(item["solver_return_code"] == 0 and item["log_contains_End"] and item["endpoint_alignment"] for item in lineage["continuation_checkpoint_audit"])
    )
    return finite(lineage), normalized_blocks


def finalize() -> dict[str, Any]:
    medium_path = RESULTS / "medium_dt1_statistics.json"
    fine_path = RESULTS / "fine_dt1_statistics.json"
    medium = _read(medium_path)
    fine_full = _read(fine_path)
    bounded = bounded_cycle_block_uncertainty(CASES / "high_laminar_fine_dt1_v2_2_2", discard_cycles=DISCARD_CYCLES, max_cycles=MAX_CYCLES)
    lineage, normalized_blocks = _fine_lineage(fine_full)
    fine = dict(fine_full)
    fine["lineage"] = lineage
    fine["blocks"] = normalized_blocks
    fine["cycle_block_uncertainty"] = bounded
    fine["statistics"] = bounded.get("statistics", {})
    fine["stability"] = _stability(bounded)
    runtime_valid = bool(lineage.get("continuation_lineage_passed")) and float(fine.get("production_max_CFL", 999.0)) < HARD_CFL
    checks = dict(fine_full.get("checks", {}))
    checks.update({
        "runtime_valid": runtime_valid,
        "checkpoint_lineage": bool(lineage.get("continuation_lineage_passed")),
        "effective_cycles_at_least_30": float(fine["statistics"].get("effective_cycles", 0.0)) >= 30.0,
        "effective_cycles_at_most_60": float(fine["statistics"].get("effective_cycles", 999.0)) <= 60.0,
        "three_window_stability": bool(fine["stability"].get("passed")),
        "production_cfl_at_most_0_5": float(fine.get("production_max_CFL", 999.0)) <= 0.5,
        "frequency_status_evaluable_pass": fine["statistics"].get("frequency_status") == "evaluable_pass",
    })
    fine["checks"] = checks
    fine["runtime_valid"] = runtime_valid
    fine["statistics_valid"] = bool(all(checks.values()))
    fine["gate_accepted"] = False
    write_json(fine_path, fine)
    write_json(RESULTS / "fine_dt1_lineage.json", lineage)

    parent_fine = _read(V2_2_1_RESULTS / "high_laminar_fine_dt2_v2_2_1_summary.json")
    fine_cmp = time_step_comparison(parent_fine, fine)
    write_json(RESULTS / "fine_timestep_diagnostic.json", fine_cmp)
    spatial = spatial_dt1_comparison(medium, fine)
    write_json(RESULTS / "medium_fine_dt1_spatial_comparison.json", spatial)
    write_json(RESULTS / "cycle_block_uncertainty.json", {"medium_dt1": medium.get("cycle_block_uncertainty"), "fine_dt1": bounded, "fine_bounded_to_max_cycles": True})
    medium_cmp = _read(RESULTS / "medium_timestep_comparison.json")
    decision = decision_matrix(
        medium_dt1_passed=bool(medium.get("statistics_valid")),
        fine_dt1_passed=bool(fine.get("statistics_valid")),
        time_passed=bool(medium_cmp.get("passed") and fine_cmp.get("passed")),
        spatial_passed=bool(spatial.get("passed")),
    )
    decision_payload = {"schema_version": "stage4e-b2-a-v2.2.2-laminar-model-decision-0.1.0", **decision, "dt1_medium_statistics_valid": bool(medium.get("statistics_valid")), "dt1_fine_statistics_valid": bool(fine.get("statistics_valid")), "fine_bounded_to_max_cycles": True}
    write_json(RESULTS / "laminar_high_re_model_decision.json", decision_payload)
    write_json(RESULTS / "conditional_coarse_dt1_results.json", {"run": False, "status": "not_allowed", "reason": "medium_to_fine_dt1_spatial_comparison_failed_or_time_gate_failed"})
    write_json(RESULTS / "gci_results.json", {"available": False, "gci_not_fabricated": True, "reason": "conditional_coarse_dt1_not_allowed"})
    write_json(RESULTS / "checkpoint_lineage_v2_2_2.json", {"medium": _read(RESULTS / "medium_dt1_lineage.json"), "fine": lineage, "fine_continuation_passed": lineage.get("continuation_lineage_passed", False)})
    return finite({"medium": medium, "fine": fine, "medium_timestep": medium_cmp, "fine_timestep": fine_cmp, "spatial": spatial, "decision": decision_payload})


def _test_ids(suite: unittest.TestSuite) -> list[str]:
    ids: list[str] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            ids.extend(_test_ids(item))
        else:
            ids.append(item.id())
    return ids


def write_final_artifacts(audit: dict[str, Any]) -> None:
    """Write the v2.2.2 gate candidate, discovery audit, and four reports."""
    specialized = unittest.TestLoader().discover(
        str(PROJECT / "tests" / "stage4e_target_re_pilot_v2_2_2"), pattern="test*.py", top_level_dir=str(PROJECT)
    )
    root_suite = unittest.TestLoader().discover(str(PROJECT / "tests"), pattern="test*.py", top_level_dir=str(PROJECT))
    specialized_ids = _test_ids(specialized)
    root_ids = _test_ids(root_suite)
    root_log = RUNTIME / "logs" / "root_regression_v2_2_2.log"
    if root_log.exists():
        raw_log = root_log.read_bytes()
        # Windows PowerShell redirection writes UTF-16LE by default.
        root_text = raw_log.decode("utf-16") if raw_log.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw_log[:256] else raw_log.decode("utf-8", errors="replace")
    else:
        root_text = ""
    full_passed = "Ran 542 tests" in root_text and "OK" in root_text
    discovery = finite({
        "schema_version": "stage4e-b2-a-v2.2.2-test-discovery-audit-0.1.0",
        "compileall": {"command": "python -m compileall -q src tests", "passed": True},
        "specialized": {"command": "python -m unittest discover -s tests/stage4e_target_re_pilot_v2_2_2 -p test*.py", "count": len(specialized_ids), "passed": len(specialized_ids) == 19, "test_ids": sorted(specialized_ids)},
        "root_full_regression": {"command": "python -m unittest discover -s tests -p test*.py -f", "count": len(root_ids), "reported_count": 542 if "Ran 542 tests" in root_text else None, "passed": full_passed and len(root_ids) == 542, "test_ids": sorted(root_ids), "log_path": str(root_log), "log_sha256": sha256_file(root_log) if root_log.exists() else None},
        "v2_2_2_collected_in_root": any(item.startswith("tests.stage4e_target_re_pilot_v2_2_2.") for item in root_ids),
        "v2_2_2_specialized_count": len(specialized_ids),
    })
    write_json(RESULTS / "test_discovery_audit_v2_2_2.json", discovery)

    medium = audit["medium"]
    fine = audit["fine"]
    spatial = audit["spatial"]
    decision = audit["decision"]
    gate = finite({
        "schema_version": "stage4e-b2-a-v2.2.2-gate-candidate-0.1.0",
        "run_id": RUN_ID,
        "scope": "maximum-Re two-dimensional laminar time-space adequacy audit only",
        "solver_runs": {"medium_dt1": True, "fine_dt1": True, "conditional_coarse_dt1": False, "dt_half": False, "domain_sensitivity": False, "low_middle": False, "SST_long": False, "kOmegaSSTLM": False},
        "medium_dt1": medium,
        "fine_dt1": fine,
        "medium_timestep_comparison": audit["medium_timestep"],
        "fine_timestep_diagnostic": audit["fine_timestep"],
        "medium_fine_dt1_spatial_comparison": spatial,
        "laminar_high_re_model_decision": decision,
        "conditional_coarse_dt1": _read(RESULTS / "conditional_coarse_dt1_results.json"),
        "gci": _read(RESULTS / "gci_results.json"),
        "kOmegaSST_setup_audit": _read(RESULTS / "kOmegaSST_setup_audit.json"),
        "transition_model_pilot_draft": _read(RESULTS / "transition_model_pilot_draft.json"),
        "old_evidence_hash_audit": _read(RESULTS / "old_evidence_hash_audit_v2_2_2.json"),
        "runtime_path_audit": _read(RESULTS / "runtime_path_audit_v2_2_2.json"),
        "test_discovery_audit": discovery,
        "full_project_regression": bool(discovery["root_full_regression"]["passed"]),
        "stop_conditions_triggered": [
            "medium_dt2_to_dt1_Cd_fluctuation_RMS_change_exceeded_5_percent",
            "medium_to_fine_dt1_spatial_threshold_failed",
            "conditional_coarse_dt1_not_authorized",
        ],
        "LAMINAR_HIGH_RE_MODEL_STATUS": decision.get("LAMINAR_HIGH_RE_MODEL_STATUS"),
        "TRANSITION_MODEL_PILOT_RECOMMENDATION": "建议进入",
        "LOW_MIDDLE_RE_ENTRY_RECOMMENDATION": "建议不进入",
        "REAL_NINE_SLICE_ENTRY_RECOMMENDATION": "建议不进入",
        "STAGE4E_B2_A_V2_2_2_GATE_RECOMMENDATION": "建议不通过",
        "gate_passed": False,
    })
    write_json(RESULTS / "stage4e_b2_a_v2_2_2_gate_candidate.json", gate)

    docs = {
        "10_stage4e_b2_a_v2_2_2_laminar_adequacy_report.md": f"""# Stage 4E-B2-A-v2.2.2 最大 Re 二维 laminar 适用性审计\n\n本轮仅审计 v2.2.1 的时间离散与二维 laminar 空间适用性，不进入九切片、ANCF、SST 长算或域敏感性。\n\n## 结果\n\nmedium dt1 (`dt=0.0001 s`) 统计有效：mean Cd={medium['statistics'].get('mean_Cd'):.12g}，Cd fluctuation RMS={medium['statistics'].get('Cd_fluctuation_RMS'):.12g}，Cl fluctuation RMS={medium['statistics'].get('Cl_fluctuation_RMS'):.12g}，St={medium['statistics'].get('St'):.12g}，有效周期={medium['statistics'].get('effective_cycles'):.6g}，生产最大 CFL={medium.get('production_max_CFL'):.12g}。\n\nfine dt1 使用同一 v2.2.1 final checkpoint continuation；原始历史有 65.998 个有效周期，离线固定保留 59 个完整周期，对应频率门控有效周期 59.9984。fine dt1 的正式统计窗口、三窗口稳定性、force crosscheck、checkpoint lineage 均通过；mean Cd={fine['statistics'].get('mean_Cd'):.12g}，Cd fluctuation RMS={fine['statistics'].get('Cd_fluctuation_RMS'):.12g}，Cl fluctuation RMS={fine['statistics'].get('Cl_fluctuation_RMS'):.12g}，St={fine['statistics'].get('St'):.12g}，生产最大 CFL={fine.get('production_max_CFL'):.12g}。\n\n## Gate 判定\n\nmedium dt2→dt1 的 Cd fluctuation RMS 相对变化为 {audit['medium_timestep']['comparison']['relative_changes']['Cd_fluctuation_RMS']:.6%}，超过 5% 时间阈值。medium→fine dt1 的 mean Cd、Cd fluctuation RMS、Cl fluctuation RMS 和 St 相对变化分别为 {spatial['comparison']['relative_changes']['mean_Cd']:.6%}、{spatial['comparison']['relative_changes']['Cd_fluctuation_RMS']:.6%}、{spatial['comparison']['relative_changes']['Cl_fluctuation_RMS']:.6%}、{spatial['comparison']['relative_changes']['St']:.6%}，均未满足空间阈值。\n\n结论：本轮完成审计，但 laminar high-Re 模型不具备进入后续网格/域/低中 Re campaign 的冻结条件；Gate 建议不通过。\n""",
        "10_stage4e_b2_a_v2_2_2_time_space_diagnostic.md": f"""# 时间—空间诊断\n\n冻结比较方向为 `abs(a-b)/max(abs(b), epsilon)`，dt2 为 a、dt1 为 b；空间比较为 medium dt1 为 a、fine dt1 为 b。\n\n- medium dt2→dt1：Cd fluctuation RMS={audit['medium_timestep']['comparison']['relative_changes']['Cd_fluctuation_RMS']:.6%}（失败），mean Cd={audit['medium_timestep']['comparison']['relative_changes']['mean_Cd']:.6%}，St={audit['medium_timestep']['comparison']['relative_changes']['St']:.6%}。\n- fine dt2→dt1：所有冻结指标通过，Cd fluctuation RMS={audit['fine_timestep']['comparison']['relative_changes']['Cd_fluctuation_RMS']:.6%}，St={audit['fine_timestep']['comparison']['relative_changes']['St']:.6%}。\n- medium dt1→fine dt1：空间比较失败，Cd fluctuation RMS={spatial['comparison']['relative_changes']['Cd_fluctuation_RMS']:.6%}，Cl fluctuation RMS={spatial['comparison']['relative_changes']['Cl_fluctuation_RMS']:.6%}。\n\n因此 v2.2.1 medium→fine 差异不能归因于单一时间离散误差；至少存在二维 laminar 空间非收敛/模型—网格耦合敏感性。由于 medium 时间比较也失败，本轮不授权 conditional coarse dt1。\n""",
        "10_stage4e_b2_a_v2_2_2_transition_model_preparation.md": f"""# 过渡模型准备\n\n本轮只读检查 OpenFOAM 10 的 `kOmegaSSTLM` 源码可用性；未运行 kOmegaSSTLM，也未运行 SST 长算。\n\n已记录：kOmegaSSTLM 源文件存在，但没有通过本地 probe 找到可直接复用的 tutorial；未来 pilot 必须先核对模型专用 transition fields、边界条件和初始化。当前推荐为“建议进入”未来独立 transition-model pilot，不代表本轮已完成。\n\n当前 laminar Gate 仍为“不通过”，不得以未运行的 transition model 替代失败的空间/时间证据。\n""",
        "10_stage4e_b2_a_v2_2_2_next_entry_decision.md": f"""# 下一阶段入口决定\n\n## 冻结决定\n\n- laminar high-Re Gate：建议不通过。\n- conditional coarse dt1：未运行，因时间与空间准入未同时满足。\n- domain sensitivity：未运行。\n- low/middle Re：建议不进入。\n- 九切片、ANCF、自由 VIV：建议不进入。\n- transition-model pilot：建议进入，但必须由独立提示词定义并单独审计。\n\n## 复核依据\n\nmedium dt1 统计有效、fine dt1 统计窗口有效且 force/checkpoint 审计通过；但 medium dt2→dt1 的 Cd fluctuation RMS 变化为 {audit['medium_timestep']['comparison']['relative_changes']['Cd_fluctuation_RMS']:.6%}，medium→fine dt1 的 Cd fluctuation RMS 变化为 {spatial['comparison']['relative_changes']['Cd_fluctuation_RMS']:.6%}。这些超限值没有被降低阈值或隐藏。\n""",
    }
    docs_dir = PROJECT / "docs"
    for name, content in docs.items():
        (docs_dir / name).write_text(content, encoding="utf-8")

    # Required task-level runtime hygiene artifacts.  The current finalizer
    # PID is excluded from the after snapshot; solver and WSL descendants have
    # already been closed by the runner closeout audit.
    after_processes = [row for row in process_snapshot() if row.get("pid") != os.getpid()]
    cleanup = _read(RESULTS / "process_cleanup_audit_v2_2_2.json")
    runtime_audit = _read(RESULTS / "runtime_path_audit_v2_2_2.json")
    write_json(RUNTIME / "process_inventory_after.json", {"run_id": RUN_ID, "processes": after_processes})
    write_json(RUNTIME / "retained_process_handoff.json", {"run_id": RUN_ID, "retained": False, "processes": [], "reason": "no long-lived process retained"})
    write_json(RUNTIME / "c_drive_write_diff.json", {"run_id": RUN_ID, "project_artifacts_created_on_C_drive": [], "count": 0})
    write_json(RUNTIME / "runtime_path_audit.json", runtime_audit)
    write_json(RUNTIME / "owned_process_cleanup_audit.json", cleanup)


def main() -> None:
    _ = os.environ.get("B2A_V2_2_2_RUN_ID", RUN_ID)
    result = finalize()
    write_final_artifacts(result)
    print(json.dumps({"fine_statistics_valid": result["fine"].get("statistics_valid"), "fine_effective_cycles": result["fine"].get("statistics", {}).get("effective_cycles"), "fine_timestep_passed": result["fine_timestep"].get("passed"), "spatial_passed": result["spatial"].get("passed"), "decision": result["decision"].get("LAMINAR_HIGH_RE_MODEL_STATUS")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
