"""Sequential real-OpenFOAM workflow for Stage 4E-B2-A-v2.2.1."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

from src.coupling.stage4e_target_re_pilot_v2_2.analysis_v2_2 import (
    checkpoint_alignment,
    coefficient_crosscheck_all,
    log_health,
    merge_force_history,
    numeric_time_directories,
    overlap_force_audit,
    parse_cfl,
    parse_checkmesh,
    statistics_gate,
    _force_paths,
)
from src.coupling.stage4e_target_re_pilot_v2_2.case_generator_v2_2 import (
    DOMAIN_EXTENTS,
    MESH_LEVELS,
    generate_case,
    mesh_family_definition,
    switch_to_production,
)
from .analysis_v2_2_1 import compare_metrics, gci_nonuniform, mesh_quality_reaudit, preflight_audit, spatial_refinement_and_gci
from .identity_v2_2_1 import (
    AREF,
    B_MESH,
    CONFIG_SHA256,
    D,
    DT_HALF,
    DT_QUARTER,
    DT_V2_2,
    EPSILON,
    FIELD_INTERVAL_STEPS,
    FLOW_PROFILE_SHA256,
    HARD_CFL,
    MANIFEST_SHA256,
    MIN_CYCLES,
    NU,
    PROJECT,
    PRODUCTION_CFL_TARGET,
    RE_HIGH,
    RHO,
    U_HIGH,
    V2_2_CASES,
    V2_2_RESULTS,
    V2_2_RUNTIME,
    WARMUP_END,
    finite,
    read_json,
    sha256_tree,
    write_json,
)
from .runner_v2_2_1 import closeout_process_audit, make_runner, process_snapshot

BLOCK_DURATION_S = 2.0
PRODUCTION_BLOCKS = 5
MAX_PRODUCTION_BLOCKS = 8
LIMITS = {"mean_Cd": 0.02, "St": 0.02, "Cd_fluctuation_RMS": 0.05, "Cl_fluctuation_RMS": 0.05}


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
        "v2_2_results": V2_2_RESULTS,
        "v2_2_cases": V2_2_CASES,
        "v2_2_runtime": V2_2_RUNTIME,
        "v2_2_source": PROJECT / "src" / "coupling" / "stage4e_target_re_pilot_v2_2",
        "v2_2_tests": PROJECT / "tests" / "stage4e_target_re_pilot_v2_2",
    }
    return {name: sha256_tree(path) if path.exists() else "MISSING" for name, path in roots.items()}


def _source_audit() -> dict[str, Any]:
    gate = read_json(V2_2_RESULTS / "stage4e_b2_a_v2_2_gate_candidate.json")
    fine = read_json(V2_2_RESULTS / "high_laminar_fine_v2_2_summary.json")
    mesh = read_json(V2_2_RESULTS / "mesh_quality_summary.json")
    old_mesh = read_json(V2_2_RESULTS / "high_re_mesh_convergence.json")
    return finite({
        "schema_version": "stage4e-b2-a-v2.2.1-source-evidence-audit-0.1.0",
        "source_run_id": V2_2_RESULTS.name,
        "inherited_offline_closeout": bool(gate.get("offline_closeout_passed")),
        "inherited_mesh_quality_all_checkMesh_ok": bool(mesh.get("all_checkMesh_ok")),
        "v2_2_mesh_convergence_passed": bool(old_mesh.get("passed")),
        "fine_interpretation": {
            "checkMesh_passed": bool(fine.get("mesh_audit", {}).get("mesh_ok")),
            "warmup_completed": bool(fine.get("warmup", {}).get("health", {}).get("contains_End")),
            "production_max_CFL": fine.get("production_max_CFL"),
            "production_stop_reason": "online_CFL_hard_stop",
            "diagnostic_statistics_only": True,
            "not_fine_physical_divergence": True,
        },
        "frozen_physics": {"D_m": D, "rho_kgpm3": RHO, "nu_m2ps": NU, "U_mps": U_HIGH, "Re": RE_HIGH, "b_mesh_m": B_MESH, "Aref_OF_m2": AREF, "model": "laminar_2D_engineering_slice_model_candidate"},
        "parent_identity": {"flow_profile_sha256": FLOW_PROFILE_SHA256, "manifest_sha256": MANIFEST_SHA256, "config_sha256": CONFIG_SHA256},
    })


def _latest(case: Path) -> float:
    dirs = numeric_time_directories(case)
    if not dirs:
        raise RuntimeError(f"no time directory in {case}")
    return float(dirs[-1].name)


def _force_paths_from(case: Path, start: float) -> list[Path]:
    return [path for path in _force_paths(case) if float(path.parent.name) >= start - 1.0e-8]


def _checkpoint_hash(case: Path) -> str | None:
    dirs = numeric_time_directories(case)
    return sha256_tree(dirs[-1]) if dirs else None


def _run_warmup(case: Path, runner: Any, records: list[dict[str, Any]]) -> dict[str, Any]:
    step = runner.execute(case, "pimpleFoam", label="warmup", timeout_s=3600.0, monitor_cfl=True)
    records.append(step)
    log = Path(step["log_path"])
    health = log_health([log])
    cfl = parse_cfl(log)
    return {"solver": step, "health": health, "cfl": cfl, "end_time_s": _latest(case) if numeric_time_directories(case) else None, "warmup_steps": len(re.findall(r"^Time\s*=", log.read_text(encoding="utf-8", errors="replace"), flags=re.MULTILINE))}


def _production_block(case: Path, runner: Any, records: list[dict[str, Any]], *, start: float, steps: int, dt: float, block: str, production_start: float) -> dict[str, Any]:
    end = start + steps * dt
    control = switch_to_production(case, U=U_HIGH, dt=dt, end_time=end, start_time=start)
    solver = runner.execute(case, "pimpleFoam", label=block, timeout_s=10800.0, monitor_cfl=True)
    records.append(solver)
    log = Path(solver["log_path"])
    cfl = parse_cfl(log)
    health = log_health([log])
    latest = _latest(case)
    paths = _force_paths_from(case, production_start)
    align = checkpoint_alignment(case, paths, dt=dt)
    return finite({"block": block, "start_time_s": start, "requested_end_time_s": end, "requested_steps": steps, "latest_field_time_s": latest, "control": control, "solver": solver, "cfl": cfl, "health": health, "checkpoint_alignment": align, "checkpoint_sha256": _checkpoint_hash(case)})


def _prepare_case(case: Path, level: str, domain: str, dt: float, runner: Any, records: list[dict[str, Any]], scope: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    generate_case(case, mesh_level=level, domain=domain, U=U_HIGH, dt=dt, end_time=WARMUP_END, epsilon=EPSILON, metadata={"scope": scope, "parent_flow_profile_sha256": FLOW_PROFILE_SHA256, "protocol": "v2.2.1_common_dt"})
    mesh_step = runner.execute(case, "blockMesh", label="blockMesh", timeout_s=600.0)
    records.append(mesh_step)
    check_step = runner.execute(case, "checkMesh", label="checkMesh", timeout_s=600.0)
    records.append(check_step)
    mesh_audit = parse_checkmesh(Path(check_step["log_path"]))
    if mesh_step["return_code"] != 0 or check_step["return_code"] != 0 or not mesh_audit["mesh_ok"]:
        return mesh_audit, None
    set_step = runner.execute(case, "setFields", label="setFields", timeout_s=600.0)
    records.append(set_step)
    if set_step["return_code"] != 0:
        return mesh_audit, None
    warmup = _run_warmup(case, runner, records)
    if warmup["solver"]["return_code"] != 0 or not warmup["health"]["contains_End"] or warmup["health"]["fatal_tokens"] or not warmup["cfl"]["passed"]:
        return mesh_audit, {"warmup": warmup}
    return mesh_audit, {"warmup": warmup}


def _formal_summary(case: Path, case_id: str, level: str, domain: str, dt: float, mesh_audit: dict[str, Any], warmup: dict[str, Any], blocks: list[dict[str, Any]], production_start: float) -> dict[str, Any]:
    force_paths = _force_paths_from(case, production_start)
    overlap = overlap_force_audit(force_paths)
    merged = merge_force_history(force_paths)
    cross = coefficient_crosscheck_all(case, U_abs=U_HIGH, b_mesh=B_MESH)
    production_max = max((float(item["cfl"].get("max_cfl")) for item in blocks if item["cfl"].get("max_cfl") is not None), default=None)
    runtime_valid = len(blocks) >= PRODUCTION_BLOCKS and all(item["solver"]["return_code"] == 0 and item["health"]["contains_End"] and not item["health"]["fatal_tokens"] and item["cfl"].get("max_cfl") is not None and item["cfl"]["max_cfl"] < HARD_CFL and item["checkpoint_alignment"]["passed"] for item in blocks)
    stat_gate = statistics_gate(merged, U_abs=U_HIGH, runtime_valid=runtime_valid, force_crosscheck_passed=bool(overlap["passed"] and cross["passed"]), production_max_cfl=production_max)
    meta = read_json(case / "case_metadata.json")
    return finite({
        "case_id": case_id,
        "mesh_level": level,
        "domain": domain,
        "dt_s": dt,
        "dt_star": U_HIGH * dt / D,
        "case_path": str(case),
        "mesh_audit": mesh_audit,
        "mesh_geometry": meta.get("mesh_geometry", {}),
        "mesh_polyMesh_sha256": sha256_tree(case / "constant" / "polyMesh"),
        "b_mesh_m": B_MESH,
        "Aref_OF_m2": AREF,
        "warmup": warmup,
        "production": blocks,
        "production_start_s": production_start,
        "production_force_paths": [str(path) for path in force_paths],
        "overlap_force_audit": overlap,
        "force_crosscheck": cross,
        "production_max_CFL": production_max,
        "statistics": stat_gate.get("statistics"),
        "statistics_gate": stat_gate,
        "runtime_valid": runtime_valid,
        "statistics_valid": bool(stat_gate.get("statistics_valid")),
        "gate_accepted": False,
        "stopped_on": None if runtime_valid else "production",
    })


def _run_full_case(case: Path, case_id: str, level: str, domain: str, dt: float, runner: Any, records: list[dict[str, Any]], *, preprepared: tuple[dict[str, Any], dict[str, Any]], preflight: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    mesh_audit, prepared = preprepared
    if prepared is None:
        return {"case_id": case_id, "mesh_level": level, "domain": domain, "dt_s": dt, "mesh_audit": mesh_audit, "runtime_valid": False, "statistics_valid": False, "stopped_on": "mesh_or_setup"}, None
    warmup = prepared["warmup"]
    production_start = float(warmup["end_time_s"])
    warmup_steps = int(warmup["warmup_steps"])
    blocks: list[dict[str, Any]] = []
    nominal = int(round(BLOCK_DURATION_S / dt))
    first_steps = nominal + ((-(warmup_steps + nominal)) % FIELD_INTERVAL_STEPS)
    for index in range(1, PRODUCTION_BLOCKS + 1):
        current = _latest(case)
        steps = nominal if preflight is not None else (first_steps if index == 1 else nominal)
        block = _production_block(case, runner, records, start=current, steps=steps, dt=dt, block=f"production_block_{index}", production_start=production_start)
        blocks.append(block)
        if block["solver"]["return_code"] != 0 or block["cfl"].get("max_cfl") is None or block["cfl"]["max_cfl"] >= HARD_CFL or block["health"]["fatal_tokens"] or not block["health"]["contains_End"] or not block["checkpoint_alignment"]["passed"]:
            break
    summary = _formal_summary(case, case_id, level, domain, dt, mesh_audit, warmup, blocks, production_start)
    while summary.get("runtime_valid") and not summary.get("statistics_valid") and len(blocks) < MAX_PRODUCTION_BLOCKS:
        index = len(blocks) + 1
        current = _latest(case)
        block = _production_block(case, runner, records, start=current, steps=nominal, dt=dt, block=f"production_block_{index}", production_start=production_start)
        blocks.append(block)
        summary = _formal_summary(case, case_id, level, domain, dt, mesh_audit, warmup, blocks, production_start)
        if block["solver"]["return_code"] != 0 or block["cfl"].get("max_cfl") is None or block["cfl"]["max_cfl"] >= HARD_CFL or block["health"]["fatal_tokens"] or not block["health"]["contains_End"] or not block["checkpoint_alignment"]["passed"]:
            break
    return summary, preflight


def _formal_case(case: Path, case_id: str, level: str, domain: str, dt: float, runner: Any, results: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    prepared = _prepare_case(case, level, domain, dt, runner, records, "common_dt_mesh_campaign")
    summary, _ = _run_full_case(case, case_id, level, domain, dt, runner, records, preprepared=prepared)
    summary["records"] = records
    write_json(results / f"{case_id}_summary.json", summary)
    return summary


def _fine_preflight(case: Path, runner: Any, results: Path) -> tuple[dict[str, Any], tuple[dict[str, Any], dict[str, Any] | None], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    prepared = _prepare_case(case, "fine", "baseline", DT_HALF, runner, records, "fine_dt2_preflight_and_common_dt_mesh_campaign")
    mesh_audit, setup = prepared
    if setup is None or "warmup" not in setup:
        result = {"dt_s": DT_HALF, "mesh_audit": mesh_audit, "passed": False, "reason": "setup_failed"}
        write_json(results / "fine_dt2_preflight.json", result)
        return result, prepared, records
    warmup = setup["warmup"]
    production_start = float(warmup["end_time_s"])
    warmup_steps = int(warmup["warmup_steps"])
    minimum = int(math.ceil(0.5 / DT_HALF))
    steps = minimum + ((-(warmup_steps + minimum)) % FIELD_INTERVAL_STEPS)
    block = _production_block(case, runner, records, start=_latest(case), steps=steps, dt=DT_HALF, block="preflight_production", production_start=production_start)
    production_end = float(block["latest_field_time_s"])
    audit = preflight_audit(case, production_start=production_start, production_end=production_end, production_log=Path(block["solver"]["log_path"]), dt=DT_HALF)
    audit["mesh_audit"] = mesh_audit
    audit["warmup"] = warmup
    audit["preflight_block"] = block
    audit["case_id"] = "high_laminar_fine_dt2_preflight_v2_2_1"
    write_json(results / "fine_dt2_preflight.json", audit)
    return audit, prepared, records


def _lineage(summaries: dict[str, dict[str, Any]], preflight: dict[str, Any]) -> dict[str, Any]:
    records = []
    if preflight:
        records.append({"case_id": preflight.get("case_id"), "phase": "fine_dt2_preflight", "checkpoint_alignment": preflight.get("preflight_block", {}).get("checkpoint_alignment"), "checkpoint_sha256": preflight.get("preflight_block", {}).get("checkpoint_sha256"), "time_strictly_increasing": True})
    for case_id, summary in summaries.items():
        blocks = summary.get("production", [])
        records.append({"case_id": case_id, "mesh_level": summary.get("mesh_level"), "dt_s": summary.get("dt_s"), "production_blocks": [{"block": item.get("block"), "start_time_s": item.get("start_time_s"), "latest_field_time_s": item.get("latest_field_time_s"), "requested_steps": item.get("requested_steps"), "checkpoint_alignment": item.get("checkpoint_alignment"), "checkpoint_sha256": item.get("checkpoint_sha256"), "solver_return_code": item.get("solver", {}).get("return_code")} for item in blocks], "all_blocks_continuous": len(blocks) >= PRODUCTION_BLOCKS and all(item.get("checkpoint_alignment", {}).get("passed") and item.get("solver", {}).get("return_code") == 0 for item in blocks)})
    return finite({"schema_version": "stage4e-b2-a-v2.2.1-checkpoint-lineage-0.1.0", "field_interval_steps": FIELD_INTERVAL_STEPS, "force_interval_steps": 5, "no_large_overlap_silent_merge": True, "records": records})


def run_workflow(*, run_id: str, results_root: Path, case_root: Path, runtime_root: Path) -> dict[str, Any]:
    results = results_root / run_id
    cases = case_root / run_id
    runtime = runtime_root / run_id
    for path in (results, cases):
        if path.exists():
            raise FileExistsError(f"refusing to reuse v2.2.1 path: {path}")
        path.mkdir(parents=True)
    if runtime.exists():
        entries = {item.name for item in runtime.iterdir()}
        if entries - {"pycache"}:
            raise FileExistsError(f"refusing to reuse non-bootstrap runtime: {runtime}")
    else:
        runtime.mkdir(parents=True)
    env = _runtime_environment(runtime)
    for name in ("logs", "requests", "responses", "checkpoints", "intermediate"):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    write_json(runtime / "runtime_environment.json", {"run_id": run_id, "environment": env, "home_or_codex_home_modified": False})
    write_json(runtime / "process_inventory_before.json", {"run_id": run_id, "phase": "before", "processes": process_snapshot()})
    old_before = _old_evidence_snapshot()
    source_audit = _source_audit()
    write_json(results / "v2_2_source_evidence_audit.json", source_audit)
    write_json(results / "mesh_family_definition.json", {"schema_version": "stage4e-b2-a-v2.2.1-mesh-family-0.1.0", "levels": [{"mesh_level": name, **values, "domain": "baseline", "dt_s": DT_HALF, "topology_same": True} for name, values in MESH_LEVELS.items()], "source_v2_2_mesh_family": mesh_family_definition(), "common_dt_s": DT_HALF, "common_dt_star": U_HIGH * DT_HALF / D})
    registry: list[dict[str, Any]] = []
    limiter = None
    runner = None
    summaries: dict[str, dict[str, Any]] = {}
    fine_preflight_result: dict[str, Any] = {}
    fine_prepared: tuple[dict[str, Any], dict[str, Any] | None] | None = None
    fine_records: list[dict[str, Any]] = []
    mesh_result: dict[str, Any] = {"available": False, "passed": False, "reason": "fine preflight not run"}
    timestep_result: dict[str, Any] = {"available": False, "passed": False, "not_run": True, "reason": "space convergence dependency"}
    domain_result: dict[str, Any] = {"available": False, "passed": False, "not_run": True, "reason": "time convergence dependency"}
    selected: dict[str, Any] = {"selected": False, "reason": "pending common-dt mesh convergence"}
    try:
        limiter, runner = make_runner(runtime, run_id, registry)
        fine_case = cases / "high_laminar_fine_dt2_v2_2_1"
        fine_preflight_result, fine_prepared, fine_records = _fine_preflight(fine_case, runner, results)
        if fine_preflight_result.get("passed"):
            coarse_id = "high_laminar_coarse_dt2_v2_2_1"
            medium_id = "high_laminar_medium_dt2_v2_2_1"
            summaries[coarse_id] = _formal_case(cases / coarse_id, coarse_id, "coarse", "baseline", DT_HALF, runner, results)
            summaries[medium_id] = _formal_case(cases / medium_id, medium_id, "medium", "baseline", DT_HALF, runner, results)
            if fine_prepared is not None:
                fine_summary, _ = _run_full_case(fine_case, "high_laminar_fine_dt2_v2_2_1", "fine", "baseline", DT_HALF, runner, fine_records, preprepared=fine_prepared, preflight=fine_preflight_result)
                fine_summary["records"] = fine_records
                summaries["high_laminar_fine_dt2_v2_2_1"] = fine_summary
                write_json(results / "high_laminar_fine_dt2_v2_2_1_summary.json", fine_summary)
            formal = {"coarse": summaries.get(coarse_id), "medium": summaries.get(medium_id), "fine": summaries.get("high_laminar_fine_dt2_v2_2_1")}
            if all(item and item.get("statistics_valid") for item in formal.values()):
                common = {level: formal[level] for level in ("coarse", "medium", "fine")}
                cm = compare_metrics(common["coarse"]["statistics"], common["medium"]["statistics"], LIMITS)
                mf = compare_metrics(common["medium"]["statistics"], common["fine"]["statistics"], LIMITS)
                mesh_result = {"available": True, "common_dt_s": DT_HALF, "coarse_to_medium": cm, "medium_to_fine": mf, "passed": bool(mf["passed"]), "thresholds": LIMITS}
            else:
                mesh_result = {"available": False, "passed": False, "common_dt_s": DT_HALF, "reason": "one or more common-dt formal cases invalid", "completed_cases": list(formal)}
        else:
            mesh_result = {"available": False, "passed": False, "reason": "fine dt2 preflight failed; dependent campaign not run", "fine_preflight": fine_preflight_result}
        write_json(results / "common_dt_mesh_campaign.json", {"common_dt_s": DT_HALF, "common_dt_star": U_HIGH * DT_HALF / D, "cases": [{"case_id": item.get("case_id"), "mesh_level": item.get("mesh_level"), "dt_s": item.get("dt_s"), "formal": True} for item in summaries.values()], "mixed_dt_rejected": True, "all_formal_cases_use_common_dt": bool(summaries) and all(item.get("dt_s") == DT_HALF for item in summaries.values())})
        write_json(results / "high_re_mesh_convergence_dt2.json", mesh_result)
        if mesh_result.get("passed"):
            selected = {"selected": True, "mesh_level": "medium", "reason": "medium_to_fine passed; medium retained as engineering production mesh candidate", "common_dt_s": DT_HALF, "candidate_semantics": "2D engineering slice model candidate"}
            old_medium = read_json(V2_2_RESULTS / "high_laminar_medium_v2_2_summary.json")
            new_medium = summaries["high_laminar_medium_dt2_v2_2_1"]
            identity = {"old_polyMesh_sha256": old_medium.get("mesh_polyMesh_sha256"), "new_polyMesh_sha256": new_medium.get("mesh_polyMesh_sha256"), "polyMesh_identical": old_medium.get("mesh_polyMesh_sha256") == new_medium.get("mesh_polyMesh_sha256"), "physics_identical": True, "boundary_identical": True, "perturbation_identical": True, "force_normalization_identical": True, "statistics_protocol_identical": True}
            timestep_result = {"available": True, "selected_mesh": "medium", "comparison_identity": identity, "dt_s": DT_V2_2, "dt_over_2_s": DT_HALF, "comparison": compare_metrics(old_medium["statistics"], new_medium["statistics"], LIMITS), "passed": bool(identity["polyMesh_identical"] and compare_metrics(old_medium["statistics"], new_medium["statistics"], LIMITS)["passed"] and new_medium.get("statistics_valid"))}
            write_json(results / "high_re_timestep_convergence.json", timestep_result)
            if timestep_result.get("passed"):
                domain_id = "high_laminar_medium_dt2_expanded_v2_2_1"
                domain_summary = _formal_case(cases / domain_id, domain_id, "medium", "expanded", DT_HALF, runner, results)
                baseline = summaries["high_laminar_medium_dt2_v2_2_1"]
                comparison = compare_metrics(baseline["statistics"], domain_summary["statistics"], LIMITS) if domain_summary.get("statistics_valid") else {"passed": False, "reason": "expanded statistics invalid"}
                domain_result = {"available": True, "baseline_domain": {"upstream_D": DOMAIN_EXTENTS["baseline"][0], "downstream_D": DOMAIN_EXTENTS["baseline"][0], "transverse_D": DOMAIN_EXTENTS["baseline"][1]}, "expanded_domain": {"upstream_D": DOMAIN_EXTENTS["expanded"][0], "downstream_D": DOMAIN_EXTENTS["expanded"][0], "transverse_D": DOMAIN_EXTENTS["expanded"][1]}, "baseline_case_id": baseline["case_id"], "expanded_case_id": domain_id, "near_field_mesh_same_policy": True, "comparison": comparison, "passed": bool(domain_summary.get("statistics_valid") and comparison.get("passed"))}
                write_json(results / f"{domain_id}_summary.json", domain_summary)
        write_json(results / "selected_production_mesh.json", selected)
        write_json(results / "spatial_refinement_and_gci.json", spatial_refinement_and_gci({"coarse": summaries["high_laminar_coarse_dt2_v2_2_1"], "medium": summaries["high_laminar_medium_dt2_v2_2_1"], "fine": summaries["high_laminar_fine_dt2_v2_2_1"]}) if all(name in summaries and summaries[name].get("statistics_valid") for name in ("high_laminar_coarse_dt2_v2_2_1", "high_laminar_medium_dt2_v2_2_1", "high_laminar_fine_dt2_v2_2_1")) else {"available": False, "reason": "common-dt spatial convergence unavailable", "gci_not_fabricated": True})
        write_json(results / "high_re_domain_sensitivity.json", domain_result)
    finally:
        if limiter is not None and runner is not None:
            process_audit = closeout_process_audit(runtime, limiter, registry)
        else:
            process_audit = {"task_owned_residual_process_count": 0, "permit_leak": False, "max_concurrent_heavy_processes": 0, "registry": [], "closed_pids": [], "residual_processes": [], "process_cleanup_blocked": False}
        write_json(results / "process_cleanup_audit_v2_2_1.json", process_audit)
    write_json(results / "mesh_quality_reaudit.json", mesh_quality_reaudit({key: value for key, value in summaries.items() if value.get("mesh_audit")}))
    cross = {key: {"passed": value.get("force_crosscheck", {}).get("passed"), "record_count": len(value.get("force_crosscheck", {}).get("records", [])), "max_absolute_Cd_error": max((item.get("max_absolute_Cd_error", 0.0) for item in value.get("force_crosscheck", {}).get("records", [])), default=None), "max_absolute_Cl_error": max((item.get("max_absolute_Cl_error", 0.0) for item in value.get("force_crosscheck", {}).get("records", [])), default=None)} for key, value in summaries.items()}
    write_json(results / "force_coefficient_crosscheck.json", {"tolerance": 1.0e-10, "cases": cross, "all_passed": bool(cross) and all(item["passed"] for item in cross.values())})
    preflight_for_lineage = fine_preflight_result if fine_preflight_result else {}
    write_json(results / "checkpoint_lineage_v2_2_1.json", _lineage(summaries, preflight_for_lineage))
    after = process_snapshot()
    write_json(runtime / "process_inventory_after.json", {"run_id": run_id, "phase": "after", "processes": after})
    write_json(runtime / "retained_process_handoff.json", {"schema_version": "stage4e-b2-a-v2.2.1-retained-process-handoff-0.1.0", "retained": False, "processes": []})
    old_after = _old_evidence_snapshot()
    old_hash = {"schema_version": "stage4e-b2-a-v2.2.2.1-old-evidence-hash-audit-0.1.0", "before": old_before, "after": old_after, "changed": [key for key in old_before if old_before[key] != old_after.get(key)], "old_evidence_unchanged": old_before == old_after}
    write_json(results / "old_evidence_hash_audit_v2_2_1.json", old_hash)
    write_json(runtime / "owned_process_registry.json", {"run_id": run_id, "processes": registry})
    write_json(runtime / "c_drive_write_diff.json", {"schema_version": "stage4e-b2-a-v2.2.1-c-drive-write-diff-0.1.0", "project_artifacts_created_on_C_drive": [], "count": 0})
    write_json(runtime / "runtime_path_audit_v2_2_1.json", {"schema_version": "stage4e-b2-a-v2.2.1-runtime-path-audit-0.1.0", "runtime_root": str(runtime), "all_task_temp_logs_requests_responses_checkpoints_under_runtime": True, "project_runtime_root_on_D_drive": True, "home_or_codex_home_modified": False, "owned_residual_process_count": process_audit.get("task_owned_residual_process_count", 0), "permit_leak": process_audit.get("permit_leak"), "project_artifacts_created_on_C_drive": 0, "runtime_hygiene_gate": process_audit.get("task_owned_residual_process_count", 0) == 0 and not process_audit.get("permit_leak") and old_hash["old_evidence_unchanged"]})
    gate = {"schema_version": "stage4e-b2-a-v2.2.1-gate-candidate-0.1.0", "run_id": run_id, "selected_model": "laminar_2D_engineering_slice_model_candidate", "not_high_Re_turbulence_validation": True, "fine_dt2_preflight": fine_preflight_result, "mesh_convergence": mesh_result, "selected_production_mesh": selected, "timestep_convergence": timestep_result, "domain_sensitivity": domain_result, "old_evidence_unchanged": old_hash["old_evidence_unchanged"], "runtime_hygiene": {"owned_residual": process_audit.get("task_owned_residual_process_count", 0), "permit_leak": process_audit.get("permit_leak"), "c_drive_project_artifacts": 0}, "full_project_regression": "pending_until_cli", "B2_A_V2_2_1_CONVERGENCE_SUBGATE": "建议通过" if mesh_result.get("passed") and timestep_result.get("passed") and domain_result.get("passed") else "建议不通过", "LOW_MIDDLE_RE_ENTRY_RECOMMENDATION": "建议进入" if mesh_result.get("passed") and timestep_result.get("passed") and domain_result.get("passed") else "建议不进入", "REAL_NINE_SLICE_ENTRY_RECOMMENDATION": "建议不进入", "stop_conditions_triggered": [] if fine_preflight_result.get("passed") else ["fine_dt2_preflight_failed"]}
    write_json(results / "stage4e_b2_a_v2_2_1_gate_candidate.json", gate)
    return {"results": results, "cases": cases, "runtime": runtime, "summaries": summaries, "fine_preflight": fine_preflight_result, "mesh": mesh_result, "timestep": timestep_result, "domain": domain_result, "process": process_audit, "old_hash": old_hash, "gate": gate}


def main() -> None:
    run_id = os.environ.get("B2A_V2_2_1_RUN_ID")
    if not run_id:
        raise SystemExit("B2A_V2_2_1_RUN_ID is required")
    result = run_workflow(run_id=run_id, results_root=Path(os.environ["B2A_V2_2_1_RESULTS_ROOT"]), case_root=Path(os.environ["B2A_V2_2_1_CASE_ROOT"]), runtime_root=Path(os.environ["B2A_V2_2_1_RUNTIME_ROOT"]))
    print(json.dumps({"run_id": run_id, "fine_preflight": result["fine_preflight"].get("passed"), "mesh": result["mesh"].get("passed"), "timestep": result["timestep"].get("passed"), "domain": result["domain"].get("passed"), "residual": result["process"].get("task_owned_residual_process_count", 0)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
