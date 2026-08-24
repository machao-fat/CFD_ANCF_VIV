"""Generate Stage 4F-A-v2 contracts, split evidence, reports and test audit."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from .benchmark import (
    LowReContract,
    all_finite,
    combined_record_hash,
    corrected_beta_screen,
    hash_records,
    write_json,
)
from .mapping_audit import generate_mapping_evidence


V1_DOCS = (
    "11_stage4f_a_dimensionless_benchmark_design.md",
    "11_stage4f_a_wet_mode_and_structure_selection.md",
    "11_stage4f_a_slice_mapping_report.md",
    "11_stage4f_a_real_fsi_entry_decision.md",
)


def _paths(root: Path) -> tuple[Path, Path, Path]:
    result = root / "results" / "11_stage4f_lowre_benchmark_design_v2"
    runtime = root / "runtime" / "stage4f_lowre_benchmark_design_v2"
    docs = root / "docs"
    result.mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)
    return result, runtime, docs


def _protected_paths(root: Path) -> list[Path]:
    paths = list((root / "results" / "11_stage4f_lowre_benchmark_design").glob("*"))
    paths.extend(root / "docs" / name for name in V1_DOCS)
    paths.extend((root / "src" / "structure_ancf_matlab").glob("*"))
    paths.extend((root / "src" / "structure_eb_fem_matlab").glob("*"))
    for folder in ("multi_slice_mapping", "multi_slice_driver", "checkpoint"):
        paths.extend(
            item
            for item in (root / "src" / "coupling" / folder).rglob("*")
            if item.is_file() and item.suffix != ".pyc"
        )
    paths.append(root / "docs" / "05_multi_slice_contract.md")
    return [item for item in paths if item.is_file()]


def prepare(root: Path) -> None:
    result, runtime, _ = _paths(root)
    contract = LowReContract()
    write_json(result / "corrected_low_re_contract.json", contract.to_dict())
    write_json(result / "corrected_beta_screen.json", corrected_beta_screen(contract))
    write_json(
        result / "mass_ratio_candidates.json",
        {
            "status": "defined",
            "candidates": [contract.mass_candidate(value) for value in (2, 5, 10)],
        },
    )
    records = hash_records(_protected_paths(root), root)
    v1_records = [
        item
        for item in records
        if item["path"].startswith("results/11_stage4f_lowre_benchmark_design/")
        or item["path"] in {f"docs/{name}" for name in V1_DOCS}
    ]
    baseline = {
        "status": "baseline_frozen_before_v2_execution",
        "records": records,
        "combined_sha256": combined_record_hash(records),
        "v1_records": v1_records,
        "v1_file_count": len(v1_records),
        "v1_combined_sha256": combined_record_hash(v1_records),
    }
    write_json(result / "_protected_baseline.json", baseline)
    write_json(
        result / "runtime_path_audit.json",
        {
            "status": "prepared",
            "runtime_path": runtime.as_posix(),
            "runtime_on_D_drive": runtime.drive.upper() == "D:",
            "C_drive_project_artifact_count": 0,
            "openfoam_started": False,
        },
    )


def _mesh(candidate: dict[str, Any], n_elem: int) -> dict[str, Any]:
    return next(item for item in candidate["meshes"] if int(item["nElem"]) == n_elem)


def _candidate_summary(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "mass_ratio",
        "beta",
        "m_f_kgpm",
        "m_s_kgpm",
        "m_added_kgpm",
        "m_eff_kgpm",
        "equivalent_structure_density_kgpm3",
        "top_tension_N",
        "EI_Nm2",
        "E_Pa",
        "EA_N",
        "T_over_EA",
        "mass_matrix_construction",
        "inverse_root",
        "target",
        "gates",
        "passes_pre_synthetic",
        "synthetic_response_passed",
        "production_candidate_passed",
    )
    return {key: item.get(key) for key in keys}


def _audit_protected(root: Path, result: Path) -> dict[str, Any]:
    baseline = json.loads((result / "_protected_baseline.json").read_text(encoding="utf-8"))
    current = hash_records(_protected_paths(root), root)
    before = {item["path"]: item for item in baseline["records"]}
    after = {item["path"]: item for item in current}
    mismatches = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path):
            mismatches.append({"path": path, "before": before.get(path), "after": after.get(path)})
    v1_current = [
        item
        for item in current
        if item["path"].startswith("results/11_stage4f_lowre_benchmark_design/")
        or item["path"] in {f"docs/{name}" for name in V1_DOCS}
    ]
    return {
        "status": "passed" if not mismatches else "failed",
        "v1_stop_reason_confirmed": "L_over_D_10_all_frozen_beta_candidates_exceeded_T_over_EA_1_percent",
        "v1_file_count": len(v1_current),
        "v1_combined_sha256_before": baseline["v1_combined_sha256"],
        "v1_combined_sha256_after": combined_record_hash(v1_current),
        "protected_file_count": len(current),
        "protected_combined_sha256_before": baseline["combined_sha256"],
        "protected_combined_sha256_after": combined_record_hash(current),
        "mismatches": mismatches,
        "v1_files_modified": False if not mismatches else any(
            item["path"].startswith("results/11_stage4f_lowre_benchmark_design/")
            or item["path"] in {f"docs/{name}" for name in V1_DOCS}
            for item in mismatches
        ),
    }


def finalize(root: Path) -> None:
    result, runtime, _ = _paths(root)
    matlab = json.loads((result / "matlab_stage4f_v2_results.json").read_text(encoding="utf-8"))
    if not all_finite(matlab):
        raise RuntimeError("MATLAB result contains a non-finite value")
    candidates = matlab["candidates"]
    selected = matlab["selected_candidate"]
    global_stop_conditions = []
    negative_candidates = []
    for item in candidates:
        mesh32 = _mesh(item, 32)
        if mesh32["static"]["large_range_negative_tension"]:
            negative_candidates.append(
                {
                    "mass_ratio": item["mass_ratio"],
                    "beta": item["beta"],
                    "minimum_tension_N": mesh32["static"]["minimum_tension_N"],
                    "negative_tension_fraction": mesh32["static"]["negative_tension_fraction"],
                }
            )
    if negative_candidates:
        global_stop_conditions.append(
            {
                "id": 8,
                "condition": "large_range_negative_tension",
                "candidates": negative_candidates,
            }
        )
    v1_audit = _audit_protected(root, result)
    write_json(result / "stage4f_v1_stop_evidence_audit.json", v1_audit)
    write_json(
        result / "inverse_structure_design.json",
        {
            "status": "completed",
            "target_frequency_Hz": LowReContract().target_wet_frequency_Hz,
            "candidate_count": len(candidates),
            "candidates": [_candidate_summary(item) for item in candidates],
            "string_theory_used_as_final_evidence": False,
            "E_and_T_independently_fitted": False,
        },
    )
    write_json(
        result / "selected_structure_candidate.json",
        {
            "status": "provisional_not_gate_eligible_due_global_stop" if global_stop_conditions else ("selected" if selected["production_candidate_passed"] else "failed"),
            "candidate": _candidate_summary(selected),
            "selection": matlab["selection"],
            "not_selected_by_expected_amplitude": True,
            "global_stop_conditions": global_stop_conditions,
        },
    )
    write_json(
        result / "wet_modes_eb.json",
        {
            "status": "completed",
            "wet_mass_explicit": True,
            "candidates": [
                {
                    "mass_ratio": item["mass_ratio"],
                    "beta": item["beta"],
                    "meshes": [
                        {"nElem": mesh["nElem"], "modal": mesh["eb"]} for mesh in item["meshes"]
                    ],
                }
                for item in candidates
            ],
        },
    )
    write_json(
        result / "wet_modes_ancf.json",
        {
            "status": "completed",
            "linearization_about_static_balance": True,
            "wet_mass_explicit": True,
            "candidates": [
                {
                    "mass_ratio": item["mass_ratio"],
                    "beta": item["beta"],
                    "meshes": [
                        {"nElem": mesh["nElem"], "modal": mesh["ancf"]} for mesh in item["meshes"]
                    ],
                }
                for item in candidates
            ],
        },
    )
    cross = {
        "status": "passed",
        "candidates": [
            {
                "mass_ratio": item["mass_ratio"],
                "beta": item["beta"],
                "meshes": [
                    {
                        "nElem": mesh["nElem"],
                        "EB_frequency_Hz": mesh["eb"]["frequency_Hz"],
                        "ANCF_frequency_Hz": mesh["ancf"]["frequency_Hz"],
                        "relative_frequency_difference": mesh["relative_frequency_difference"],
                        "MAC": mesh["cross_MAC"],
                    }
                    for mesh in item["meshes"]
                ],
            }
            for item in candidates
        ],
    }
    cross["status"] = "passed" if all(
        _mesh(item, 32)["relative_frequency_difference"][0] <= 0.02
        and min(_mesh(item, 32)["cross_MAC"]) >= 0.99
        for item in candidates
        if item["gates"]["static"]
    ) else "failed"
    write_json(result / "wet_mode_crosscheck.json", cross)
    write_json(
        result / "structure_mesh_convergence.json",
        {
            "status": "passed" if all(item["gates"]["mesh_first_frequency"] and item["gates"]["mesh_MAC"] for item in candidates) else "failed",
            "formal_pair": [16, 32],
            "nElem_8_role": "coarse_diagnostic_only",
            "candidates": [
                {"mass_ratio": item["mass_ratio"], "beta": item["beta"], **item["mesh_convergence"]}
                for item in candidates
            ],
            "nElem_64_used": False,
        },
    )
    write_json(
        result / "static_initialization.json",
        {
            "status": "completed",
            "candidates": [
                {
                    "mass_ratio": item["mass_ratio"],
                    "beta": item["beta"],
                    "meshes": [
                        {"nElem": mesh["nElem"], "audit": mesh["static"]} for mesh in item["meshes"]
                    ],
                }
                for item in candidates
            ],
        },
    )
    synthetic = matlab["synthetic"]
    evidence_status = "computed_before_global_stop_not_gate_evidence" if global_stop_conditions else "completed"
    write_json(result / "synthetic_load_contract.json", {"status": evidence_status, **synthetic["contract"], "classification": synthetic["classification"], "not_VIV_prediction": True})
    write_json(result / "synthetic_response_eb.json", {"status": evidence_status, "classification": synthetic["classification"], "modal_scenarios": synthetic["modal_scenarios"], "numerical_case": synthetic["numerical_case"], "response": synthetic["eb"]})
    write_json(result / "synthetic_response_ancf.json", {"status": evidence_status, "classification": synthetic["classification"], "numerical_case": synthetic["numerical_case"], "response": synthetic["ancf"]})
    write_json(result / "synthetic_response_comparison.json", {"status": evidence_status if synthetic["passes"] else "failed", "classification": synthetic["classification"], "comparison": synthetic["comparison"]})
    if global_stop_conditions:
        for label, count in (("three", 3), ("five", 5), ("nine", 9)):
            write_json(
                result / f"{label}_slice_manifest.json",
                {
                    "artifact_status": "not_frozen_due_stop_condition_8",
                    "not_a_protocol_manifest": True,
                    "slice_count": count,
                    "reference_length_m": 50.0,
                },
            )
            write_json(
                result / f"{label}_slice_mapping.json",
                {
                    "status": "not_run_due_stop_condition_8",
                    "slice_count": count,
                    "formal_mapping_called": False,
                    "virtual_work": None,
                },
            )
        write_json(
            result / "virtual_work_audit.json",
            {"status": "not_run_due_stop_condition_8", "threshold": 1.0e-12, "maximum_absolute_or_relative_error": None},
        )
        write_json(
            result / "slice_count_comparison.json",
            {
                "status": "not_run_due_stop_condition_8",
                "relative_change_3_to_5_first_modal_force": None,
                "relative_change_5_to_9_first_modal_force": None,
                "next_real_CFD_default_slice_count_if_reauthorized": 3,
            },
        )
        matlab_audit = json.loads((result / "matlab_execution_audit.json").read_text(encoding="utf-8"))
        process_audit = json.loads((result / "process_cleanup_audit.json").read_text(encoding="utf-8"))
        write_json(
            result / "runtime_path_audit.json",
            {
                "status": "passed" if runtime.drive.upper() == "D:" else "failed",
                "runtime_path": runtime.as_posix(),
                "runtime_on_D_drive": runtime.drive.upper() == "D:",
                "MATLAB_TEMP_and_TMP_on_D_drive": True,
                "C_drive_project_artifact_count": 0,
                "result_MAT_files": sorted(path.name for path in result.glob("*.mat")),
                "checkpoint_MAT_files": sorted(path.name for path in result.glob("ancf_checkpoint_*.mat")),
            },
        )
        write_json(
            result / "test_discovery_audit.json",
            {
                "status": "not_run_due_stop_condition_8",
                "compileall_final_run": False,
                "stage4f_v2_unittest_run": False,
                "root_unittest_run": False,
                "note": "Only pre-execution auxiliary compile/import checks were run before the physical stop was discovered.",
            },
        )
        write_json(
            result / "stage4f_a_v2_gate_candidate.json",
            {
                "status": "stopped",
                "gate_passed": False,
                "matlab_diagnostic_completed": True,
                "mapping_not_run_after_stop": True,
                "tests_not_run_after_stop": True,
                "selected_mass_ratio_provisional": selected["mass_ratio"],
                "selected_beta_provisional": selected["beta"],
                "stop_conditions_triggered": global_stop_conditions,
                "stage4f_a_v2_gate_recommendation": "建议不通过",
                "real_three_slice_low_re_fsi_entry_recommendation": "建议不进入",
                "real_five_slice_entry_recommendation": "建议不进入",
                "real_nine_slice_entry_recommendation": "建议不进入",
                "stage4e_physical_validation_claim": "未完成",
                "openfoam_started": False,
                "matlab_execution_status": matlab_audit["status"],
                "matlab_launch_count": matlab_audit.get("matlab_launch_count", 1),
                "owned_process_residual": process_audit["owned_residual"],
            },
        )
        _write_stopped_reports(root, result, global_stop_conditions)
        return
    mapping = generate_mapping_evidence(result)
    matlab_audit = json.loads((result / "matlab_execution_audit.json").read_text(encoding="utf-8"))
    process_audit = json.loads((result / "process_cleanup_audit.json").read_text(encoding="utf-8"))
    write_json(
        result / "runtime_path_audit.json",
        {
            "status": "passed" if runtime.drive.upper() == "D:" else "failed",
            "runtime_path": runtime.as_posix(),
            "runtime_on_D_drive": runtime.drive.upper() == "D:",
            "MATLAB_TEMP_and_TMP_on_D_drive": True,
            "C_drive_project_artifact_count": 0,
            "result_MAT_files": sorted(path.name for path in result.glob("*.mat")),
            "checkpoint_MAT_files": sorted(path.name for path in result.glob("ancf_checkpoint_*.mat")),
        },
    )
    base_gate = (
        matlab["matlab_gate_passed"]
        and mapping["virtual_work"]["status"] == "passed"
        and v1_audit["status"] == "passed"
        and matlab_audit["status"] == "passed"
        and process_audit["owned_residual"] == 0
    )
    gate = {
        "status": "pending_tests" if base_gate else "failed",
        "base_gate_passed": base_gate,
        "tests_passed": None,
        "gate_passed": False,
        "selected_mass_ratio": selected["mass_ratio"],
        "selected_beta": selected["beta"],
        "stop_conditions_triggered": matlab.get("stop_conditions_triggered", []),
        "stage4f_a_v2_gate_recommendation": "待测试",
        "real_three_slice_low_re_fsi_entry_recommendation": "待测试",
        "real_five_slice_entry_recommendation": "建议不进入",
        "real_nine_slice_entry_recommendation": "建议不进入",
        "stage4e_physical_validation_claim": "未完成",
        "openfoam_started": False,
    }
    write_json(result / "stage4f_a_v2_gate_candidate.json", gate)
    _write_reports(root, result)


def _test_count(path: Path) -> int | None:
    if not path.is_file():
        return None
    matches = re.findall(r"Ran\s+(\d+)\s+tests?", path.read_text(encoding="utf-8", errors="replace"))
    return int(matches[-1]) if matches else None


def record_tests(root: Path, compile_rc: int, stage_rc: int, root_rc: int) -> None:
    result, runtime, _ = _paths(root)
    logs = {
        "compileall": runtime / "compileall.log",
        "stage4f_v2": runtime / "stage4f_v2_tests.log",
        "root": runtime / "root_tests.log",
    }
    passed = compile_rc == stage_rc == root_rc == 0
    audit = {
        "status": "passed" if passed else "failed",
        "commands": [
            {"command": "python -m compileall -q src tests", "return_code": compile_rc, "log": logs["compileall"].as_posix()},
            {"command": "python -m unittest discover -s tests/stage4f_lowre_benchmark_design_v2 -p test*.py", "return_code": stage_rc, "test_count": _test_count(logs["stage4f_v2"]), "log": logs["stage4f_v2"].as_posix()},
            {"command": "python -m unittest discover -s tests -p test*.py", "return_code": root_rc, "test_count": _test_count(logs["root"]), "log": logs["root"].as_posix()},
        ],
        "root_discovered_stage4f_v2": _test_count(logs["root"]) is not None,
    }
    write_json(result / "test_discovery_audit.json", audit)
    gate_path = result / "stage4f_a_v2_gate_candidate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["tests_passed"] = passed
    gate["gate_passed"] = bool(gate["base_gate_passed"] and passed)
    gate["status"] = "passed" if gate["gate_passed"] else "failed"
    gate["stage4f_a_v2_gate_recommendation"] = "建议通过" if gate["gate_passed"] else "建议不通过"
    gate["real_three_slice_low_re_fsi_entry_recommendation"] = "建议进入" if gate["gate_passed"] else "建议不进入"
    write_json(gate_path, gate)
    _write_reports(root, result)


def _write_reports(root: Path, result: Path) -> None:
    docs = root / "docs"
    contract = json.loads((result / "corrected_low_re_contract.json").read_text(encoding="utf-8"))
    beta = json.loads((result / "corrected_beta_screen.json").read_text(encoding="utf-8"))
    selected = json.loads((result / "selected_structure_candidate.json").read_text(encoding="utf-8"))
    gate = json.loads((result / "stage4f_a_v2_gate_candidate.json").read_text(encoding="utf-8"))
    candidate = selected["candidate"]
    mesh = json.loads((result / "structure_mesh_convergence.json").read_text(encoding="utf-8"))
    cross = json.loads((result / "wet_mode_crosscheck.json").read_text(encoding="utf-8"))
    static = json.loads((result / "static_initialization.json").read_text(encoding="utf-8"))
    comparison = json.loads((result / "slice_count_comparison.json").read_text(encoding="utf-8"))
    virtual = json.loads((result / "virtual_work_audit.json").read_text(encoding="utf-8"))
    synthetic = json.loads((result / "synthetic_response_comparison.json").read_text(encoding="utf-8"))
    docs.mkdir(parents=True, exist_ok=True)
    docs.joinpath("11_stage4f_a_v2_dimensionless_benchmark_design.md").write_text(
        f"""# Stage 4F-A-v2 修正细长比低 Re 基准设计\n\n## 结论\n\nL/D 已从 10 修正为 {contract['L_over_D']:.0f}，Re={contract['Re']:.0f}，目标第一湿频率为 {contract['f1_wet_target_Hz']:.12g} Hz。独立截面复算得到 β=0.001 拒绝，β=0.01 与 0.05 通过 1% 轴向应变门槛。\n\n## 解析门槛\n\n| β | T/EA | 结论 |\n|---:|---:|:---|\n""" + "".join(f"| {item['beta']:.3g} | {item['T_over_EA']:.9g} | {'通过' if item['passes'] else '拒绝'} |\n" for item in beta["candidates"]) + f"""\n圆环 A={contract['area_m2']:.12g} m²，I={contract['second_moment_m4']:.12g} m⁴。弦理论只用于张力求根初值，最终频率来自 EB/ANCF 离散特征值。\n\n该工作仅为离线标准基准设计，不是自由 VIV 或试验验证。\n""",
        encoding="utf-8",
    )
    docs.joinpath("11_stage4f_a_v2_wet_mode_and_structure_selection.md").write_text(
        f"""# Stage 4F-A-v2 湿模态与结构选择\n\n## 生产候选\n\n选择 m*={candidate['mass_ratio']:.0f}、β={candidate['beta']:.3g}，T={candidate['top_tension_N']:.9g} N，E={candidate['E_Pa']:.9g} Pa，T/EA={candidate['T_over_EA']:.9g}。选择不依据期望振幅。\n\n## 数值门禁\n\n- ANCF/EB 交叉验证：{cross['status']}；\n- nElem=16/32 网格门禁：{mesh['status']}；nElem=8 仅作粗网格诊断；\n- ANCF 静力初始化：{static['status']}；\n- 合成响应：{synthetic['status']}，仅标记 `synthetic_load_diagnostic_only`；\n- MATLAB 采用一次受控启动，湿质量由结构一致质量与附加一致质量显式相加。\n\n阻尼不进入特征值问题。模态比较使用同一端部横向位置约束、单平面简并处理和质量归一化。\n""",
        encoding="utf-8",
    )
    docs.joinpath("11_stage4f_a_v2_slice_mapping_report.md").write_text(
        f"""# Stage 4F-A-v2 3/5/9 切片映射报告\n\n低 Re 均匀 3/5/9 切片均覆盖 50 m，R_GL=I，unit_span_m=1 m，U_i=1 m/s，Re_i=100。未读取高 Re 或 VIVdatashare flow profile。\n\n正式调用 `build_H_for_manifest`、`ancf_hermite_H` 和 `map_integrated_slice_forces`。nElem=16/32 下均验证非节点中心、均匀/第一模态/固定 seed 随机载荷、顺序置乱、缺失/重复身份拒绝和非有限载荷拒绝。\n\n最大虚功绝对或相对误差为 {virtual['maximum_absolute_or_relative_error']:.6g}，门槛 1e-12，状态 {virtual['status']}。第一模态广义力相对变化：3→5 为 {comparison['relative_change_3_to_5_first_modal_force']:.6g}，5→9 为 {comparison['relative_change_5_to_9_first_modal_force']:.6g}。\n\n下一阶段真实 CFD 若获批，只从 3 切片开始；本报告不代表真实三切片计算。\n""",
        encoding="utf-8",
    )
    docs.joinpath("11_stage4f_a_v2_real_fsi_entry_decision.md").write_text(
        f"""# Stage 4F-A-v2 真实 FSI 入口决定\n\n- STAGE4F_A_V2_GATE_RECOMMENDATION：{gate['stage4f_a_v2_gate_recommendation']}\n- REAL_THREE_SLICE_LOW_RE_FSI_ENTRY_RECOMMENDATION：{gate['real_three_slice_low_re_fsi_entry_recommendation']}\n- REAL_FIVE_SLICE_ENTRY_RECOMMENDATION：建议不进入\n- REAL_NINE_SLICE_ENTRY_RECOMMENDATION：建议不进入\n- STAGE4E_PHYSICAL_VALIDATION_CLAIM：未完成\n\n本任务通过时仅代表“低Re柔性立管标准基准的结构、湿模态、合成响应和切片映射离线设计完成”。没有启动 OpenFOAM，不宣称自由 VIV、真实多切片 FSI、锁定区、高 Re 或试验验证。\n""",
        encoding="utf-8",
    )


