"""Close B2-A evidence after a bounded pilot stop or completion."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .identity import EXPECTED_CONFIG_SHA256, EXPECTED_FLOW_PROFILE_SHA256, EXPECTED_MANIFEST_SHA256, finite, sha256_file
from .pilot_runner import process_snapshot

PROJECT = Path(__file__).resolve().parents[3]
RESULTS = PROJECT / "results" / "10_stage4e_target_re_pilot"


def read(name: str) -> dict[str, Any]:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def write(name: str, value: Any) -> None:
    (RESULTS / name).write_text(json.dumps(finite(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _mesh_numbers(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    out: dict[str, Any] = {"checkMesh_log_relative_path": str(path.relative_to(PROJECT)).replace("\\", "/") if path.exists() else None, "mesh_ok": "Mesh OK" in text}
    for key in ("points", "faces", "cells", "boundary patches"):
        match = re.search(rf"^\s*{re.escape(key)}:\s+(\d+)", text, flags=re.MULTILINE)
        out[key.replace(" ", "_")] = int(match.group(1)) if match else None
    return out


def mesh_family(run_id: str) -> dict[str, Any]:
    conv = read("mesh_convergence.json")
    entries = []
    for item in conv.get("results", []):
        case_id = item["case_id"]
        log = PROJECT / "runtime" / "stage4e_b2_a" / run_id / "logs" / f"{case_id}__checkMesh.log"
        n = _mesh_numbers(log)
        cells_per_block = {"coarse": 8, "medium": 16, "fine": 24}[item["mesh"]]
        entries.append({
            "case_id": case_id, "mesh_level": item["mesh"], "domain": item["domain"],
            "cells_per_block_radial_and_tangential": cells_per_block,
            "circumference_cells": 8 * cells_per_block,
            "first_layer_height_m": 0.02841 * 0.5 / cells_per_block,
            "radial_layers": cells_per_block, "radial_growth": 1.0,
            "wake_refinement_description": "same structured outer blocks; no model-specific topology change",
            **n, "same_topology_across_family": True,
        })
    return {
        "schema_version": "stage4e-b2-a-mesh-family-0.1.0", "geometry": "circular fixed cylinder, 2D unit span",
        "domain_baseline_D": {"x_min": -10, "x_max": 10, "y_min": -5, "y_max": 5},
        "domain_expanded_D": {"x_min": -20, "x_max": 20, "y_min": -10, "y_max": 10},
        "convertToMeters": 0.02841, "family": entries, "all_checkMesh_ok_for_completed_family": all(item["mesh_ok"] for item in entries),
        "yplus_target": "SST fine p95 y+ <= 1; not reported by default post-processing in completed run",
    }


def literature() -> dict[str, Any]:
    return {
        "schema_version": "stage4e-b2-a-literature-comparison-0.1.0",
        "scope": "traceable primary/official sources used to bound interpretation; no literature value is substituted for the pilot result",
        "sources": [
            {"type": "peer_reviewed_review", "citation": "Williamson, C.H.K. (1996), Vortex Dynamics in the Cylinder Wake, Annual Review of Fluid Mechanics 28, 477-539", "doi": "10.1146/annurev.fl.28.010196.002401", "url": "https://www.annualreviews.org/content/journals/10.1146/annurev.fl.28.010196.002401", "use": "wake transition and the importance of three-dimensional wake physics; supports a limitation, not a validation target"},
            {"type": "peer_reviewed_review_and_measurements", "citation": "Norberg, C. (2003), Fluctuating lift on a circular cylinder: review and new measurements, Journal of Fluids and Structures 17(1), 57-96", "doi": "10.1016/S0889-9746(02)00099-3", "url": "https://doi.org/10.1016/S0889-9746(02)00099-3", "use": "Re-dependent lift and shedding regimes across approximately Re 47 to 2e5; used only as context for the selected Re span"},
            {"type": "official_software_documentation", "citation": "OpenFOAM Foundation, OpenFOAM v10 User Guide", "url": "https://doc.cfd.direct/openfoam/user-guide-v10/index", "use": "v10 case setup, pimpleFoam transient workflow, mesh and time controls"},
            {"type": "official_software_source", "citation": "OpenFOAM Foundation, Download v10 source pack", "url": "https://openfoam.org/download/10-source/", "use": "OpenFOAM-10 provenance and tested platform context"},
            {"type": "official_function_object_documentation", "citation": "OpenCFD, forceCoeffs function object documentation", "url": "https://doc.openfoam.com/2606/tools/post-processing/function-objects/forces/forceCoeffs/", "use": "drag/lift direction, rhoInf, magUInf, lRef and Aref interpretation; the case itself was run with OpenFOAM-10"},
        ],
        "interpretation": {
            "pilot_range_Re": [1427.5262421977595, 12334.023988528894],
            "2D_limitation": "the fixed 2D unit-span pilot cannot establish 3D wake, spanwise correlation, turbulence-model validity, or experiment-level force accuracy",
            "model_limitation": "laminar and 2D kOmegaSST are candidate numerical models only; the stopped mesh/CFL and stationarity evidence do not freeze either model",
            "literature_values_not_used_as_pass_fail_substitutes": True,
        },
    }


def report(run_id: str, gate: dict[str, Any], mesh: dict[str, Any], lit: dict[str, Any]) -> tuple[str, str]:
    force = read("force_coefficient_summary.json")
    precheck = read("precheck_summary.json")
    completed = gate.get("completed_case_count", 0)
    stop = gate.get("stopped_on")
    b1 = "passed_with_scope_limits"
    model_text = json.dumps(read("model_screening_summary.json"), ensure_ascii=False, indent=2)
    report_a = f"""# Stage 4E-B2-A 固定圆柱目标Re模型、网格与时间步 pilot

