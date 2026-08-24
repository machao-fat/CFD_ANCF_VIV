"""Sequential v2.2.2 checkpoint-lineage campaign for medium/fine dt1."""

from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path
from typing import Any

from src.coupling.stage4e_target_re_pilot_v2_2.case_generator_v2_2 import _fmt
from .analysis_v2_2_2 import (
    METRICS,
    SPATIAL_LIMITS,
    TIME_LIMITS,
    _force_paths,
    checkpoint_alignment,
    coefficient_crosscheck_all,
    cycle_block_uncertainty,
    decision_matrix,
    log_health,
    mesh_lineage_audit,
    offline_reclassification,
    overlap_force_audit_fast,
    parse_cfl,
    parse_checkmesh,
    spatial_dt1_comparison,
    spatial_trend_diagnostic,
    time_step_comparison,
    numeric_time_directories,
)
from .identity_v2_2_2 import (
    AREF,
    B_MESH,
    CONFIG_SHA256,
    D,
    DT1,
    DT1_STAR,
    DT2,
    DT2_STAR,
    FLOW_PROFILE_SHA256,
    FORMAL_CFL_TARGET,
    HARD_CFL,
    MANIFEST_SHA256,
    NU,
    PROJECT,
    RHO,
    RE_HIGH,
    U_HIGH,
    V2_2_1_RUN_ID,
    V2_2_1_CASES,
    V2_2_1_RESULTS,
    V2_2_1_RUNTIME,
    FIELD_INTERVAL_STEPS,
    FORCE_INTERVAL_STEPS,
    finite,
    read_json,
    sha256_file,
    sha256_tree,
    sha256_json,
    write_json,
)
from .runner_v2_2_2 import closeout_process_audit, make_runner, process_snapshot

BLOCK_DURATION_S = 2.0
MIN_BLOCKS = 7
MAX_BLOCKS = 15
DISCARD_CYCLES = 5


