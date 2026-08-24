"""Stage 4E-B2-A preparation and bounded pilot orchestration."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis import analyze_coefficients, compare_metrics, yplus_audit
from .case_generator import generate_case
from .identity import (
    EXPECTED_CASE_ID, EXPECTED_CONFIG_SHA256, EXPECTED_FLOW_PROFILE_SHA256,
    EXPECTED_MANIFEST_SHA256, finite, load_formal_flow_profile, read_json, sha256_file, sha256_json,
    choose_representative_cases,
)
from .pilot_runner import case_freshness, closeout_process_audit, cfl_from_log, log_health, process_snapshot, run_openfoam_case

PROJECT = Path(__file__).resolve().parents[3]
RESULTS = PROJECT / "results" / "10_stage4e_target_re_pilot"
CASE_ROOT = PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder"


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(finite(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _load_runtime(path: str) -> tuple[Path, str]:
    runtime = Path(path).resolve()
    run_id = runtime.name
    if runtime.parent.name != "stage4e_b2_a":
        raise ValueError("runtime root must be D:/.../CFD_ANCF_VIV/runtime/stage4e_b2_a/<run_id>")
    if not str(runtime).upper().startswith(str(PROJECT / "runtime").upper()):
        raise ValueError("runtime root is outside the project D-drive runtime directory")
    return runtime, run_id


def source_audit(flow: dict[str, Any]) -> dict[str, Any]:
    paths = {
        "parent_flow_profile": PROJECT / "results" / "08_stage4e_physical_baseline_v3_2_2" / "route_G_flow_profile_candidate.json",
        "parent_identity": PROJECT / "results" / "08_stage4e_physical_baseline_v3_2_2" / "final_candidate_identity.json",
        "official_compatibility": PROJECT / "results" / "08_stage4e_physical_baseline_v3_2_2" / "official_0_2_1_compatibility.json",
        "b1_smoke_report": PROJECT / "docs" / "09_stage4e_b1_route_g_boundary_smoke_report.md",
        "b1_symmetry_report": PROJECT / "docs" / "09_stage4e_b1_route_g_symmetry_audit.md",
        "b1_v3_1_2_report": PROJECT / "docs" / "09_stage4e_b1_v3_1_2_project_gate_report.md",
        "b1_v3_1_2_gate": PROJECT / "results" / "09_stage4e_b1_v3_1_2_closeout" / "stage4e_b1_v3_1_2_gate_candidate.json",
        "corrected_velocity_profile": PROJECT / "results" / "08_stage4e_physical_baseline_v3_2_1" / "corrected_velocity_profile.json",
        "route_g_profile_v3_2_1": PROJECT / "results" / "08_stage4e_physical_baseline_v3_2_1" / "route_G_flow_profile_candidate.json",
        "multi_slice_contract": PROJECT / "docs" / "05_multi_slice_contract.md",
        "source_template_blockMeshDict": PROJECT / "cases" / "openfoam" / "stage4e_route_g_reverse_flow_template" / "base" / "system" / "blockMeshDict",
        "source_template_controlDict": PROJECT / "cases" / "openfoam" / "stage4e_route_g_reverse_flow_template" / "base" / "system" / "controlDict",
        "stage4d_developed_flow_v3": PROJECT / "src" / "coupling" / "stage4d_campaign" / "developed_flow_v3.py",
    }
    result: dict[str, Any] = {
        "schema_version": "stage4e-b2-a-source-identity-0.1.0",
        "parent_case_id": EXPECTED_CASE_ID, "parent_candidate": flow["selected_candidate"],
        "parent_flow_profile_sha256": flow["flow_profile_sha256"],
        "parent_manifest_sha256": flow["slice_manifest_sha256"],
        "parent_config_sha256": EXPECTED_CONFIG_SHA256,
        "source_files": {},
        "old_evidence_modified_by_this_task": False,
        "all_required_sources_present": True,
    }
    for label, path in paths.items():
        exists = path.exists()
        result["source_files"][label] = {
            "relative_path": str(path.relative_to(PROJECT)).replace("\\", "/") if exists else None,
            "sha256": sha256_file(path) if exists else None,
            "exists": exists,
        }
        result["all_required_sources_present"] = result["all_required_sources_present"] and exists
    return result


def _case_specs(selected: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    high, middle, low = selected["high"], selected["middle"], selected["low"]
    def duration(item: dict[str, Any]) -> float:
        return max(4.0, 12.0 * 0.02841 / (0.2 * item["pilot_U_mps"]))
    return [
        {"case_id": "precheck_high_laminar_medium", "label": "high", "model": "laminar", "mesh": "medium", "domain": "baseline", "dt": 0.0005, "end": 0.005, "precheck": True},
        {"case_id": "precheck_high_kOmegaSST_medium", "label": "high", "model": "kOmegaSST", "mesh": "medium", "domain": "baseline", "dt": 0.0005, "end": 0.005, "precheck": True},
        {"case_id": "high_laminar_medium", "label": "high", "model": "laminar", "mesh": "medium", "domain": "baseline", "dt": 0.0005, "end": duration(high)},
        {"case_id": "high_kOmegaSST_medium", "label": "high", "model": "kOmegaSST", "mesh": "medium", "domain": "baseline", "dt": 0.0005, "end": duration(high)},
        {"case_id": "high_kOmegaSST_coarse", "label": "high", "model": "kOmegaSST", "mesh": "coarse", "domain": "baseline", "dt": 0.0005, "end": duration(high)},
        {"case_id": "high_kOmegaSST_fine", "label": "high", "model": "kOmegaSST", "mesh": "fine", "domain": "baseline", "dt": 0.0005, "end": duration(high)},
        {"case_id": "high_kOmegaSST_medium_dt2", "label": "high", "model": "kOmegaSST", "mesh": "medium", "domain": "baseline", "dt": 0.00025, "end": duration(high)},
        {"case_id": "high_kOmegaSST_expanded", "label": "high", "model": "kOmegaSST", "mesh": "medium", "domain": "expanded", "dt": 0.0005, "end": duration(high)},
        {"case_id": "middle_kOmegaSST_medium", "label": "middle", "model": "kOmegaSST", "mesh": "medium", "domain": "baseline", "dt": 0.001, "end": duration(middle)},
        {"case_id": "low_kOmegaSST_medium", "label": "low", "model": "kOmegaSST", "mesh": "medium", "domain": "baseline", "dt": 0.0025, "end": duration(low)},
    ]


def prepare(runtime_root: Path) -> dict[str, Any]:
    flow = load_formal_flow_profile()
    selected = choose_representative_cases(flow)
    audit = source_audit(flow)
    run_id = runtime_root.name
    case_run_root = CASE_ROOT / run_id
    if case_run_root.exists():
        raise FileExistsError(f"refusing to reuse case run directory: {case_run_root}")
    case_run_root.mkdir(parents=True)
    specs = _case_specs(selected)
    prepared: list[dict[str, Any]] = []
    for spec in specs:
        source = selected[spec["label"]]
        case_dir = case_run_root / spec["case_id"]
        metadata = {
            "run_id": run_id, "source_slice_id": source["source_slice_id"],
            "source_s_ref_m": source["source_s_ref_m"],
            "source_signed_U_global_mps": source["source_signed_U_global_mps"],
            "source_flow_sign": source["source_flow_sign"],
            "selected_candidate": flow["selected_candidate"],
            "parent_flow_profile_sha256": flow["flow_profile_sha256"],
            "pilot_uses_positive_equivalent_magnitude": True,
            "purpose": "fixed-cylinder target-Re model mesh timestep pilot",
        }
        case_meta = generate_case(
            case_dir, model=spec["model"], mesh_level=spec["mesh"], domain=spec["domain"],
            U=source["pilot_U_mps"], dt=spec["dt"], end_time=spec["end"], metadata=metadata,
        )
        prepared.append({**spec, "case_relative_path": str(case_dir.relative_to(PROJECT)).replace("\\", "/"), "case_metadata": case_meta})
    _write(runtime_root / "prepared_cases.json", {"schema_version": "stage4e-b2-a-prepared-cases-0.1.0", "run_id": run_id, "cases": prepared})
    _write(RESULTS / "source_identity_audit.json", audit)
    _write(RESULTS / "selected_reynolds_cases.json", {
        "schema_version": "stage4e-b2-a-selected-reynolds-cases-0.1.0",
        "selected_candidate": flow["selected_candidate"], "slice_count": len(flow["slices"]),
        "parent_flow_profile_sha256": flow["flow_profile_sha256"], "cases": selected,
        "selection_rule": "low=min nonzero abs(U), middle=middle sorted nonzero magnitude, high=max abs(U)",
        "positive_equivalent_policy": True,
    })
    _write(RESULTS / "case_freshness_audit.json", {"schema_version": "stage4e-b2-a-case-freshness-0.1.0", "run_id": run_id, "prepared_cases": [{"case_id": item["case_id"], "freshness": case_freshness(CASE_ROOT / run_id / item["case_id"])} for item in prepared]})
    return {"flow": flow, "selected": selected, "prepared": prepared, "source_audit": audit}


def run_prechecks(runtime_root: Path) -> dict[str, Any]:
    prepared = read_json(runtime_root / "prepared_cases.json")
    registry: list[dict[str, Any]] = []
    limiter = __import__("src.coupling.process_control.process_limiter", fromlist=["ProcessLimiter"]).ProcessLimiter(2, run_id=runtime_root.name)
    outputs: list[dict[str, Any]] = []
    try:
        for item in prepared["cases"]:
            if not item.get("precheck"):
                continue
            case_dir = PROJECT / item["case_relative_path"]
            freshness = case_freshness(case_dir)
            if not freshness["passed"]:
                raise RuntimeError(f"freshness failed before precheck: {item['case_id']}")
            results = run_openfoam_case(case_dir, runtime_root=runtime_root, run_id=runtime_root.name, registry=registry, limiter=limiter, timeout_s=600.0)
            logs = [Path(r["log_path"]) for r in results]
            solver_result = next((r for r in results if r["step"] == "pimpleFoam"), None)
            output = {
                "case_id": item["case_id"], "steps": results, "solver_return_code": None if solver_result is None else solver_result["return_code"],
                "log_health": log_health(logs), "cfl": cfl_from_log(logs[-1]) if logs else {},
                "precheck_passed": bool(solver_result and solver_result["return_code"] == 0 and log_health(logs)["contains_End"] and not log_health(logs)["fatal_tokens"]),
            }
            outputs.append(output)
            if not output["precheck_passed"]:
                break
        limiter.shutdown()
        process_audit = closeout_process_audit(limiter, registry, runtime_root)
    except Exception:
        try:
            limiter.shutdown(force=True)
        finally:
            closeout_process_audit(limiter, registry, runtime_root)
        raise
    result = {"schema_version": "stage4e-b2-a-precheck-0.1.0", "run_id": runtime_root.name, "outputs": outputs, "all_prechecks_passed": bool(outputs) and all(item["precheck_passed"] for item in outputs), "process_audit": process_audit}
    _write(RESULTS / "precheck_summary.json", result)
    return result


def _formal_case_result(item: dict[str, Any], case_dir: Path, steps: list[dict[str, Any]]) -> dict[str, Any]:
    logs = [Path(r["log_path"]) for r in steps]
    check_log = next((Path(r["log_path"]) for r in steps if r["step"] == "checkMesh"), None)
    solver = next((r for r in steps if r["step"] == "pimpleFoam"), None)
    solver_log = next((Path(r["log_path"]) for r in steps if r["step"] == "pimpleFoam"), None)
    health = log_health(logs)
    cfl = cfl_from_log(solver_log) if solver_log else {}
    force_path = case_dir / "postProcessing" / "forceCoeffs" / "0" / "forceCoeffs.dat"
    stats = analyze_coefficients(force_path, U=float(item["case_metadata"]["U_abs_mps"]))
    mesh_ok = bool(check_log and check_log.exists() and "Mesh OK" in check_log.read_text(encoding="utf-8", errors="replace"))
    solver_ok = bool(solver and solver["return_code"] == 0 and health["contains_End"] and not health["fatal_tokens"])
    cfl_ok = bool(cfl.get("max_cfl") is not None and float(cfl["max_cfl"]) < 0.8)
    return {
        "case_id": item["case_id"], "case_relative_path": item["case_relative_path"],
        "model": item["model"], "mesh": item["mesh"], "domain": item["domain"],
        "U_mps": item["case_metadata"]["U_mps"], "U_abs_mps": item["case_metadata"]["U_abs_mps"],
        "Re": item["case_metadata"]["Re"], "deltaT_s": item["dt"], "endTime_s": item["end"],
        "steps": steps, "mesh_ok": mesh_ok, "solver_return_code": None if solver is None else solver["return_code"],
        "solver_ok": solver_ok, "log_health": health, "cfl": cfl, "cfl_ok": cfl_ok,
        "force_coefficient_path_relative_to_project": str(force_path.relative_to(PROJECT)).replace("\\", "/"),
        "force_statistics": stats, "yplus": yplus_audit(solver_log) if solver_log else {},
        "case_passed_basic_runtime_checks": mesh_ok and solver_ok and cfl_ok and bool(stats.get("available")),
    }


def _metric_for(result: dict[str, Any], key: str) -> float | None:
    value = result.get("force_statistics", {}).get(key)
    return None if value is None else float(value)


def run_suite(runtime_root: Path) -> dict[str, Any]:
    prepared = read_json(runtime_root / "prepared_cases.json")
    previous_registry = []
    registry_path = runtime_root / "owned_process_registry.json"
    if registry_path.exists():
        previous_registry = read_json(registry_path).get("registry", [])
    registry: list[dict[str, Any]] = list(previous_registry)
    limiter = __import__("src.coupling.process_control.process_limiter", fromlist=["ProcessLimiter"]).ProcessLimiter(2, run_id=runtime_root.name)
    results: list[dict[str, Any]] = []
    stopped_on: str | None = None
    try:
        for item in prepared["cases"]:
            if item.get("precheck"):
                continue
            case_dir = PROJECT / item["case_relative_path"]
            fresh = case_freshness(case_dir)
            if not fresh["passed"]:
                stopped_on = f"freshness:{item['case_id']}"
                break
            steps = run_openfoam_case(case_dir, runtime_root=runtime_root, run_id=runtime_root.name, registry=registry, limiter=limiter, timeout_s=7200.0)
            result = _formal_case_result(item, case_dir, steps)
            results.append(result)
            if not result["case_passed_basic_runtime_checks"]:
                stopped_on = f"runtime:{item['case_id']}"
                break
        limiter.shutdown()
        process_audit = closeout_process_audit(limiter, registry, runtime_root)
    except Exception:
        try:
            limiter.shutdown(force=True)
        finally:
            closeout_process_audit(limiter, registry, runtime_root)
        raise

    by_id = {item["case_id"]: item for item in results}
    high_lam = by_id.get("high_laminar_medium")
    high_sst = by_id.get("high_kOmegaSST_medium")
    model_screening = {
        "schema_version": "stage4e-b2-a-model-screening-0.1.0",
        "candidate_models": ["laminar", "kOmegaSST"], "screening_Re": prepared["cases"][2]["case_metadata"]["Re"],
        "comparison": None if not high_lam or not high_sst else compare_metrics(
            {"mean_Cd": _metric_for(high_lam, "mean_Cd"), "Cl_RMS": _metric_for(high_lam, "Cl_RMS"), "St": _metric_for(high_lam, "St")},
            {"mean_Cd": _metric_for(high_sst, "mean_Cd"), "Cl_RMS": _metric_for(high_sst, "Cl_RMS"), "St": _metric_for(high_sst, "St")},
            {"mean_Cd": 0.03, "Cl_RMS": 0.05, "St": 0.02},
        ),
        "results_available": bool(high_lam and high_sst),
        "model_selection_requires_physical_and_cost_review": True,
    }
    mesh_items = [by_id.get(name) for name in ("high_kOmegaSST_coarse", "high_kOmegaSST_medium", "high_kOmegaSST_fine")]
    mesh_conv = {
        "schema_version": "stage4e-b2-a-mesh-convergence-0.1.0", "model": "kOmegaSST", "Re": prepared["cases"][3]["case_metadata"]["Re"],
        "results": [item for item in mesh_items if item], "medium_to_fine_comparison": None,
        "thresholds": {"mean_Cd": 0.03, "Cl_RMS": 0.05, "St": 0.02},
    }
    if mesh_items[1] and mesh_items[2]:
        mesh_conv["medium_to_fine_comparison"] = compare_metrics(
            {key: _metric_for(mesh_items[1], key) for key in ("mean_Cd", "Cl_RMS", "St")},
            {key: _metric_for(mesh_items[2], key) for key in ("mean_Cd", "Cl_RMS", "St")}, mesh_conv["thresholds"]
        )
    dt_base, dt_half = by_id.get("high_kOmegaSST_medium"), by_id.get("high_kOmegaSST_medium_dt2")
    timestep = {
        "schema_version": "stage4e-b2-a-timestep-convergence-0.1.0", "results": [item for item in (dt_base, dt_half) if item],
        "comparison": None if not dt_base or not dt_half else compare_metrics(
            {key: _metric_for(dt_base, key) for key in ("mean_Cd", "Cl_RMS", "St")},
            {key: _metric_for(dt_half, key) for key in ("mean_Cd", "Cl_RMS", "St")}, {"mean_Cd": 0.03, "Cl_RMS": 0.05, "St": 0.02}
        ),
    }
    domain_base, domain_expanded = by_id.get("high_kOmegaSST_medium"), by_id.get("high_kOmegaSST_expanded")
    domain = {
        "schema_version": "stage4e-b2-a-domain-sensitivity-0.1.0", "results": [item for item in (domain_base, domain_expanded) if item],
        "comparison": None if not domain_base or not domain_expanded else compare_metrics(
            {key: _metric_for(domain_base, key) for key in ("mean_Cd", "Cl_RMS", "St")},
            {key: _metric_for(domain_expanded, key) for key in ("mean_Cd", "Cl_RMS", "St")}, {"mean_Cd": 0.03, "Cl_RMS": 0.05, "St": 0.02}
        ),
    }
    low_mid_high = {label: by_id.get(f"{label}_kOmegaSST_medium") for label in ("low", "middle", "high")}
    stationarity = {
        "schema_version": "stage4e-b2-a-statistical-stationarity-0.1.0",
        "criteria": {"three_consecutive_windows": True, "mean_Cd_relative_change": 0.03, "Cl_RMS_relative_change": 0.05, "dominant_frequency_relative_change": 0.02, "Cl_peak_to_peak_relative_change": 0.05},
        "results": {key: (None if value is None else {"case_passed_basic_runtime_checks": value["case_passed_basic_runtime_checks"], "force_statistics": value["force_statistics"]}) for key, value in low_mid_high.items()},
        "frequency_gate": "frequency_not_evaluable_for_gate unless at least three effective shedding periods are present",
    }
    all_stats = [item for item in results if item.get("force_statistics", {}).get("available")]
    force_summary = {"schema_version": "stage4e-b2-a-force-coefficient-summary-0.1.0", "results": all_stats, "force_reference": "F_ref=0.5*rho*U_abs^2*D*unit_span; forceCoeffs uses global drag/lift axes"}
    yplus = {"schema_version": "stage4e-b2-a-yplus-audit-0.1.0", "results": [{"case_id": item["case_id"], **item["yplus"]} for item in results], "target": "SST fine candidate p95 y+ <= 1", "no_claim_without_reported_yplus": True}
    costs = {"schema_version": "stage4e-b2-a-computational-cost-0.1.0", "cases": [{"case_id": item["case_id"], "steps": len(item["force_statistics"].get("three_consecutive_windows", [])), "all_sample_count": item["force_statistics"].get("all_sample_count"), "endTime_s": item["endTime_s"]} for item in results]}
    regression = {"schema_version": "stage4e-b2-a-regression-summary-0.1.0", "precheck_summary_path": "results/10_stage4e_target_re_pilot/precheck_summary.json", "pilot_case_count_completed": len(results), "stopped_on": stopped_on, "no_old_case_modified": True}
    for name, value in {
        "model_screening_summary.json": model_screening, "mesh_convergence.json": mesh_conv,
        "timestep_convergence.json": timestep, "domain_sensitivity.json": domain,
        "low_mid_high_re_results.json": {"schema_version": "stage4e-b2-a-low-mid-high-0.1.0", "results": low_mid_high},
        "statistical_stationarity.json": stationarity, "force_coefficient_summary.json": force_summary,
        "yplus_audit.json": yplus, "computational_cost_summary.json": costs, "regression_summary.json": regression,
        "process_concurrency_audit.json": process_audit,
    }.items():
        _write(RESULTS / name, value)
    gate = {
        "schema_version": "stage4e-b2-a-gate-candidate-0.1.0", "run_id": runtime_root.name,
        "status": "candidate_not_passed" if stopped_on or not results else "candidate_requires_review",
        "scope": "fixed-cylinder target-Re model mesh timestep pilot only",
        "parent_flow_profile_sha256": EXPECTED_FLOW_PROFILE_SHA256, "parent_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "parent_config_sha256": EXPECTED_CONFIG_SHA256, "completed_case_count": len(results), "stopped_on": stopped_on,
        "model_screening": model_screening, "mesh_convergence": mesh_conv, "timestep_convergence": timestep, "domain_sensitivity": domain,
        "no_nine_slice_cfd_claim": True, "no_anf_coupling_claim": True, "no_experiment_validation_claim": True,
    }
    _write(RESULTS / "stage4e_b2_a_gate_candidate.json", gate)
    return {"results": results, "stopped_on": stopped_on, "process_audit": process_audit, "gate": gate}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "precheck", "run-suite"))
    parser.add_argument("--runtime-root", required=True)
    args = parser.parse_args()
    runtime_root, _ = _load_runtime(args.runtime_root)
    if args.command == "prepare":
        prepare(runtime_root)
    elif args.command == "precheck":
        run_prechecks(runtime_root)
    else:
        run_suite(runtime_root)


if __name__ == "__main__":
    main()