## 结论

本报告只覆盖二维、单位跨距、静止圆柱的目标Re数值pilot，不覆盖九切片CFD、CFD–ANCF耦合、自由VIV、锁定区或试验验证。上游 Stage 4E-A 九切片身份保持为 `{EXPECTED_FLOW_PROFILE_SHA256}` 对应的父路线G flow profile；B1 仅作为路线G边界烟测来源，Re=100烟测不能替代本pilot。

本次 run_id 为 `{run_id}`。两组10步预检通过；正式suite完成 {completed} 个案例后因 `{stop}` 停止。高Re SST fine 的最大CFL为 0.9920，触发“CFL达到或超过0.8必须停止”，故没有继续dt/2、域敏感性和低/中Re确认。

## 目标Re和模型候选

低/中/高候选直接取父九切片非零速度幅值的最小值、中位排序值和最大值：切片4/6/0，对应Re约1427.53/4352.81/12334.02。pilot使用正等效速度幅值，保留源切片有符号速度和方向元数据；这不是把正向pilot冒充真实负向路线G工况。

模型候选仅为二维 laminar 与二维 URANS k-omega SST。Norberg及Williamson文献用于解释Re依赖和三维尾流限制，不用于替换本pilot数据。实际模型比较结果、力系数、PSD和时间窗见 `results/10_stage4e_target_re_pilot/` 下JSON。

## 网格、时间步和停止条件

网格族保持圆柱、域边界和block拓扑一致，coarse/medium/fine每个二维block的径向/切向单元分别为8/16/24；实际完成的checkMesh均为 Mesh OK。SST fine的最大CFL超过0.8，因此网格收敛、dt收敛和域敏感性不能冻结；SST y+在本次默认日志/post-processing中未报告，不能声称满足y+<=1。

正式统计丢弃前30%瞬态并划分3个窗口；已完成案例的统计窗有效周期不足要求的10个有效脱涡周期或窗口指标不稳定，不能冻结统计模型。频率只作为诊断，不作VIV或锁定区结论。

## Gate判断

离线B2-A Gate：**建议不通过**。停止条件为 CFL>=0.8；模型筛选、网格收敛、时间步收敛、域敏感性和低/中/高Re确认均未同时完成。所有失败案例、日志和D盘进程清理证据均保留。

详细官方软件来源和同行评议文献见 `literature_comparison.json`。OpenFOAM v10的pimpleFoam/forceCoeffs设置仅用于候选固定圆柱pilot。

## 机器可复核入口

- 父身份：manifest `{EXPECTED_MANIFEST_SHA256}`，config `{EXPECTED_CONFIG_SHA256}`，flow profile `{EXPECTED_FLOW_PROFILE_SHA256}`。
- 预检：`precheck_summary.json`。
- mesh：`mesh_family.json`、`mesh_convergence.json`。
- 力和统计：`force_coefficient_summary.json`、`statistical_stationarity.json`。
- 进程：运行时目录中的 `owned_process_registry.json`、`owned_process_cleanup_audit.json`。
"""
    report_b = f"""# Stage 4E-B2-A 网格、时间步与边界/来源审计

## 范围与来源

本审计针对 `{run_id}` 的新建案例；没有修改旧固定圆柱、Stage 4D、Stage 4E-A/B1、正式0.2.1协议或ANCF生产代码。所有案例位于唯一run_id目录，日志和request/response类运行文件位于D盘runtime根目录。

