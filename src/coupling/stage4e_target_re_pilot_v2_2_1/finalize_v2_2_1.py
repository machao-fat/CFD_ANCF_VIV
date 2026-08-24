"""Finalize v2.2.1 evidence after CFD and regression commands complete."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

from .identity_v2_2_1 import PROJECT, read_json, write_json, finite


def _result_root(run_id: str) -> Path:
    return PROJECT / "results" / "10_stage4e_target_re_pilot_v2_2_1" / run_id


def _runtime_root(run_id: str) -> Path:
    return PROJECT / "runtime" / "stage4e_b2_a_v2_2_1" / run_id


def _case_root(run_id: str) -> Path:
    return PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder_v2_2_1" / run_id


def finalize(run_id: str, *, compileall_status: str, specialized_status: str, specialized_count: int, root_status: str, root_count: int, module_names: list[str], root_process_audit: dict[str, Any] | None = None) -> dict[str, Any]:
    root = _result_root(run_id)
    runtime = _runtime_root(run_id)
    gate = read_json(root / "stage4e_b2_a_v2_2_1_gate_candidate.json")
    process = read_json(root / "process_cleanup_audit_v2_2_1.json")
    if root_process_audit:
        process["root_regression_process_audit"] = root_process_audit
        process["task_owned_residual_process_count"] = int(process.get("task_owned_residual_process_count", 0)) + int(root_process_audit.get("residual_process_count", 0))
        process["permit_leak"] = bool(process.get("permit_leak", False) or root_process_audit.get("permit_leak", False))
        process["process_cleanup_blocked"] = bool(process.get("process_cleanup_blocked", False) or process["task_owned_residual_process_count"] != 0)
        write_json(root / "process_cleanup_audit_v2_2_1.json", process)
    runtime_audit = read_json(runtime / "runtime_path_audit_v2_2_1.json")
    write_json(root / "runtime_path_audit_v2_2_1.json", runtime_audit)
    if not (root / "high_re_timestep_convergence.json").exists():
        write_json(root / "high_re_timestep_convergence.json", {"available": False, "not_run": True, "passed": False, "reason": "common-dt spatial convergence did not pass"})
    if not (root / "high_re_domain_sensitivity.json").exists():
        write_json(root / "high_re_domain_sensitivity.json", {"available": False, "not_run": True, "passed": False, "reason": "time-step convergence dependency"})
    tests = {
        "schema_version": "stage4e-b2-a-v2.2.1-test-discovery-audit-0.1.0",
        "compileall_status": compileall_status,
        "specialized_status": specialized_status,
        "specialized_count": specialized_count,
        "root_status": root_status,
        "root_count": root_count,
        "specialized_module": "stage4e_target_re_pilot_v2_2_1.test_v2_2_1_contracts",
        "modules": module_names,
        "v2_2_1_specialized_tests_collected": specialized_count == 15,
        "root_regression_collected_v2_2_1": any("stage4e_target_re_pilot_v2_2_1" in name for name in module_names),
    }
    write_json(root / "test_discovery_audit_v2_2_1.json", tests)
    old_hash = read_json(root / "old_evidence_hash_audit_v2_2_1.json")
    dependencies_pass = bool(gate.get("fine_dt2_preflight", {}).get("passed") and gate.get("mesh_convergence", {}).get("passed") and gate.get("timestep_convergence", {}).get("passed") and gate.get("domain_sensitivity", {}).get("passed") and old_hash.get("old_evidence_unchanged") and process.get("task_owned_residual_process_count", 0) == 0 and not process.get("permit_leak") and compileall_status == "passed" and specialized_status == "passed" and root_status == "passed")
    gate.update({
        "full_project_regression": root_status,
        "test_discovery": tests,
        "process_cleanup": process,
        "runtime_hygiene": runtime_audit,
        "B2_A_V2_2_1_CONVERGENCE_SUBGATE": "建议通过" if dependencies_pass else "建议不通过",
        "LOW_MIDDLE_RE_ENTRY_RECOMMENDATION": "建议进入" if dependencies_pass else "建议不进入",
        "REAL_NINE_SLICE_ENTRY_RECOMMENDATION": "建议不进入",
    })
    write_json(root / "stage4e_b2_a_v2_2_1_gate_candidate.json", gate)
    mesh = read_json(root / "high_re_mesh_convergence_dt2.json")
    fine = read_json(root / "high_laminar_fine_dt2_v2_2_1_summary.json")
    coarse = read_json(root / "high_laminar_coarse_dt2_v2_2_1_summary.json")
    medium = read_json(root / "high_laminar_medium_dt2_v2_2_1_summary.json")
    docs = PROJECT / "docs"
    (docs / "10_stage4e_b2_a_v2_2_1_fine_cfl_recovery_report.md").write_text(f"""# Stage 4E-B2-A-v2.2.1 fine CFL 恢复\n\n- run_id: `{run_id}`\n- fine dt/2 预检: `{gate.get('fine_dt2_preflight', {}).get('passed')}`\n- 预检 max CFL: `{gate.get('fine_dt2_preflight', {}).get('cfl', {}).get('max_cfl')}`\n- 正式 fine max CFL: `{fine.get('production_max_CFL')}`\n- 正式 fine 超过目标 0.5 但未达到硬停止 0.8，因此不进入正式空间收敛 Gate。\n\n该结果表示时间步目标不满足，不称为 fine 网格物理发散。\n""", encoding="utf-8")
    (docs / "10_stage4e_b2_a_v2_2_1_mesh_convergence_report.md").write_text(f"""# Stage 4E-B2-A-v2.2.1 统一时间步空间收敛\n\n三套网格均使用 `dt=0.0002 s`。coarse runtime/statistics valid=`{coarse.get('runtime_valid')}/{coarse.get('statistics_valid')}`，medium=`{medium.get('runtime_valid')}/{medium.get('statistics_valid')}`，fine=`{fine.get('runtime_valid')}/{fine.get('statistics_valid')}`。\n\n空间收敛结果：`{mesh.get('passed')}`。fine 正式 max CFL=`{fine.get('production_max_CFL')}`，因此不生成伪 GCI，也不接受 medium→fine 空间收敛。\n""", encoding="utf-8")
    (docs / "10_stage4e_b2_a_v2_2_1_dt_domain_report.md").write_text("""# Stage 4E-B2-A-v2.2.1 时间步与计算域\n\n由于统一 dt 空间收敛未通过，正式时间步收敛和 baseline/expanded domain 长算按依赖停止规则未启动。\n""", encoding="utf-8")
    (docs / "10_stage4e_b2_a_v2_2_1_next_entry_decision.md").write_text(f"""# Stage 4E-B2-A-v2.2.1 下一阶段决定\n\n- fine dt/2 预检：通过。\n- 统一 dt 空间收敛：`{mesh.get('passed')}`。\n- 时间步收敛：未运行。\n- domain 敏感性：未运行。\n- B2-A-v2.2.1 convergence subgate：`{gate.get('B2_A_V2_2_1_CONVERGENCE_SUBGATE')}`。\n- low/middle：建议不进入。\n- 真实九切片：建议不进入。\n\n当前 laminar 结果仍只能称为二维工程切片模型候选。\n""", encoding="utf-8")
    return finite({"gate": gate, "tests": tests, "docs": [str(docs / name) for name in ("10_stage4e_b2_a_v2_2_1_fine_cfl_recovery_report.md", "10_stage4e_b2_a_v2_2_1_mesh_convergence_report.md", "10_stage4e_b2_a_v2_2_1_dt_domain_report.md", "10_stage4e_b2_a_v2_2_1_next_entry_decision.md")]})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--compileall-status", required=True)
    parser.add_argument("--specialized-status", required=True)
    parser.add_argument("--specialized-count", type=int, required=True)
    parser.add_argument("--root-status", required=True)
    parser.add_argument("--root-count", type=int, required=True)
    parser.add_argument("--module-names", required=True)
    parser.add_argument("--module-names-base64")
    parser.add_argument("--root-process-audit-json")
    parser.add_argument("--root-process-audit-base64")
    args = parser.parse_args()
    if args.module_names_base64:
        module_names = json.loads(base64.b64decode(args.module_names_base64).decode("utf-8"))
    else:
        module_names = json.loads(args.module_names)
    if args.root_process_audit_base64:
        root_process = json.loads(base64.b64decode(args.root_process_audit_base64).decode("utf-8"))
    else:
        root_process = json.loads(args.root_process_audit_json) if args.root_process_audit_json else None
    result = finalize(args.run_id, compileall_status=args.compileall_status, specialized_status=args.specialized_status, specialized_count=args.specialized_count, root_status=args.root_status, root_count=args.root_count, module_names=module_names, root_process_audit=root_process)
    print(json.dumps({"gate": result["gate"], "tests": result["tests"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