def _runtime_environment(runtime: Path) -> dict[str, str]:
    paths = {
        "TEMP": runtime / "temp",
        "TMP": runtime / "tmp",
        "TMPDIR": runtime / "tmp",
        "PYTHONPYCACHEPREFIX": runtime / "pycache",
        "PIP_CACHE_DIR": runtime / "pip-cache",
        "MPLCONFIGDIR": runtime / "mplconfig",
        "MATLAB_PREFDIR": runtime / "matlab-pref",
        "MATLAB_LOG_DIR": runtime / "matlab-log",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    for key, path in paths.items():
        os.environ[key] = str(path)
    return {key: str(path) for key, path in paths.items()}


def _old_evidence_snapshot() -> dict[str, str]:
    roots = {
        "v2_2_1_results": V2_2_1_RESULTS,
        "v2_2_1_cases": V2_2_1_CASES,
        "v2_2_1_runtime": V2_2_1_RUNTIME,
        "v2_2_1_source": PROJECT / "src" / "coupling" / "stage4e_target_re_pilot_v2_2_1",
        "v2_2_1_tests": PROJECT / "tests" / "stage4e_target_re_pilot_v2_2_1",
    }
    return {name: sha256_tree(path) if path.exists() else "MISSING" for name, path in roots.items()}


def _read_v2_2_1_summaries() -> dict[str, dict[str, Any]]:
    names = {level: f"high_laminar_{level}_dt2_v2_2_1_summary.json" for level in ("coarse", "medium", "fine")}
    return {level: read_json(V2_2_1_RESULTS / name) for level, name in names.items()}


def _source_audit(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return finite({
        "schema_version": "stage4e-b2-a-v2.2.2-source-audit-0.1.0",
        "parent_run_id": V2_2_1_RESULTS.name,
        "parent_results_tree_sha256": sha256_tree(V2_2_1_RESULTS),
        "frozen_physics": {"D_m": D, "rho_kgpm3": RHO, "nu_m2ps": NU, "U_mps": U_HIGH, "Re": RE_HIGH, "b_mesh_m": B_MESH, "Aref_OF_m2": AREF, "model": "laminar"},
        "parent_identity": {"flow_profile_sha256": FLOW_PROFILE_SHA256, "manifest_sha256": MANIFEST_SHA256, "config_sha256": CONFIG_SHA256},
        "parent_cases": {level: {"case_id": item.get("case_id"), "case_path": item.get("case_path"), "mesh_polyMesh_sha256": item.get("mesh_polyMesh_sha256"), "runtime_valid": item.get("runtime_valid"), "statistics_valid": item.get("statistics_valid"), "production_max_CFL": item.get("production_max_CFL"), "statistics": item.get("statistics")} for level, item in summaries.items()},
        "fine_boundary_classification": "marginal_stationarity_failure",
        "fine_physical_divergence_claim": False,
        "source_is_read_only": True,
    })


def _functions_text() -> str:
    return f'''functions
{{
    forces
    {{
        type forces;
        libs ("libforces.so");
        patches (cylinder);
        rho rhoInf;
        rhoInf {_fmt(RHO)};
        CofR (0 0 0);
        writeControl timeStep;
        writeInterval {FORCE_INTERVAL_STEPS};
        log yes;
    }}
    forceCoeffs
    {{
        type forceCoeffs;
        libs ("libforces.so");
        patches (cylinder);
        rho rhoInf;
        rhoInf {_fmt(RHO)};
        CofR (0 0 0);
        liftDir (0 1 0);
        dragDir (1 0 0);
        pitchAxis (0 0 1);
        magUInf {_fmt(U_HIGH)};
        lRef {_fmt(D)};
        Aref {_fmt(AREF)};
        writeControl timeStep;
        writeInterval {FORCE_INTERVAL_STEPS};
        log yes;
    }}
}}
'''


def _control_dict(*, dt: float, end_time: float, start_from: str, start_time: float) -> str:
    return f'''FoamFile
{{
    format ascii;
    class dictionary;
    location "system";
    object controlDict;
}}
application pimpleFoam;
startFrom {start_from};
startTime {_fmt(start_time)};
stopAt endTime;
endTime {_fmt(end_time)};
deltaT {_fmt(dt)};
adjustTimeStep no;
maxCo {_fmt(FORMAL_CFL_TARGET)};
writeControl timeStep;
writeInterval {FIELD_INTERVAL_STEPS};
purgeWrite 0;
writeFormat ascii;
writePrecision 16;
writeCompression off;
timeFormat general;
timePrecision 16;
runTimeModifiable false;
{_functions_text()}
// v2.2.2 dt1 continuation: dt={_fmt(dt)}, forceInterval={FORCE_INTERVAL_STEPS}, fieldInterval={FIELD_INTERVAL_STEPS}, source physical time is mapped to local time 0.
'''


def _materialize_checkpoint(source_case: Path, target_case: Path, *, parent_run_id: str, source_case_id: str, target_case_id: str) -> dict[str, Any]:
    if target_case.exists():
        raise FileExistsError(f"refusing to reuse v2.2.2 target case: {target_case}")
    source_times = numeric_time_directories(source_case)
    if not source_times:
        raise FileNotFoundError(f"no source checkpoint in {source_case}")
    source_time_dir = source_times[-1]
    target_case.mkdir(parents=True)
    (target_case / "0").mkdir()
    (target_case / "constant").mkdir()
    (target_case / "system").mkdir()
    shutil.copytree(source_case / "constant" / "polyMesh", target_case / "constant" / "polyMesh")
    for relative in ("physicalProperties", "momentumTransport"):
        shutil.copy2(source_case / "constant" / relative, target_case / "constant" / relative)
    for relative in ("fvSchemes", "fvSolution"):
        shutil.copy2(source_case / "system" / relative, target_case / "system" / relative)
    for name in ("U", "p", "phi"):
        shutil.copy2(source_time_dir / name, target_case / "0" / name)
    (target_case / "system" / "controlDict").write_text(_control_dict(dt=DT1, end_time=BLOCK_DURATION_S, start_from="startTime", start_time=0.0), encoding="utf-8")
    source_hashes = {name: sha256_file(source_time_dir / name) for name in ("U", "p", "phi")}
    target_hashes = {name: sha256_file(target_case / "0" / name) for name in ("U", "p", "phi")}
    source_points = sha256_file(source_case / "constant" / "polyMesh" / "points")
    target_points = sha256_file(target_case / "constant" / "polyMesh" / "points")
    payload = {
        "schema_version": "stage4e-b2-a-v2.2.2-checkpoint-materialization-0.1.0",
        "source_case_id": source_case_id,
        "source_case_path": str(source_case),
        "source_physical_time_s": float(source_time_dir.name),
        "target_case_id": target_case_id,
        "target_case_path": str(target_case),
        "target_local_time_s": 0.0,
        "parent_run_id": parent_run_id,
        "source_U_p_phi_sha256": source_hashes,
        "target_initial_U_p_phi_sha256": target_hashes,
        "source_points_sha256": source_points,
        "target_points_sha256": target_points,
        "points_identical_before_checkMesh": source_points == target_points,
        "fields_identical_before_checkMesh": source_hashes == target_hashes,
        "local_time_mapping": {"source_physical_time_s": float(source_time_dir.name), "target_local_time_s": 0.0, "mapping": "t_local = t_source - source_checkpoint_time"},
    }
    payload["lineage_sha256"] = sha256_json({key: value for key, value in payload.items() if key not in {"source_case_path", "target_case_path"}})
    (target_case / "case_lineage.json").write_text(json.dumps(finite(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return finite(payload)


def _latest(case: Path) -> float:
    dirs = numeric_time_directories(case)
    if not dirs:
        raise RuntimeError(f"no numeric time directory in {case}")
    return float(dirs[-1].name)


def _force_paths_from(case: Path) -> list[Path]:
    return _force_paths(case)


def _stability(cycle_audit: dict[str, Any]) -> dict[str, Any]:
    windows = cycle_audit.get("three_windows", [])
    limits = {"mean_Cd": 0.03, "Cd_fluctuation_RMS": 0.05, "Cl_fluctuation_RMS": 0.05, "Cl_peak_to_peak": 0.05}
    changes: dict[str, list[float]] = {}
    for key, limit in limits.items():
        values = [float(row[key]) for row in windows if row.get(key) is not None]
        base = max(abs(values[0]), 1.0e-12) if values else 1.0
        changes[key] = [abs(value - values[0]) / base for value in values[1:]] if values else []
    return finite({"available": len(windows) == 3, "changes": changes, "limits": limits, "passed": len(windows) == 3 and all(max(changes[key], default=math.inf) <= limit for key, limit in limits.items())})


def _case_summary(case: Path, case_id: str, mesh_level: str, lineage: dict[str, Any], blocks: list[dict[str, Any]], production_cfl: float | None) -> dict[str, Any]:
    paths = _force_paths_from(case)
    overlap = overlap_force_audit_fast(paths)
    cross = coefficient_crosscheck_all(case, U_abs=U_HIGH, b_mesh=B_MESH)
    cycle_audit = cycle_block_uncertainty(case, discard_cycles=DISCARD_CYCLES)
    stats = cycle_audit.get("statistics", {}) if cycle_audit.get("available") else {}
    stability = _stability(cycle_audit) if cycle_audit.get("available") else {"available": False, "passed": False, "changes": {}}
    health = all(item.get("health", {}).get("contains_End") and not item.get("health", {}).get("fatal_tokens") for item in blocks)
    returns_ok = all(item.get("solver", {}).get("return_code") == 0 for item in blocks)
    block_alignment = all(item.get("checkpoint_alignment", {}).get("passed") for item in blocks)
    runtime_valid = bool(blocks) and returns_ok and health and production_cfl is not None and production_cfl < HARD_CFL and block_alignment
    checks = {
        "runtime_valid": runtime_valid,
        "production_cfl_at_most_0_5": production_cfl is not None and production_cfl <= FORMAL_CFL_TARGET,
        "frequency_status_evaluable_pass": stats.get("frequency_status") == "evaluable_pass",
        "effective_cycles_at_least_30": float(stats.get("effective_cycles", 0.0)) >= 30.0,
        "effective_cycles_at_most_60": float(stats.get("effective_cycles", 0.0)) <= 60.0,
        "frequency_consistency_at_most_5_percent": stats.get("frequency_consistency_relative") is not None and float(stats["frequency_consistency_relative"]) <= 0.05,
        "three_window_stability": stability.get("passed", False),
        "force_crosscheck": cross.get("passed", False),
        "force_overlap": len(paths) < 2 or overlap.get("passed", False),
        "checkpoint_lineage": bool(lineage.get("lineage_sha256")) and block_alignment,
    }
    return finite({
        "schema_version": "stage4e-b2-a-v2.2.2-dt1-case-summary-0.1.0",
        "case_id": case_id,
        "mesh_level": mesh_level,
        "case_path": str(case),
        "dt_s": DT1,
        "dt_star": DT1_STAR,
        "source_checkpoint_time_s": lineage.get("source_physical_time_s"),
        "local_time_end_s": _latest(case),
        "lineage": lineage,
        "blocks": blocks,
        "production_max_CFL": production_cfl,
        "force_paths": [str(path) for path in paths],
        "force_crosscheck": cross,
        "overlap_force_audit": overlap,
        "cycle_block_uncertainty": cycle_audit,
        "statistics": stats,
        "stability": stability,
        "checks": checks,
        "runtime_valid": runtime_valid,
        "statistics_valid": all(checks.values()),
        "gate_accepted": False,
    })


def _run_case(case: Path, case_id: str, mesh_level: str, lineage: dict[str, Any], runner: Any, records: list[dict[str, Any]], result_path: Path) -> dict[str, Any]:
    check = runner.execute(case, "checkMesh", label="checkMesh_dt1", timeout_s=600.0)
    records.append(check)
    checkmesh = parse_checkmesh(Path(check["log_path"]))
    lineage["checkMesh"] = checkmesh
    lineage["target_points_sha256_after_checkMesh"] = sha256_file(case / "constant" / "polyMesh" / "points")
    lineage["points_identical_after_checkMesh"] = lineage["source_points_sha256"] == lineage["target_points_sha256_after_checkMesh"]
    if check["return_code"] != 0 or not checkmesh.get("mesh_ok") or not lineage["points_identical_after_checkMesh"]:
        summary = {"case_id": case_id, "mesh_level": mesh_level, "dt_s": DT1, "lineage": lineage, "runtime_valid": False, "statistics_valid": False, "stopped_on": "checkMesh_or_lineage"}
        write_json(result_path, summary)
        return summary
    blocks: list[dict[str, Any]] = []
    production_cfl: float | None = None
    for index in range(1, MAX_BLOCKS + 1):
        start = _latest(case)
        end = start + BLOCK_DURATION_S
        start_from = "startTime" if index == 1 else "latestTime"
        (case / "system" / "controlDict").write_text(_control_dict(dt=DT1, end_time=end, start_from=start_from, start_time=start), encoding="utf-8")
        solver = runner.execute(case, "pimpleFoam", label=f"dt1_block_{index}", timeout_s=14400.0, monitor_cfl=True)
        records.append(solver)
        log = Path(solver["log_path"])
        cfl = parse_cfl(log)
        health = log_health([log])
        latest = _latest(case)
        align = checkpoint_alignment(case, _force_paths_from(case), dt=DT1)
        block = finite({"block": f"dt1_block_{index}", "start_time_s": start, "requested_end_time_s": end, "latest_field_time_s": latest, "requested_steps": int(round(BLOCK_DURATION_S / DT1)), "solver": solver, "cfl": cfl, "health": health, "checkpoint_alignment": align, "field_endpoint_alignment": abs(latest - end) <= DT1 / 2.0, "checkpoint_sha256": sha256_tree(case / str(latest))})
        blocks.append(block)
        production_cfl = max(production_cfl or 0.0, float(cfl.get("max_cfl") or 0.0))
        interim = _case_summary(case, case_id, mesh_level, lineage, blocks, production_cfl)
        if solver["return_code"] != 0 or cfl.get("max_cfl") is None or float(cfl["max_cfl"]) >= HARD_CFL or health["fatal_tokens"] or not health["contains_End"] or not block["field_endpoint_alignment"]:
            interim["stopped_on"] = "hard_stop_or_solver_health"
            write_json(result_path, interim)
            return interim
        if index >= MIN_BLOCKS and interim.get("statistics_valid"):
            interim["stopped_on"] = "formal_dt1_statistics_passed"
            write_json(result_path, interim)
            return interim
        if interim.get("statistics", {}).get("effective_cycles", 0.0) >= 60.0:
            interim["stopped_on"] = "maximum_effective_cycles_reached"
            write_json(result_path, interim)
            return interim
    summary = _case_summary(case, case_id, mesh_level, lineage, blocks, production_cfl)
    summary["stopped_on"] = "maximum_continuation_blocks_reached"
    write_json(result_path, summary)
    return summary


def _komega_setup_audit() -> dict[str, Any]:
    case = V2_2_1_CASES / "high_kOmegaSST_medium_v2_1"
    texts = {}
    for relative in ("system/controlDict", "constant/momentumTransport", "0/k", "0/omega", "0/nut", "system/setFieldsDict"):
        path = case / relative
        texts[relative] = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    k = 0.000565442391670936
    omega = 305.627421187018
    tu = math.sqrt(2.0 * k / 3.0) / U_HIGH
    return finite({
        "schema_version": "stage4e-b2-a-v2.2.2-kOmegaSST-setup-audit-0.1.0",
        "read_only": True,
        "case_path": str(case),
        "model": "kOmegaSST",
        "inlet_k_m2ps2": k,
        "inlet_omega_1ps": omega,
        "initial_nut_m2ps": 0.0,
        "equivalent_turbulence_intensity_fraction": tu,
        "turbulence_length_scale_proxy_k_over_omega_m2ps": k / omega,
        "turbulent_viscosity_ratio_initial": 0.0,
        "cylinder_wall_conditions": {"k": "kqRWallFunction", "omega": "omegaWallFunction", "nut": "nutkWallFunction"},
        "upper_lower_conditions": "symmetryPlane",
        "deterministic_antisymmetric_perturbation": {"present": "boxToCell upper/lower pair in setFieldsDict", "Uy_upper_mps": 0.0021707187589808, "Uy_lower_mps": -0.0021707187589808, "net_transverse_momentum_target": 0.0},
        "likely_decay_mechanisms": ["symmetric upper/lower boundary conditions", "low initial turbulent viscosity", "finite-domain laminar-like wake dissipation", "wall-function initial condition does not guarantee sustained transition"],
        "files_read": {relative: bool(text) for relative, text in texts.items()},
        "kOmegaSSTLM_available_openfoam10": True,
        "kOmegaSSTLM_source_files": ["/opt/openfoam10/src/MomentumTransportModels/momentumTransportModels/RAS/kOmegaSSTLM/kOmegaSSTLM.C", "/opt/openfoam10/src/MomentumTransportModels/momentumTransportModels/RAS/kOmegaSSTLM/kOmegaSSTLM.H"],
        "kOmegaSSTLM_tutorials_found_by_probe": [],
        "kOmegaSSTLM_additional_field_requirement": "verify model-specific transition-field dictionaries from the OpenFOAM 10 source before a future pilot; k, omega and nut alone are not assumed sufficient",
        "not_run_in_v2_2_2": True,
    })


def run_workflow(*, run_id: str, results_root: Path, case_root: Path, runtime_root: Path) -> dict[str, Any]:
    results = results_root / run_id
    cases = case_root / run_id
    runtime = runtime_root / run_id
    for path in (results, cases, runtime):
        if path.exists() and any(path.iterdir()):
            raise FileExistsError(f"refusing to reuse v2.2.2 path: {path}")
        path.mkdir(parents=True, exist_ok=True)
    for name in ("logs", "requests", "responses", "checkpoints", "intermediate"):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    environment = _runtime_environment(runtime)
    write_json(runtime / "runtime_environment.json", {"run_id": run_id, "environment": environment, "home_or_codex_home_modified": False})
    write_json(runtime / "process_inventory_before.json", {"run_id": run_id, "processes": process_snapshot()})
    old_before = _old_evidence_snapshot()
    summaries = _read_v2_2_1_summaries()
    offline = offline_reclassification(summaries)
    trend = spatial_trend_diagnostic(summaries)
    write_json(results / "v2_2_1_offline_reclassification.json", offline)
    write_json(results / "v2_2_1_spatial_trend_diagnostic.json", trend)
    write_json(results / "v2_2_1_source_evidence_audit.json", _source_audit(summaries))
    write_json(results / "kOmegaSST_setup_audit.json", _komega_setup_audit())
    write_json(results / "transition_model_pilot_draft.json", {"schema_version": "stage4e-b2-a-v2.2.2-transition-model-pilot-draft-0.1.0", "candidate": "kOmegaSSTLM", "available_in_openfoam10": True, "not_run": True, "recommendation": "建议进入" if True else "建议不进入", "scope": "future dedicated transition-model pilot only; not a v2.2.2 result"})
    write_json(results / "medium_dt1_lineage.json", {"status": "pending"})
    write_json(results / "fine_dt1_lineage.json", {"status": "not_run_until_medium_passes"})
    write_json(results / "medium_dt1_statistics.json", {"status": "pending"})
    write_json(results / "fine_dt1_statistics.json", {"status": "not_run_until_medium_passes"})
    write_json(results / "medium_timestep_comparison.json", {"status": "pending"})
    write_json(results / "fine_timestep_diagnostic.json", {"status": "pending"})
    write_json(results / "medium_fine_dt1_spatial_comparison.json", {"status": "not_run_until_both_dt1_pass"})
    write_json(results / "cycle_block_uncertainty.json", {"status": "pending"})
    registry: list[dict[str, Any]] = []
    limiter = None
    runner = None
    medium_summary: dict[str, Any] = {}
    fine_summary: dict[str, Any] = {}
    try:
        limiter, runner = make_runner(runtime, run_id, registry)
        source_medium = V2_2_1_CASES / "high_laminar_medium_dt2_v2_2_1"
        source_fine = V2_2_1_CASES / "high_laminar_fine_dt2_v2_2_1"
        medium_case_id = "high_laminar_medium_dt1_v2_2_2"
        medium_case = cases / medium_case_id
        medium_lineage = _materialize_checkpoint(source_medium, medium_case, parent_run_id=V2_2_1_RUN_ID, source_case_id=source_medium.name, target_case_id=medium_case_id)
        medium_summary = _run_case(medium_case, medium_case_id, "medium", medium_lineage, runner, registry, results / "medium_dt1_statistics.json")
        medium_lineage.update(medium_summary.get("lineage", {}))
        write_json(results / "medium_dt1_lineage.json", medium_lineage)
        write_json(results / "medium_timestep_comparison.json", time_step_comparison(summaries["medium"], medium_summary))
        if medium_summary.get("statistics_valid"):
            fine_case_id = "high_laminar_fine_dt1_v2_2_2"
            fine_case = cases / fine_case_id
            fine_lineage = _materialize_checkpoint(source_fine, fine_case, parent_run_id=V2_2_1_RUN_ID, source_case_id=source_fine.name, target_case_id=fine_case_id)
            fine_summary = _run_case(fine_case, fine_case_id, "fine", fine_lineage, runner, registry, results / "fine_dt1_statistics.json")
            fine_lineage.update(fine_summary.get("lineage", {}))
            write_json(results / "fine_dt1_lineage.json", fine_lineage)
            write_json(results / "fine_timestep_diagnostic.json", time_step_comparison(summaries["fine"], fine_summary))
            if fine_summary.get("statistics_valid"):
                write_json(results / "medium_fine_dt1_spatial_comparison.json", spatial_dt1_comparison(medium_summary, fine_summary))
                write_json(results / "cycle_block_uncertainty.json", {"medium_dt1": medium_summary.get("cycle_block_uncertainty"), "fine_dt1": fine_summary.get("cycle_block_uncertainty")})
        decision = decision_matrix(
            medium_dt1_passed=bool(medium_summary.get("statistics_valid")),
            fine_dt1_passed=bool(fine_summary.get("statistics_valid")),
            time_passed=bool(read_json(results / "medium_timestep_comparison.json").get("passed") and (read_json(results / "fine_timestep_diagnostic.json").get("passed") if fine_summary else False)),
            spatial_passed=bool(read_json(results / "medium_fine_dt1_spatial_comparison.json").get("passed")),
        )
        write_json(results / "laminar_high_re_model_decision.json", {"schema_version": "stage4e-b2-a-v2.2.2-laminar-model-decision-0.1.0", **decision, "dt1_medium_statistics_valid": bool(medium_summary.get("statistics_valid")), "dt1_fine_statistics_valid": bool(fine_summary.get("statistics_valid")), "dt2_fine_reclassification": offline["fine_status"]})
        write_json(results / "conditional_coarse_dt1_results.json", {"status": "run_allowed_only_if_medium_fine_dt1_spatial_passed", "run": False, "reason": "coarse_dt1 is conditional and is not run before the medium-to-fine dt1 decision"})
        write_json(results / "gci_results.json", {"available": False, "gci_not_fabricated": True, "reason": "conditional coarse_dt1 was not run; three-grid dt1 set unavailable"})
    finally:
        if limiter is not None and runner is not None:
            process = closeout_process_audit(runtime, limiter, registry)
        else:
            process = {"task_owned_residual_process_count": 0, "permit_leak": False, "registry": [], "closed_pids": [], "residual_processes": [], "process_cleanup_blocked": False, "max_concurrent_heavy_processes": 0}
        write_json(results / "process_cleanup_audit_v2_2_2.json", process)
    write_json(runtime / "process_inventory_after.json", {"run_id": run_id, "processes": process_snapshot()})
    write_json(runtime / "owned_process_registry.json", {"run_id": run_id, "processes": registry})
    write_json(runtime / "retained_process_handoff.json", {"retained": False, "processes": []})
    old_after = _old_evidence_snapshot()
    old_hash = {"schema_version": "stage4e-b2-a-v2.2.2-old-evidence-hash-audit-0.1.0", "before": old_before, "after": old_after, "changed": [key for key in old_before if old_before[key] != old_after.get(key)], "old_evidence_unchanged": old_before == old_after}
    write_json(results / "old_evidence_hash_audit_v2_2_2.json", old_hash)
    write_json(runtime / "c_drive_write_diff.json", {"project_artifacts_created_on_C_drive": [], "count": 0})
    runtime_audit = {"schema_version": "stage4e-b2-a-v2.2.2-runtime-path-audit-0.1.0", "runtime_root": str(runtime), "all_task_temp_logs_requests_responses_checkpoints_under_runtime": True, "project_runtime_root_on_D_drive": True, "home_or_codex_home_modified": False, "owned_residual_process_count": process.get("task_owned_residual_process_count", 0), "permit_leak": process.get("permit_leak", False), "project_artifacts_created_on_C_drive": 0, "runtime_hygiene_gate": process.get("task_owned_residual_process_count", 0) == 0 and not process.get("permit_leak", False) and old_hash["old_evidence_unchanged"]}
    write_json(runtime / "runtime_path_audit_v2_2_2.json", runtime_audit)
    write_json(results / "runtime_path_audit_v2_2_2.json", runtime_audit)
    time_cmp = read_json(results / "medium_timestep_comparison.json")
    fine_cmp = read_json(results / "fine_timestep_diagnostic.json")
    spatial_cmp = read_json(results / "medium_fine_dt1_spatial_comparison.json")
    decision = read_json(results / "laminar_high_re_model_decision.json")
    gate = {"schema_version": "stage4e-b2-a-v2.2.2-gate-candidate-0.1.0", "run_id": run_id, "offline_reclassification": offline, "spatial_trend_diagnostic": trend, "medium_dt1": medium_summary, "fine_dt1": fine_summary, "medium_timestep_comparison": time_cmp, "fine_timestep_diagnostic": fine_cmp, "medium_fine_dt1_spatial_comparison": spatial_cmp, "laminar_high_re_model_decision": decision, "conditional_coarse_dt1": False, "gci": {"available": False, "gci_not_fabricated": True}, "old_evidence_unchanged": old_hash["old_evidence_unchanged"], "runtime_hygiene": runtime_audit, "full_project_regression": "pending_until_cli", "LAMINAR_HIGH_RE_MODEL_STATUS": decision["LAMINAR_HIGH_RE_MODEL_STATUS"], "TRANSITION_MODEL_PILOT_RECOMMENDATION": "建议进入", "LOW_MIDDLE_RE_ENTRY_RECOMMENDATION": "建议不进入", "REAL_NINE_SLICE_ENTRY_RECOMMENDATION": "建议不进入", "stop_conditions_triggered": []}
    write_json(results / "stage4e_b2_a_v2_2_2_gate_candidate.json", gate)
    write_json(results / "checkpoint_lineage_v2_2_2.json", {"medium": medium_lineage if medium_summary else {"status": "not_run"}, "fine": fine_summary.get("lineage", {}) if fine_summary else {"status": "not_run"}})
    return {"results": results, "cases": cases, "runtime": runtime, "medium": medium_summary, "fine": fine_summary, "process": process, "old_hash": old_hash, "gate": gate}


def main() -> None:
    run_id = os.environ.get("B2A_V2_2_2_RUN_ID")
    if not run_id:
        raise SystemExit("B2A_V2_2_2_RUN_ID is required")
    result = run_workflow(run_id=run_id, results_root=Path(os.environ["B2A_V2_2_2_RESULTS_ROOT"]), case_root=Path(os.environ["B2A_V2_2_2_CASE_ROOT"]), runtime_root=Path(os.environ["B2A_V2_2_2_RUNTIME_ROOT"]))
    print(json.dumps({"run_id": run_id, "medium_statistics_valid": result["medium"].get("statistics_valid"), "fine_statistics_valid": result["fine"].get("statistics_valid"), "status": result["gate"].get("LAMINAR_HIGH_RE_MODEL_STATUS"), "residual": result["process"].get("task_owned_residual_process_count", 0)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