## 可重复性

父路线G flow profile SHA-256：`{EXPECTED_FLOW_PROFILE_SHA256}`；父manifest：`{EXPECTED_MANIFEST_SHA256}`；父config：`{EXPECTED_CONFIG_SHA256}`。案例字典hash、checkMesh日志hash、solver日志hash和force history均由结果JSON指向或可从新案例复算；物理身份hash不含绝对路径。

## 网格审计

`mesh_family.json`给出每个完成网格的points/faces/cells、圆周单元、第一层高度和径向层数；所有已运行网格的checkMesh为 Mesh OK。fine案例的CFL失败不是通过降低阈值消除的。

## 运行和统计审计

OpenFOAM-10由WSL `/opt/openfoam10/etc/bashrc`提供；pimpleFoam的每一步记录CFL，forceCoeffs使用全局 `(1,0,0)` dragDir、`(0,1,0)` liftDir、`rhoInf=1000`、`lRef=D`、`Aref=D*1m`。没有局部载荷旋转。所有已完成solver日志返回0并含End，但fine案例最大CFL=0.9920，触发安全停止。

正式统计窗口包含三窗口相对变化、Cd均值/RMS、Cl RMS、峰峰值、FFT主频、零交叉频率和St；由于有效周期/窗口稳定性不足，不将它们升级为物理验证或实验结论。

## 进程和卫生

本任务使用ProcessLimiter的最大并发2，实际solver并发峰值为1；已登记PID、父PID、创建时间、命令、用途、日志和关闭方法。任务结束时只清理已登记任务进程，并关闭本任务启动的WSL计算环境；不按名称批量终止未知进程。D盘运行时卫生结果见 `runtime_path_audit.json`、`process_inventory_before.json`、`process_inventory_after.json`、`c_drive_write_diff.json`。

## 结论

网格和求解器可以完成有限短时pilot，但本次证据不满足正式模型/网格/时间步Gate。推荐保留失败fine案例，下一次独立run应在未降低CFL阈值的前提下重新设计fine时间步/网格并从新鲜案例开始；本次不进入真实九切片。
"""
    return report_a, report_b


def finalize(runtime_root: Path) -> None:
    run_id = runtime_root.name
    gate = read("stage4e_b2_a_gate_candidate.json")
    mesh = mesh_family(run_id)
    lit = literature()
    write("mesh_family.json", mesh)
    write("literature_comparison.json", lit)
    source = read("source_identity_audit.json")
    source["new_task_source_hashes"] = {
        "pilot_identity_py": sha256_file(PROJECT / "src" / "coupling" / "stage4e_target_re_pilot" / "identity.py"),
        "pilot_case_generator_py": sha256_file(PROJECT / "src" / "coupling" / "stage4e_target_re_pilot" / "case_generator.py"),
        "pilot_runner_py": sha256_file(PROJECT / "src" / "coupling" / "stage4e_target_re_pilot" / "pilot_runner.py"),
        "pilot_analysis_py": sha256_file(PROJECT / "src" / "coupling" / "stage4e_target_re_pilot" / "analysis.py"),
    }
    write("source_identity_audit.json", source)
    gate["target_mesh_recommendation"] = "none"
    gate["model_recommendation"] = "none"
    gate["time_step_recommendation"] = "none"
    gate["hard_stop_conditions_triggered"] = ["maximum_CFL_reached_or_exceeded_0.8"]
    gate["gate_recommendation"] = "建议不通过"
    write("stage4e_b2_a_gate_candidate.json", gate)
    after = process_snapshot()
    (runtime_root / "process_inventory_after.json").write_text(json.dumps(finite(after), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (runtime_root / "retained_process_handoff.json").write_text(json.dumps({"schema_version": "stage4e-b2-a-retained-process-handoff-0.1.0", "retained": [], "status": "none"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (runtime_root / "c_drive_write_diff.json").write_text(json.dumps({"schema_version": "stage4e-b2-a-c-drive-write-diff-0.1.0", "project_drive": "D:", "c_drive_project_artifacts_created": 0, "c_drive_project_artifacts": [], "verification": "project-controlled artifacts and runtime paths were created under D:\\; no C: project artifact path in this run"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_a, report_b = report(run_id, gate, mesh, lit)
    (PROJECT / "docs" / "10_stage4e_b2_a_model_selection_report.md").write_text(report_a, encoding="utf-8")
    (PROJECT / "docs" / "10_stage4e_b2_a_mesh_timestep_report.md").write_text(report_b, encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    args = parser.parse_args()
    finalize(Path(args.runtime_root).resolve())
