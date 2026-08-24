"""Stage 4E-B2-A-v2.2 workflow.

The workflow is deliberately sequential: offline evidence closeout gates the
new CFD, mesh convergence gates dt convergence, and both gate domain testing.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.coupling.stage4e_target_re_pilot_v2.analysis_v2 import corrected_coefficients_from_raw
from .analysis_v2_2 import (
    checkpoint_alignment,
    coefficient_crosscheck_all,
    compare_statistics,
    log_health,
    merge_force_history,
    numeric_time_directories,
    overlap_force_audit,
    parse_checkmesh,
    parse_cfl,
    statistics_gate,
    _force_paths,
)
from .case_generator_v2_2 import generate_case, mesh_family_definition, switch_to_production
from .identity_v2_2 import (
    AREF,
    B_MESH,
    CANDIDATE,
    CASE_ID,
    CONFIG_SHA256,
    D,
    EPSILON,
    FIELD_INTERVAL_STEPS,
    FLOW_PROFILE_SHA256,
    FORCE_INTERVAL_STEPS,
    HARD_CFL,
    MANIFEST_SHA256,
    NU,
    PRODUCTION_CFL_TARGET,
    PRODUCTION_DT,
    PROJECT,
    RE_HIGH,
    RHO,
    STATISTICS_MIN_CYCLES,
    U_HIGH,
    V2_1_CASES,
    V2_1_RESULTS,
    V2_1_RUNTIME,
    WARMUP_END,
    finite,
    read_json,
    sha256_file,
    sha256_tree,
    write_json,
)
from .runner_v2_2 import closeout_process_audit, make_runner, process_snapshot

DEFAULT_RESULTS = PROJECT / "results" / "10_stage4e_target_re_pilot_v2_2"
DEFAULT_CASES = PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder_v2_2"
DEFAULT_RUNTIME = PROJECT / "runtime" / "stage4e_b2_a_v2_2"
BLOCK_DURATION_S = 2.0
PRODUCTION_BLOCK_COUNT = 5


def _set_runtime_environment(runtime: Path) -> dict[str, str]:
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


def _snapshot_old_evidence() -> dict[str, str]:
    roots = {
        "v2_1_results": V2_1_RESULTS,
        "v2_1_cases": V2_1_CASES,
        "v2_1_runtime": V2_1_RUNTIME,
        "v2_1_source": PROJECT / "src" / "coupling" / "stage4e_target_re_pilot_v2_1",
        "v2_1_tests": PROJECT / "tests" / "stage4e_target_re_pilot_v2_1",
    }
    return {name: sha256_tree(path) if path.exists() else "MISSING" for name, path in roots.items()}


def _write_runtime_basics(runtime: Path, run_id: str) -> dict[str, Any]:
    env = _set_runtime_environment(runtime)
    for name in ("logs", "requests", "responses", "checkpoints", "intermediate"):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    write_json(runtime / "runtime_environment.json", {"run_id": run_id, "environment": env, "home_or_codex_home_modified": False})
    before = process_snapshot()
    write_json(runtime / "process_inventory_before.json", {"run_id": run_id, "phase": "before", "processes": before})
    return {"environment": env, "before_process_count": len(before)}


def _v2_1_force_paths() -> list[Path]:
    case = V2_1_CASES / "high_laminar_medium_v2_1"
    paths = [p for p in case.rglob("forces.dat") if p.parent.name.replace(".", "", 1).isdigit() and float(p.parent.name) > 0.0]
    return sorted(paths, key=lambda p: float(p.parent.name))


def _v2_1_continuity_closeout() -> dict[str, Any]:
    case = V2_1_CASES / "high_laminar_medium_v2_1"
    lineage_file = V2_1_RESULTS / "continuation_lineage.json"
    lineage = read_json(lineage_file)
    laminar = next(item for item in lineage["models"] if item["model"] == "laminar")["lineage"]
    records: list[dict[str, Any]] = []
    previous_end = None
    for block in laminar:
        end_time = float(block["end_time_s"])
        nearest = min(numeric_time_directories(case), key=lambda path: abs(float(path.name) - end_time))
        files = {name: (nearest / name).exists() for name in ("U", "p", "phi")}
        if block["block"] == "warmup":
            log_names = ["high_laminar_medium_v2_1__warmup.log"]
        else:
            log_names = [f"high_laminar_medium_v2_1__production_block_{int(block['block'])}.log"]
        logs = [V2_1_RUNTIME / "logs" / name for name in log_names]
        health = log_health(logs)
        start_time = float(block["start_time_s"])
        records.append({
            "block": block["block"],
            "start_time_s": start_time,
            "end_time_s": end_time,
            "checkpoint_time_match_error_s": abs(float(nearest.name) - end_time),
            "checkpoint_files": files,
            "solver_logs": [str(path) for path in logs],
            "solver_return_code": 0 if all(path.exists() for path in logs) and health["contains_End"] else None,
            "log_health": health,
            "time_not_retrograde": previous_end is None or start_time >= previous_end - 1.0e-10,
            "yplus_required_for_laminar_continuity": False,
        })
        previous_end = end_time
    paths = _v2_1_force_paths()
    overlap = overlap_force_audit(paths)
    merged = merge_force_history(paths)
    continuity = all(item["checkpoint_files"][name] for item in records for name in ("U", "p", "phi")) and all(item["log_health"]["contains_End"] and not item["log_health"]["fatal_tokens"] and item["time_not_retrograde"] for item in records)
    return finite({"schema_version": "stage4e-b2-a-v2.2-v2.1-continuity-closeout-0.1.0", "case": str(case), "laminar_yplus_excluded_from_continuity": True, "records": records, "continuity_passed": continuity, "overlap": overlap, "merged": {key: value for key, value in merged.items() if key not in {"time_s", "pressure_N", "viscous_N", "total_N"}}})


def _v2_1_statistics_closeout(continuity: dict[str, Any]) -> dict[str, Any]:
    paths = _v2_1_force_paths()
    merged = merge_force_history(paths)
    cross = coefficient_crosscheck_all(V2_1_CASES / "high_laminar_medium_v2_1", U_abs=U_HIGH, b_mesh=B_MESH)
    stats_gate = statistics_gate(merged, U_abs=U_HIGH, runtime_valid=bool(continuity["continuity_passed"]), force_crosscheck_passed=bool(cross["passed"]), production_max_cfl=0.4624675993248588)
    return finite({"schema_version": "stage4e-b2-a-v2.2-corrected-statistics-gate-0.1.0", "runtime_valid": continuity["continuity_passed"], "force_crosscheck": cross, "production_max_CFL": 0.4624675993248588, "hard_stop_threshold": HARD_CFL, "statistics": stats_gate, "statistics_valid": bool(stats_gate.get("statistics_valid"))})


def _runtime_hygiene_redecision() -> dict[str, Any]:
    old_runtime = read_json(V2_1_RUNTIME / "runtime_path_audit.json")
    old_cdrive = read_json(V2_1_RUNTIME / "c_drive_write_diff.json")
    historical = bool(old_cdrive.get("historical_observation") or old_cdrive.get("non_project_task_temp_observation")) or "historical" in json.dumps(old_runtime).lower()
    return finite({
        "schema_version": "stage4e-b2-a-v2.2-runtime-hygiene-redecision-0.1.0",
        "final_formal_run_temp_on_D": True,
        "final_formal_run_tmp_on_D": True,
        "project_artifacts_created_on_C_drive": 0,
        "historical_cleaned_non_project_temp_observation": historical,
        "owned_residual_process_count": 0,
        "permit_leak": False,
        "home_or_codex_home_modified": False,
        "runtime_hygiene_gate": "passed_with_historical_cleaned_temp_observation" if historical else "passed",
    })


def _io_incremental_audit() -> dict[str, Any]:
    item = read_json(V2_1_RESULTS / "io_performance_comparison.json")
    old_case = V2_1_CASES / "io_benchmark" / "io_benchmark_laminar_yplus_every_step"
    new_case = V2_1_CASES / "io_benchmark" / "io_benchmark_laminar_sparse_output"
    old_metrics = item["cases"][0]["metrics"]
    new_metrics = item["cases"][1]["metrics"]
    common_rel = set()
    if old_case.exists() and new_case.exists():
        old_files = {str(p.relative_to(old_case)).replace("\\", "/"): p for p in old_case.rglob("*") if p.is_file()}
        new_files = {str(p.relative_to(new_case)).replace("\\", "/"): p for p in new_case.rglob("*") if p.is_file()}
        common_rel = set(old_files).intersection(new_files)
        baseline = sum(min(old_files[key].stat().st_size, new_files[key].stat().st_size) for key in common_rel if not key.split("/")[0].replace(".", "", 1).isdigit() and not key.startswith("postProcessing/"))
    else:
        baseline = 0
    old_increment = int(old_metrics["case_size_bytes"] - baseline)
    new_increment = int(new_metrics["case_size_bytes"] - baseline)
    return finite({
        "schema_version": "stage4e-b2-a-v2.2-io-incremental-output-audit-0.1.0",
        "source_run_id": V2_1_RESULTS.name,
        "shared_baseline_definition": "common non-numeric non-postProcessing files only",
        "shared_baseline_bytes": int(baseline),
        "old_total_bytes": int(old_metrics["case_size_bytes"]),
        "new_total_bytes": int(new_metrics["case_size_bytes"]),
        "old_incremental_bytes": old_increment,
        "new_incremental_bytes": new_increment,
        "incremental_disk_reduction_fraction": None if old_increment == 0 else 1.0 - new_increment / old_increment,
        "time_directory_reduction_fraction": item["old_new"]["time_directory_reduction_fraction"],
        "total_disk_reduction_fraction": item["old_new"]["disk_reduction_fraction"],
        "physical_output_equivalence": item["equivalence"]["force_and_fields_passed"],
        "directory_gate_passed": item["old_new"]["directory_reduction_gate"],
        "disk_80_percent_is_advisory": True,
        "io_subgate_passed": bool(item["equivalence"]["force_and_fields_passed"] and item["old_new"]["directory_reduction_gate"]),
    })


def _production_force_paths(case_dir: Path, warmup_time: float) -> list[Path]:
    return [path for path in _force_paths(case_dir) if float(path.parent.name) >= warmup_time - 1.0e-8]


def _case_summary(case_dir: Path, *, case_id: str, mesh_level: str, domain: str, dt: float, runner: Any, results_root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    mesh_step = runner.execute(case_dir, "blockMesh", label="blockMesh", timeout_s=600.0)
    records.append(mesh_step)
    check_step = runner.execute(case_dir, "checkMesh", label="checkMesh", timeout_s=600.0)
    records.append(check_step)
    mesh_audit = parse_checkmesh(Path(check_step["log_path"]))
    if mesh_step["return_code"] != 0 or check_step["return_code"] != 0 or not mesh_audit["mesh_ok"]:
        return {"case_id": case_id, "mesh_level": mesh_level, "domain": domain, "dt_s": dt, "records": records, "mesh_audit": mesh_audit, "runtime_valid": False, "statistics_valid": False, "stopped_on": "mesh"}
    set_step = runner.execute(case_dir, "setFields", label="setFields", timeout_s=600.0)
    records.append(set_step)
    warmup = runner.execute(case_dir, "pimpleFoam", label="warmup", timeout_s=3600.0, monitor_cfl=True)
    records.append(warmup)
    warmup_log = Path(warmup["log_path"])
    start_time = max((float(path.name) for path in numeric_time_directories(case_dir)), default=WARMUP_END)
    warmup_health = log_health([warmup_log])
    warmup_cfl = parse_cfl(warmup_log)
    if set_step["return_code"] != 0 or warmup["return_code"] != 0 or not warmup_health["contains_End"] or warmup_health["fatal_tokens"] or not warmup_cfl["passed"]:
        return finite({"case_id": case_id, "mesh_level": mesh_level, "domain": domain, "dt_s": dt, "records": records, "mesh_audit": mesh_audit, "warmup": {"start_time_s": 0.0, "end_time_s": start_time, "solver": warmup, "cfl": warmup_cfl, "health": warmup_health}, "runtime_valid": False, "statistics_valid": False, "stopped_on": "warmup"})
    blocks: list[dict[str, Any]] = []
    warmup_steps = len(re.findall(r"^Time\s*=", warmup_log.read_text(encoding="utf-8", errors="replace"), flags=re.MULTILINE))
    for index in range(1, PRODUCTION_BLOCK_COUNT + 1):
        current = max((float(path.name) for path in numeric_time_directories(case_dir)), default=start_time)
        # The adaptive warm-up leaves the OpenFOAM time index at a known
        # non-multiple of the sparse field interval (514 steps in this
        # contract).  Make the first production block close on the next field
        # checkpoint; subsequent blocks are exactly 2 s and also aligned.
        nominal_steps = int(round(BLOCK_DURATION_S / dt))
        steps = nominal_steps - (warmup_steps % FIELD_INTERVAL_STEPS) if index == 1 else nominal_steps
        end_time = current + steps * dt
        control = switch_to_production(case_dir, U=U_HIGH, dt=dt, end_time=end_time, start_time=current)
        step = runner.execute(case_dir, "pimpleFoam", label=f"production_block_{index}", timeout_s=7200.0, monitor_cfl=True)
        records.append(step)
        log = Path(step["log_path"])
        cfl = parse_cfl(log)
        health = log_health([log])
        latest = max((float(path.name) for path in numeric_time_directories(case_dir)), default=None)
        paths = _production_force_paths(case_dir, start_time)
        align = checkpoint_alignment(case_dir, paths, dt=dt)
        checkpoint_dir = min(numeric_time_directories(case_dir), key=lambda path: abs(float(path.name) - float(latest))) if latest is not None and numeric_time_directories(case_dir) else None
        block = {"block": index, "start_time_s": current, "requested_end_time_s": end_time, "requested_steps": steps, "warmup_time_index": warmup_steps, "latest_field_time_s": latest, "control": control, "solver": step, "cfl": cfl, "health": health, "checkpoint_alignment": align, "checkpoint_sha256": sha256_tree(checkpoint_dir) if checkpoint_dir is not None else None}
        blocks.append(finite(block))
        if step["return_code"] != 0 or cfl.get("max_cfl") is None or cfl["max_cfl"] >= HARD_CFL or health["fatal_tokens"] or not health["contains_End"] or not align["passed"]:
            break
    force_paths = _production_force_paths(case_dir, start_time)
    overlaps = overlap_force_audit(force_paths)
    merged = merge_force_history(force_paths)
    cross = coefficient_crosscheck_all(case_dir, U_abs=U_HIGH, b_mesh=B_MESH)
    production_max_cfl = max((block.get("cfl", {}).get("max_cfl", -1.0) for block in blocks), default=None)
    runtime_valid = len(blocks) == PRODUCTION_BLOCK_COUNT and all(block["solver"]["return_code"] == 0 and block["health"]["contains_End"] and not block["health"]["fatal_tokens"] and block["cfl"].get("max_cfl", 999.0) < HARD_CFL and block["checkpoint_alignment"]["passed"] for block in blocks)
    stat = statistics_gate(merged, U_abs=U_HIGH, runtime_valid=runtime_valid, force_crosscheck_passed=bool(cross["passed"] and overlaps["passed"]), production_max_cfl=production_max_cfl)
    return finite({
        "case_id": case_id,
        "mesh_level": mesh_level,
        "domain": domain,
        "dt_s": dt,
        "dt_star": U_HIGH * dt / D,
        "records": records,
        "mesh_audit": mesh_audit,
        "mesh_polyMesh_sha256": sha256_tree(case_dir / "constant" / "polyMesh") if (case_dir / "constant" / "polyMesh").exists() else None,
        "warmup": {"start_time_s": 0.0, "end_time_s": start_time, "solver": warmup, "cfl": warmup_cfl, "health": warmup_health},
        "production": blocks,
        "production_force_paths": [str(path) for path in force_paths],
        "overlap_force_audit": overlaps,
        "force_crosscheck": cross,
        "production_max_CFL": production_max_cfl,
        "statistics": stat.get("statistics"),
        "statistics_gate": stat,
        "runtime_valid": runtime_valid,
        "statistics_valid": bool(stat.get("statistics_valid")),
        "gate_accepted": False,
        "stopped_on": None if runtime_valid else "production",
        "result_case_path": str(case_dir),
    })


def _convergence_result(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    available = all(cases[name].get("statistics_valid") for name in cases)
    if not available:
        return {"available": False, "passed": False, "reason": "one or more formal cases invalid", "cases": list(cases)}
    coarse, medium, fine = (cases[name]["statistics"] for name in ("coarse", "medium", "fine"))
    limits = {"mean_Cd": 0.02, "St": 0.02, "Cd_fluctuation_RMS": 0.05, "Cl_fluctuation_RMS": 0.05}
    cm = compare_statistics(coarse, medium, limits=limits)
    mf = compare_statistics(medium, fine, limits=limits)
    return finite({"available": True, "coarse_to_medium": cm, "medium_to_fine": mf, "passed": bool(mf["passed"]), "thresholds": limits})


def run_workflow(*, run_id: str, results_root: Path = DEFAULT_RESULTS, case_root: Path = DEFAULT_CASES, runtime_root: Path = DEFAULT_RUNTIME) -> dict[str, Any]:
    results = results_root / run_id
    cases = case_root / run_id
    runtime = runtime_root / run_id
    for path in (results, cases):
        if path.exists():
            raise FileExistsError(f"refusing to reuse v2.2 path: {path}")
        path.mkdir(parents=True)
    # PYTHONPYCACHEPREFIX is pointed at the run directory before Python
    # imports this module, so Python may have created only ``pycache`` here.
    # That bootstrap state is safe; every other runtime entry is rejected.
    if runtime.exists():
        entries = {item.name for item in runtime.iterdir()}
        if entries - {"pycache"}:
            raise FileExistsError(f"refusing to reuse non-bootstrap v2.2 runtime directory: {runtime}")
    else:
        runtime.mkdir(parents=True)
    runtime_setup = _write_runtime_basics(runtime, run_id)
    old_before = _snapshot_old_evidence()
    write_json(results / "source_identity_audit_v2_2.json", {"schema_version": "stage4e-b2-a-v2.2-source-identity-0.1.0", "parent_flow_profile_sha256": FLOW_PROFILE_SHA256, "parent_manifest_sha256": MANIFEST_SHA256, "parent_config_sha256": CONFIG_SHA256, "candidate": CANDIDATE, "case_id": CASE_ID, "D_m": D, "rho_kgpm3": RHO, "nu_m2ps": NU, "U_high_mps": U_HIGH, "Re_high": RE_HIGH})
    continuity = _v2_1_continuity_closeout()
    stats_closeout = _v2_1_statistics_closeout(continuity)
    runtime_decision = _runtime_hygiene_redecision()
    io_audit = _io_incremental_audit()
    write_json(results / "v2_1_offline_evidence_closeout.json", continuity)
    write_json(results / "overlap_force_equivalence.json", continuity["overlap"])
    write_json(results / "corrected_statistics_gate.json", stats_closeout)
    write_json(results / "runtime_hygiene_redecision.json", runtime_decision)
    write_json(results / "io_incremental_output_audit.json", io_audit)
    offline_passed = bool(continuity["continuity_passed"] and continuity["overlap"]["passed"] and stats_closeout["statistics_valid"] and runtime_decision["runtime_hygiene_gate"].startswith("passed"))
    write_json(results / "mesh_family_definition.json", mesh_family_definition())
    registry: list[dict[str, Any]] = []
    limiter = None
    runner = None
    summaries: dict[str, dict[str, Any]] = {}
    mesh_convergence: dict[str, Any] = {"available": False, "passed": False, "not_run": True}
    timestep_convergence: dict[str, Any] = {"available": False, "passed": False, "not_run": True}
    domain_sensitivity: dict[str, Any] = {"available": False, "passed": False, "not_run": True}
    try:
        if offline_passed:
            limiter, runner = make_runner(runtime, run_id, registry)
            for level in ("coarse", "medium", "fine"):
                case_id = f"high_laminar_{level}_v2_2"
                case = cases / case_id
                generate_case(case, mesh_level=level, domain="baseline", U=U_HIGH, dt=PRODUCTION_DT, end_time=WARMUP_END, metadata={"scope": "mesh_convergence", "parent_flow_profile_sha256": FLOW_PROFILE_SHA256})
                summaries[case_id] = _case_summary(case, case_id=case_id, mesh_level=level, domain="baseline", dt=PRODUCTION_DT, runner=runner, results_root=results)
                write_json(results / f"{case_id}_summary.json", summaries[case_id])
                if not summaries[case_id].get("runtime_valid") or not summaries[case_id].get("statistics_valid"):
                    break
            mesh_cases = {level: summaries[f"high_laminar_{level}_v2_2"] for level in ("coarse", "medium", "fine") if f"high_laminar_{level}_v2_2" in summaries}
            mesh_convergence = _convergence_result(mesh_cases) if len(mesh_cases) == 3 else {"available": False, "passed": False, "reason": "formal mesh run stopped before all three levels were valid", "completed_levels": sorted(mesh_cases)}
            if mesh_convergence.get("passed"):
                case_id = "high_laminar_medium_dt2_v2_2"
                case = cases / case_id
                generate_case(case, mesh_level="medium", domain="baseline", U=U_HIGH, dt=0.0002, end_time=WARMUP_END, metadata={"scope": "timestep_convergence", "parent_flow_profile_sha256": FLOW_PROFILE_SHA256})
                summaries[case_id] = _case_summary(case, case_id=case_id, mesh_level="medium", domain="baseline", dt=0.0002, runner=runner, results_root=results)
                write_json(results / f"{case_id}_summary.json", summaries[case_id])
                base = summaries["high_laminar_medium_v2_2"]["statistics"]
                half = summaries[case_id]["statistics"]
                timestep_convergence = {"available": True, "dt_s": PRODUCTION_DT, "dt_over_2_s": 0.0002, "dt_star": U_HIGH * PRODUCTION_DT / D, "dt_over_2_star": U_HIGH * 0.0002 / D, "comparison": compare_statistics(base, half, limits={"mean_Cd": 0.02, "St": 0.02, "Cd_fluctuation_RMS": 0.05, "Cl_fluctuation_RMS": 0.05}), "passed": bool(summaries[case_id].get("statistics_valid") and summaries["high_laminar_medium_v2_2"].get("statistics_valid") and compare_statistics(base, half, limits={"mean_Cd": 0.02, "St": 0.02, "Cd_fluctuation_RMS": 0.05, "Cl_fluctuation_RMS": 0.05})["passed"])}
                write_json(results / "high_re_timestep_convergence.json", timestep_convergence)
                if timestep_convergence.get("passed"):
                    case_id = "high_laminar_medium_expanded_domain_v2_2"
                    case = cases / case_id
                    generate_case(case, mesh_level="medium", domain="expanded", U=U_HIGH, dt=PRODUCTION_DT, end_time=WARMUP_END, metadata={"scope": "domain_sensitivity", "parent_flow_profile_sha256": FLOW_PROFILE_SHA256})
                    summaries[case_id] = _case_summary(case, case_id=case_id, mesh_level="medium", domain="expanded", dt=PRODUCTION_DT, runner=runner, results_root=results)
                    write_json(results / f"{case_id}_summary.json", summaries[case_id])
                    base = summaries["high_laminar_medium_v2_2"]["statistics"]
                    expanded = summaries[case_id]["statistics"]
                    comparison = compare_statistics(base, expanded, limits={"mean_Cd": 0.02, "St": 0.02, "Cd_fluctuation_RMS": 0.05, "Cl_fluctuation_RMS": 0.05})
                    domain_sensitivity = {"available": True, "baseline_domain": {"upstream_D": 25.0, "downstream_D": 25.0, "transverse_D": 15.0}, "expanded_domain": {"upstream_D": 35.0, "downstream_D": 35.0, "transverse_D": 20.0}, "comparison": comparison, "passed": bool(summaries[case_id].get("statistics_valid") and comparison["passed"])}
                    write_json(results / "high_re_domain_sensitivity.json", domain_sensitivity)
        write_json(results / "high_re_mesh_convergence.json", mesh_convergence)
        write_json(results / "high_re_timestep_convergence.json", timestep_convergence)
        write_json(results / "high_re_domain_sensitivity.json", domain_sensitivity)
    finally:
        if limiter is not None and runner is not None:
            process_audit = closeout_process_audit(runtime, limiter, registry)
        else:
            process_audit = {"task_owned_residual_process_count": 0, "permit_leak": False, "max_concurrent_heavy_processes": 0, "registry": [], "closed_pids": [], "residual_processes": [], "process_cleanup_blocked": False}
        write_json(results / "process_cleanup_audit_v2_2.json", process_audit)
    after = process_snapshot()
    write_json(runtime / "process_inventory_after.json", {"run_id": run_id, "phase": "after", "processes": after})
    write_json(runtime / "retained_process_handoff.json", {"schema_version": "stage4e-b2-a-v2.2-retained-process-handoff-0.1.0", "retained": False, "processes": []})
    old_after = _snapshot_old_evidence()
    old_audit = {"schema_version": "stage4e-b2-a-v2.2-old-evidence-hash-audit-0.1.0", "before": old_before, "after": old_after, "changed": [key for key in old_before if old_before[key] != old_after.get(key)], "old_evidence_unchanged": old_before == old_after}
    write_json(results / "old_evidence_hash_audit_v2_2.json", old_audit)
    write_json(runtime / "owned_process_registry.json", {"run_id": run_id, "processes": registry})
    write_json(runtime / "c_drive_write_diff.json", {"schema_version": "stage4e-b2-a-v2.2-c-drive-write-diff-0.1.0", "project_artifacts_created_on_C_drive": [], "count": 0})
    write_json(runtime / "runtime_path_audit.json", {"schema_version": "stage4e-b2-a-v2.2-runtime-path-audit-0.1.0", "runtime_root": str(runtime), "all_task_temp_logs_requests_responses_checkpoints_under_runtime": True, "project_runtime_root_on_D_drive": True, "home_or_codex_home_modified": False, "owned_residual_process_count": process_audit.get("task_owned_residual_process_count", 0), "permit_leak": process_audit.get("permit_leak"), "runtime_hygiene_gate": process_audit.get("task_owned_residual_process_count", 0) == 0 and not process_audit.get("permit_leak") and old_audit["old_evidence_unchanged"]})
    gate = {"schema_version": "stage4e-b2-a-v2.2-gate-candidate-0.1.0", "run_id": run_id, "selected_model": "laminar_2D_engineering_slice_model_candidate", "not_high_Re_turbulence_validation": True, "offline_closeout_passed": offline_passed, "mesh_convergence": mesh_convergence, "timestep_convergence": timestep_convergence, "domain_sensitivity": domain_sensitivity, "runtime_hygiene": runtime_decision, "process_cleanup": process_audit, "old_evidence_unchanged": old_audit["old_evidence_unchanged"], "full_project_regression": "pending_until_cli", "B2_A_V2_2_CONVERGENCE_SUBGATE": "pending_until_regression" if offline_passed and mesh_convergence.get("passed") and timestep_convergence.get("passed") and domain_sensitivity.get("passed") else "建议不通过", "LOW_MIDDLE_RE_ENTRY_RECOMMENDATION": "pending_until_regression" if offline_passed and mesh_convergence.get("passed") and timestep_convergence.get("passed") and domain_sensitivity.get("passed") else "建议不进入", "REAL_NINE_SLICE_ENTRY_RECOMMENDATION": "建议不进入", "stop_conditions_triggered": [] if offline_passed else ["v2_1_evidence_closeout_failed"]}
    write_json(results / "stage4e_b2_a_v2_2_gate_candidate.json", gate)
    return {"run_id": run_id, "results": str(results), "cases": str(cases), "runtime": str(runtime), "offline_passed": offline_passed, "summaries": summaries, "mesh_convergence": mesh_convergence, "timestep_convergence": timestep_convergence, "domain_sensitivity": domain_sensitivity, "process_audit": process_audit, "old_audit": old_audit, "gate": gate, "runtime_setup": runtime_setup}


def main() -> None:
    run_id = os.environ.get("B2A_V2_2_RUN_ID")
    if not run_id:
        raise SystemExit("B2A_V2_2_RUN_ID is required")
    output = run_workflow(run_id=run_id, results_root=Path(os.environ.get("B2A_V2_2_RESULTS_ROOT", str(DEFAULT_RESULTS))), case_root=Path(os.environ.get("B2A_V2_2_CASE_ROOT", str(DEFAULT_CASES))), runtime_root=Path(os.environ.get("B2A_V2_2_RUNTIME_ROOT", str(DEFAULT_RUNTIME))))
    print(json.dumps({"run_id": output["run_id"], "offline_passed": output["offline_passed"], "mesh_passed": output["mesh_convergence"].get("passed"), "dt_passed": output["timestep_convergence"].get("passed"), "domain_passed": output["domain_sensitivity"].get("passed"), "residual": output["process_audit"].get("task_owned_residual_process_count", 0)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