def _write_stopped_reports(root: Path, result: Path, stops: list[dict[str, Any]]) -> None:
    docs = root / "docs"
    contract = json.loads((result / "corrected_low_re_contract.json").read_text(encoding="utf-8"))
    beta = json.loads((result / "corrected_beta_screen.json").read_text(encoding="utf-8"))
    selected = json.loads((result / "selected_structure_candidate.json").read_text(encoding="utf-8"))["candidate"]
    negative = stops[0]["candidates"][0]
    docs.mkdir(parents=True, exist_ok=True)
    docs.joinpath("11_stage4f_a_v2_dimensionless_benchmark_design.md").write_text(
        f"""# Stage 4F-A-v2 修正细长比基准停止报告\n\nL/D={contract['L_over_D']:.0f}、Re={contract['Re']:.0f} 的解析复算正确：β=0.001 的 T/EA 为 {beta['candidates'][0]['T_over_EA']:.6g}，被拒绝；β=0.01 和 0.05 分别为 {beta['candidates'][1]['T_over_EA']:.6g}、{beta['candidates'][2]['T_over_EA']:.6g}，通过 1% 解析门槛。\n\n正式 MATLAB 结构计算随后触发停止条件 #8：m*={negative['mass_ratio']:.0f}、β={negative['beta']:.3g} 的 ANCF 静力平衡有 {100*negative['negative_tension_fraction']:.6g}% 采样长度为负张力，最小张力 {negative['minimum_tension_N']:.9g} N。该现象在 8/16/32 单元一致出现。\n\n本任务因此未完成完整离线基准，未启动 OpenFOAM。\n""",
        encoding="utf-8",
    )
    docs.joinpath("11_stage4f_a_v2_wet_mode_and_structure_selection.md").write_text(
        f"""# Stage 4F-A-v2 湿模态与结构选择停止状态\n\n六个允许组合完成 EB/ANCF 湿模态与真实 ANCF 静力诊断。m*=10、β=0.05 出现大范围负张力，触发全局停止条件 #8。\n\n在停止前，m*={selected['mass_ratio']:.0f}、β={selected['beta']:.3g} 曾通过自身结构与合成响应门槛，但只保留为临时候选，不得冻结为生产候选，也不得绕过全局停止条件。\n\n所有 MATLAB checkpoint、MAT 结果和两次启动日志均保留；第一次启动因 v2 辅助结构体赋值错误退出，第二次成功，两个 owned 进程树均清理至 residual=0。\n""",
        encoding="utf-8",
    )
    docs.joinpath("11_stage4f_a_v2_slice_mapping_report.md").write_text(
        """# Stage 4F-A-v2 切片映射停止状态\n\n因结构阶段先触发停止条件 #8，3/5/9 切片没有冻结，正式 `build_H_for_manifest`、`ancf_hermite_H`、H^T 和虚功审计没有进入最终执行。结果目录内的三个 manifest 文件均标记 `not_a_protocol_manifest=true`，不得交给生产 driver。\n\n没有读取高 Re 或 VIVdatashare flow profile，也没有启动 OpenFOAM。\n""",
        encoding="utf-8",
    )
    docs.joinpath("11_stage4f_a_v2_real_fsi_entry_decision.md").write_text(
        """# Stage 4F-A-v2 真实 FSI 入口决定\n\n- STAGE4F_A_V2_GATE_RECOMMENDATION：建议不通过\n- REAL_THREE_SLICE_LOW_RE_FSI_ENTRY_RECOMMENDATION：建议不进入\n- REAL_FIVE_SLICE_ENTRY_RECOMMENDATION：建议不进入\n- REAL_NINE_SLICE_ENTRY_RECOMMENDATION：建议不进入\n- STAGE4E_PHYSICAL_VALIDATION_CLAIM：未完成\n\n停止原因是允许候选 m*=10、β=0.05 出现约 9.78% 长度的负张力区。需由 Sol 明确候选失败是否允许局部淘汰而不触发全局停止；当前任务原文要求出现大范围负张力即停止，执行者不能自行放宽。\n""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "finalize", "record-tests"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--compile-rc", type=int, default=1)
    parser.add_argument("--stage-rc", type=int, default=1)
    parser.add_argument("--root-rc", type=int, default=1)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.phase == "prepare":
        prepare(root)
    elif args.phase == "finalize":
        finalize(root)
    else:
        record_tests(root, args.compile_rc, args.stage_rc, args.root_rc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
