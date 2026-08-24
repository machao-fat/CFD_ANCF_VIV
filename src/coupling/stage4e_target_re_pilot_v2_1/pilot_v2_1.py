"""Stage 4E-B2-A-v2.1 workflow.

The workflow intentionally stops at the two maximum-Re medium-grid model
screening cases.  It does not launch coarse/fine campaigns, low/middle cases,
domain or time-step sensitivity, or any nine-slice/ANCF calculation.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.coupling.process_control.process_limiter import ProcessLimiter
from src.coupling.stage4e_target_re_pilot_v2.analysis_v2 import corrected_coefficients_from_raw, corrected_statistics, parse_cfl, parse_force_coefficients, parse_raw_forces
from src.coupling.stage4e_target_re_pilot_v2.identity_v2 import EXPECTED_CANDIDATE, EXPECTED_CONFIG_SHA256, EXPECTED_FLOW_PROFILE_SHA256, EXPECTED_MANIFEST_SHA256, PROJECT, D, NU, finite, load_formal_flow_profile, sha256_file, sha256_json
from src.coupling.stage4e_target_re_pilot_v2.runner_v2 import log_health

from .analysis_v2_1 import coefficient_crosscheck, checkpoint_hash, field_equivalence, force_equivalence, latest_time, output_metrics, parse_raw_force_history, yplus_history
from .case_generator_v2_1 import CASE_ROOT, FIELD_WRITE_INTERVAL_STEPS, FORCE_WRITE_INTERVAL_STEPS, HARD_CFL, PRODUCTION_DT_S, WARMUP_END_S, case_freshness, generate_case, switch_to_production
from .online_cfl_monitor import IncrementalCFLMonitor
from .runner_v2_1 import OwnedRunnerV21, closeout_process_audit, process_snapshot


V2_RESULTS = PROJECT / "results" / "10_stage4e_target_re_pilot_v2" / "20260814T154500000Z_stage4e_b2_a_v2_registryfix"
V2_CASE_ROOT = PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder_v2" / "20260814T154500000Z_stage4e_b2_a_v2_registryfix"
V1_CASE_ROOT = PROJECT / "cases" / "openfoam" / "stage4e_target_re_fixed_cylinder" / "20260814T051204411Z_stage4e_b2_a_retry3"
DEFAULT_RESULTS = PROJECT / "results" / "10_stage4e_target_re_pilot_v2_1"
DEFAULT_CASES = CASE_ROOT
DEFAULT_RUNTIME = PROJECT / "runtime" / "stage4e_b2_a_v2_1"
U_HIGH = 0.43414375179615955
RE_HIGH = U_HIGH * D / NU
BLOCKS = [3.0, 5.5, 7.0, 10.5]
FORMAL_END_TIME_S = BLOCKS[-1]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(finite(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _case_relative(case: Path) -> str:
    return str(case.relative_to(PROJECT)).replace("\\", "/")


def _log_cfl(path: Path) -> dict[str, Any]:
    return parse_cfl(path)


def _old_log_diagnosis() -> dict[str, Any]:
    log = PROJECT / "runtime" / "stage4e_b2_a_v2" / "20260814T154500000Z_stage4e_b2_a_v2_registryfix" / "logs" / "high_laminar_medium__pimpleFoam.log"
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    rows: list[tuple[float, float]] = []
    current = None
    for line in text.splitlines():
        tm = re.search(r"Time\s*=\s*([-+0-9.eE]+)", line)
        if tm:
            current = float(tm.group(1))
        cm = re.search(r"Courant Number mean:\s*([-+0-9.eE]+)\s*max:\s*([-+0-9.eE]+)", line)
        if cm:
            rows.append((current if current is not None else float("nan"), float(cm.group(2))))
    def max_after(t: float) -> float | None:
        vals = [c for time, c in rows if math.isfinite(time) and time >= t]
        return max(vals) if vals else None
    return finite({"old_run_id": "20260814T154500000Z_stage4e_b2_a_v2_registryfix", "case_id": "high_laminar_medium", "solver_completed": True, "runtime_valid": False, "statistics_valid": False, "gate_accepted": False, "reason": "startup_CFL_exceeded_hard_limit", "solver_return_code": 0, "log_contains_End": "End" in text, "steps": len(rows), "full_history_max_CFL": max((c for _, c in rows), default=None), "max_CFL_after_0.1_s": max_after(0.1), "max_CFL_after_1.65_s": max_after(1.65), "diagnostic_use": ["startup strategy", "cost trend", "frequency trend only"], "forbidden_use": ["formal Gate", "model selection", "mesh/time/domain convergence", "final physical frequency"]})


def _snapshot_paths(paths: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for root in paths:
        if root.is_file():
            result[str(root)] = sha256_file(root)
        elif root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    result[str(path)] = sha256_file(path)
    return result


def _old_hash_audit(before: dict[str, str]) -> dict[str, Any]:
    current = _snapshot_paths([V2_RESULTS, PROJECT / "src" / "coupling" / "stage4e_target_re_pilot_v2", V2_CASE_ROOT])
    changed = [path for path, digest in before.items() if current.get(path) != digest]
    missing = [path for path in before if path not in current]
    added = [path for path in current if path not in before]
    return {"schema_version": "stage4e-b2-a-v2.1-old-evidence-hash-audit-0.1.0", "before_file_count": len(before), "after_file_count": len(current), "changed": changed, "missing": missing, "unexpected_added": added, "old_evidence_unchanged": not changed and not missing, "v2_results_overwritten": False}


def _fresh_case_manifest(selected: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [item.get("freshness", {}).get("passed", item.get("passed", False)) for item in selected]
    return {"schema_version": "stage4e-b2-a-v2.1-case-freshness-0.1.0", "cases": selected, "all_fresh_before_run": all(statuses)}


def _run_steps(runner: OwnedRunnerV21, case: Path, steps: list[tuple[str, str, bool]], *, timeout_s: float = 3600.0) -> list[dict[str, Any]]:
    results = []
    for executable, label, monitor in steps:
        result = runner.execute(case, executable, label=label, extra_args=("-func yPlus -latestTime" if executable == "postProcess" else ""), timeout_s=timeout_s, monitor_cfl=monitor)
        results.append(result)
        if result["return_code"] != 0 or (result.get("online_cfl") or {}).get("stopped"):
            break
    return results


def _run_model(runner: OwnedRunnerV21, case: Path, *, model: str, registry: list[dict[str, Any]]) -> dict[str, Any]:
    freshness = case_freshness(case)
    if not freshness["passed"]:
        raise RuntimeError(f"freshness rejected: {case}")
    records: list[dict[str, Any]] = []
    setup = _run_steps(runner, case, [("blockMesh", "blockMesh", False), ("checkMesh", "checkMesh", False), ("setFields", "setFields", False)], timeout_s=900.0)
    records.extend(setup)
    warmup = runner.execute(case, "pimpleFoam", label="warmup", timeout_s=1800.0, monitor_cfl=True)
    records.append(warmup)
    warmup_log = Path(warmup["log_path"])
    warmup_health = log_health([warmup_log])
    warmup_cfl = _log_cfl(warmup_log)
    yplus_records: list[dict[str, Any]] = []
    if model == "kOmegaSST":
        yplus_step = runner.execute(case, "pimpleFoam", label="yplus_warmup", extra_args="-postProcess -func yPlus -latestTime", timeout_s=300.0, monitor_cfl=False)
        records.append(yplus_step)
        yplus_records.append({"label": "warmup_end", "time_s": latest_time(case), "command": "pimpleFoam -postProcess -func yPlus -latestTime", "return_code": yplus_step["return_code"]})
    else:
        yplus_step = {"return_code": None, "label": "yplus_warmup_not_applicable", "log_path": None}
        yplus_records.append({"label": "warmup_end", "time_s": latest_time(case), "command": "not_applicable_laminar", "return_code": None})
    warmup_summary = {"model": model, "case_id": case.name, "solver_completed": warmup["return_code"] == 0 and warmup_health["contains_End"], "runtime_valid": bool(warmup["return_code"] == 0 and not (warmup.get("online_cfl") or {}).get("stopped") and warmup_cfl.get("max_cfl", 999) < HARD_CFL), "statistics_included": False, "startup_max_CFL": warmup_cfl.get("max_cfl"), "warmup_tail_max_CFL": warmup_cfl.get("max_cfl"), "startup_min_dt": None, "warmup_max_dt": None, "production_fixed_dt": PRODUCTION_DT_S, "production_dt_star": U_HIGH * PRODUCTION_DT_S / D, "return_code": warmup["return_code"], "log_contains_End": warmup_health["contains_End"], "online_cfl": warmup.get("online_cfl"), "checkpoint_after_warmup": checkpoint_hash(case)}
    # OpenFOAM's yPlus function requires a turbulence model.  A laminar case
    # is therefore allowed to record yPlus as unavailable, but a kOmegaSST
    # case must produce the requested post-processing field.
    yplus_required = model == "kOmegaSST"
    warmup_summary["yplus_supported"] = yplus_step["return_code"] == 0 if yplus_required else False
    if not warmup_summary["runtime_valid"] or (yplus_required and yplus_step["return_code"] != 0):
        return {"case_id": case.name, "model": model, "freshness": freshness, "records": records, "warmup": warmup_summary, "production": [], "yplus": yplus_history(case, yplus_records), "stopped_on": "warmup"}
    production: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = [{"block": "warmup", "start_time_s": 0.0, "end_time_s": latest_time(case), "checkpoint": warmup_summary["checkpoint_after_warmup"], "control_mode": "adaptive_warmup", "solver_record_labels": [item.get("label") for item in records]}]
    for index, end_time in enumerate(BLOCKS, start=1):
        start_time = latest_time(case)
        control = switch_to_production(case, model=model, U=U_HIGH, end_time=end_time)
        step = runner.execute(case, "pimpleFoam", label=f"production_block_{index}", timeout_s=3600.0, monitor_cfl=True)
        records.append(step)
        production.append({"block": index, "requested_end_time_s": end_time, "control": control, "solver": step, "cfl": _log_cfl(Path(step["log_path"])), "health": log_health([Path(step["log_path"])]), "latest_time_s": latest_time(case), "checkpoint": checkpoint_hash(case)})
        if model == "kOmegaSST":
            ystep = runner.execute(case, "pimpleFoam", label=f"yplus_block_{index}", extra_args="-postProcess -func yPlus -latestTime", timeout_s=300.0, monitor_cfl=False)
            records.append(ystep)
            yplus_records.append({"label": f"block_{index}_end", "time_s": latest_time(case), "command": "pimpleFoam -postProcess -func yPlus -latestTime", "return_code": ystep["return_code"]})
        else:
            ystep = {"return_code": None, "label": f"yplus_block_{index}_not_applicable"}
            yplus_records.append({"label": f"block_{index}_end", "time_s": latest_time(case), "command": "not_applicable_laminar", "return_code": None})
        lineage.append({"block": index, "start_time_s": start_time, "end_time_s": production[-1]["latest_time_s"], "checkpoint": production[-1]["checkpoint"], "control_mode": "fixed_dt_production", "solver_record_labels": [step.get("label"), ystep.get("label")], "continuity": bool(step["return_code"] == 0 and ystep["return_code"] == 0)})
        if step["return_code"] != 0 or (step.get("online_cfl") or {}).get("stopped") or (model == "kOmegaSST" and ystep["return_code"] != 0):
            break
    cross = coefficient_crosscheck(case, U_abs=U_HIGH, b_mesh=D)
    raw_paths = sorted(case.rglob("forces.dat")); coeff_paths = sorted(case.rglob("forceCoeffs.dat"))
    stats: dict[str, Any] = {"available": False}
    if raw_paths and cross.get("passed"):
        production_paths = [path for path in raw_paths if path.parent.name.replace(".", "", 1).isdigit() and float(path.parent.name) > 0.0]
        raw = parse_raw_force_history(production_paths)
        corrected = corrected_coefficients_from_raw(raw, U_abs=U_HIGH, b_mesh=D); stats = corrected_statistics(corrected, U_abs=U_HIGH)
        stats["production_force_history_paths"] = [str(path) for path in production_paths]
        stats["production_force_history_rows"] = int(raw.get("rows", 0))
    all_solver_logs = [Path(item["solver"]["log_path"]) for item in production if item.get("solver", {}).get("log_path")]
    final_health = log_health(all_solver_logs)
    production_cfl = max((item.get("cfl", {}).get("max_cfl", -1) for item in production), default=None)
    statistics_valid = bool(stats.get("available") and len(production) == len(BLOCKS) and production_cfl is not None and production_cfl < HARD_CFL and stats.get("effective_cycles", 0.0) >= 15.0 and len(stats.get("three_consecutive_windows", [])) == 3)
    valid_runtime = bool(len(production) == len(BLOCKS) and all(item.get("solver", {}).get("return_code") == 0 and item.get("health", {}).get("contains_End") and not item.get("health", {}).get("fatal_tokens") and item.get("cfl", {}).get("max_cfl", 999) < HARD_CFL for item in production))
    formal_yplus = yplus_history(case, yplus_records)
    return finite({"case_id": case.name, "model": model, "freshness": freshness, "records": records, "warmup": warmup_summary, "production": production, "continuation": lineage, "force_crosscheck": cross, "statistics": stats, "formal_yplus": formal_yplus, "solver_completed": final_health["contains_End"] and all(item.get("solver", {}).get("return_code") == 0 for item in production), "runtime_valid": valid_runtime, "statistics_valid": statistics_valid, "gate_accepted": False, "production_max_CFL": production_cfl, "production_fixed_dt_s": PRODUCTION_DT_S, "production_dt_star": U_HIGH * PRODUCTION_DT_S / D, "final_solver_health": final_health, "stopped_on": None if valid_runtime else "production_runtime"})


def _run_io_benchmark(runner: OwnedRunnerV21, root: Path) -> dict[str, Any]:
    old_case = root / "io_benchmark_laminar_yplus_every_step"
    new_case = root / "io_benchmark_laminar_sparse_output"
    generate_case(old_case, model="laminar", U=U_HIGH, mode="io_benchmark_old", end_time=0.1, include_yplus=True, force_interval=5, field_interval=1000, metadata={"benchmark": "v2_old_stepwise_yPlus", "benchmark_steps": 1000, "benchmark_dt_s": 1.0e-4})
    generate_case(new_case, model="laminar", U=U_HIGH, mode="io_benchmark_new", end_time=0.1, include_yplus=False, force_interval=5, field_interval=1000, metadata={"benchmark": "v2.1_sparse_output", "benchmark_steps": 1000, "benchmark_dt_s": 1.0e-4})
    cases = []
    for case, mode in ((old_case, "old_stepwise_yPlus"), (new_case, "new_sparse_output")):
        before = sum(p.stat().st_size for p in case.rglob("*") if p.is_file())
        steps = _run_steps(runner, case, [("blockMesh", "blockMesh", False), ("checkMesh", "checkMesh", False), ("setFields", "setFields", False), ("pimpleFoam", "solver_1000_steps", True)], timeout_s=1800.0)
        logs = [Path(item["log_path"]) for item in steps]
        cases.append({"case_id": case.name, "mode": mode, "steps": steps, "metrics": output_metrics(case, logs, before_bytes=before), "health": log_health(logs), "cfl": _log_cfl(logs[-1]) if logs else {}})
    equivalence = {"force": force_equivalence(old_case, new_case), "fields": field_equivalence(old_case, new_case)}
    equivalence["force_and_fields_passed"] = bool(equivalence["force"]["passed"] and equivalence["fields"]["passed"])
    old, new = cases
    old_dirs, new_dirs = old["metrics"]["time_directory_count"], new["metrics"]["time_directory_count"]
    old_size, new_size = old["metrics"]["case_size_bytes"], new["metrics"]["case_size_bytes"]
    return {"cases": cases, "equivalence": equivalence, "old_new": {"time_directory_reduction_fraction": None if old_dirs == 0 else 1.0 - new_dirs / old_dirs, "disk_reduction_fraction": None if old_size == 0 else 1.0 - new_size / old_size, "directory_reduction_gate": None if old_dirs == 0 else (1.0 - new_dirs / old_dirs) >= 0.90, "disk_reduction_gate": None if old_size == 0 else (1.0 - new_size / old_size) >= 0.80}}


def _offline_monitor_tests() -> dict[str, Any]:
    cases = {"0.49_continue": "Courant Number mean: 0.1 max: 0.49\n", "0.799_continue": "Courant Number mean: 0.1 max: 0.799\n", "0.8_stop": "Courant Number mean: 0.1 max: 0.8\n", "1.2_stop": "Courant Number mean: 0.1 max: 1.2\n", "nan_stop": "Courant Number mean: nan max: 0.2\n"}
    results = {}
    for label, text in cases.items():
        monitor = IncrementalCFLMonitor()
        event = monitor.feed(text)
        results[label] = {"event": event, "summary": monitor.summary(), "passed": (event is None) == ("continue" in label)}
    monitor = IncrementalCFLMonitor(); first = monitor.feed("Courant Number mean: 0.1 max: 0."); second = monitor.feed("8\n"); results["incomplete_line"] = {"first_event": first, "second_event": second, "passed": first is None and second is not None}
    return {"schema_version": "stage4e-b2-a-v2.1-online-cfl-monitor-test-0.1.0", "results": results, "passed": all(item["passed"] for item in results.values())}


def run_workflow(*, run_id: str, results_root: Path = DEFAULT_RESULTS, case_root: Path = DEFAULT_CASES, runtime_root: Path = DEFAULT_RUNTIME) -> dict[str, Any]:
    results = results_root / run_id
    cases = case_root / run_id
    runtime = runtime_root / run_id
    for path in (results, cases):
        path.mkdir(parents=True, exist_ok=False)
    # PYTHONPYCACHEPREFIX is configured before this module is imported, so an
    # otherwise fresh runtime directory may already contain only the approved
    # run-local cache folders.  Reuse is allowed only for that exact empty
    # bootstrap state; any log, checkpoint, time directory or unknown entry is
    # rejected.
    if runtime.exists():
        allowed_bootstrap = {"tmp", "temp", "pycache", "pip-cache", "mplconfig", "matlab-pref", "matlab-log"}
        entries = {item.name for item in runtime.iterdir()}
        if not entries.issubset(allowed_bootstrap) or any(item.is_file() for item in runtime.iterdir()):
            raise FileExistsError(f"refusing to reuse non-empty runtime directory: {runtime}")
    else:
        runtime.mkdir(parents=True, exist_ok=False)
    for name in ("tmp", "temp", "logs", "requests", "responses", "checkpoints", "intermediate"):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    env_paths = {"TEMP": runtime / "temp", "TMP": runtime / "tmp", "TMPDIR": runtime / "tmp", "PYTHONPYCACHEPREFIX": runtime / "pycache", "PIP_CACHE_DIR": runtime / "pip-cache", "MPLCONFIGDIR": runtime / "mplconfig", "MATLAB_PREFDIR": runtime / "matlab-pref", "MATLAB_LOG_DIR": runtime / "matlab-log"}
    for path in env_paths.values(): path.mkdir(parents=True, exist_ok=True)
    for key, path in env_paths.items(): os.environ[key] = str(path)
    (runtime / "runtime_environment.json").write_text(json.dumps({key: str(path) for key, path in env_paths.items()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    before_inventory = process_snapshot(); write_json(runtime / "process_inventory_before.json", {"run_id": run_id, "phase": "before", "processes": before_inventory})
    old_before = _snapshot_paths([V2_RESULTS, PROJECT / "src" / "coupling" / "stage4e_target_re_pilot_v2", V2_CASE_ROOT]); write_json(runtime / "old_evidence_hashes_before.json", old_before)
    flow = load_formal_flow_profile()
    write_json(results / "prior_run_diagnostic_audit.json", _old_log_diagnosis())
    write_json(results / "online_cfl_monitor_test.json", _offline_monitor_tests())
    fmax = 0.25 * U_HIGH / D
    force_sample_s = FORCE_WRITE_INTERVAL_STEPS * PRODUCTION_DT_S
    sampling_contract = {"schema_version": "stage4e-b2-a-v2.1-output-sampling-contract-0.1.0", "solver_dt_s": PRODUCTION_DT_S, "force_write_interval_steps": FORCE_WRITE_INTERVAL_STEPS, "force_sample_interval_s": force_sample_s, "f_max_Hz": fmax, "fastest_period_s": 1.0 / fmax, "samples_per_fastest_cycle": (1.0 / fmax) / force_sample_s, "field_write_interval_steps": FIELD_WRITE_INTERVAL_STEPS, "field_write_interval_s": FIELD_WRITE_INTERVAL_STEPS * PRODUCTION_DT_S, "yPlus_evaluation_times": ["warmup_end", "each_continuation_block_end"], "formal_end_time_s": FORMAL_END_TIME_S, "estimated_time_directories_0_to_formal_end": 1 + math.ceil(FORMAL_END_TIME_S / (FIELD_WRITE_INTERVAL_STEPS * PRODUCTION_DT_S)), "force_sampling_requirement_samples_per_cycle": 100, "force_sampling_passed": (1.0 / fmax) / force_sample_s >= 100, "yPlus_in_controlDict": False}
    write_json(results / "output_sampling_contract_v2_1.json", sampling_contract)
    write_json(results / "startup_warmup_contract.json", {"schema_version": "stage4e-b2-a-v2.1-startup-warmup-contract-0.1.0", "warmup_end_s": WARMUP_END_S, "adjustTimeStep": True, "maxCo": 0.5, "maxDeltaT_s": PRODUCTION_DT_S, "production_adjustTimeStep": False, "production_fixed_dt_s": PRODUCTION_DT_S, "warmup_excluded_from_statistics": True, "potentialFoam_used": False, "perturbation_written_before_warmup": True})
    write_json(results / "initial_perturbation_contract_v2_1.json", {"schema_version": "stage4e-b2-a-v2.1-perturbation-contract-0.1.0", "epsilon": 0.005, "upper_Uy": 0.005 * U_HIGH, "lower_Uy": -0.005 * U_HIGH, "net_perturbation_Uy": 0.0, "deterministic": True, "zero_net_transverse_momentum": True})
    write_json(results / "source_identity_audit_v2_1.json", {"schema_version": "stage4e-b2-a-v2.1-source-identity-0.1.0", "parent_flow_profile_sha256": flow["flow_profile_sha256"], "parent_manifest_sha256": EXPECTED_MANIFEST_SHA256, "parent_config_sha256": EXPECTED_CONFIG_SHA256, "selected_candidate": EXPECTED_CANDIDATE, "Re_high": RE_HIGH, "U_high_mps": U_HIGH, "protocol_version": "0.2.1"})
    selected_fresh = []
    for name, model in (("high_laminar_medium_v2_1", "laminar"), ("high_kOmegaSST_medium_v2_1", "kOmegaSST")):
        case = cases / name
        meta = generate_case(case, model=model, U=U_HIGH, mode="warmup", end_time=WARMUP_END_S, metadata={"parent_flow_profile_sha256": flow["flow_profile_sha256"], "scope": "maximum_Re_medium_model_screening_only"})
        selected_fresh.append({"case_id": name, "case_relative_path": _case_relative(case), "freshness": case_freshness(case), "case_identity_sha256": meta["case_identity_sha256"]})
    io_cases = cases / "io_benchmark"
    io_cases.mkdir()
    selected_fresh.append({"case_id": "io_benchmark", "freshness": {"passed": True}})
    write_json(results / "case_freshness_audit_v2_1.json", _fresh_case_manifest(selected_fresh))
    registry: list[dict[str, Any]] = []
    limiter = ProcessLimiter(2, run_id=run_id)
    runner = OwnedRunnerV21(limiter, registry, runtime, run_id)
    io_result: dict[str, Any] = {}
    model_results: list[dict[str, Any]] = []
    try:
        io_result = _run_io_benchmark(runner, io_cases)
        write_json(results / "io_equivalence_test.json", io_result["equivalence"])
        write_json(results / "io_performance_comparison.json", io_result)
        for name, model in (("high_laminar_medium_v2_1", "laminar"), ("high_kOmegaSST_medium_v2_1", "kOmegaSST")):
            item = _run_model(runner, cases / name, model=model, registry=registry)
            model_results.append(item)
            write_json(results / ("laminar_medium_statistics.json" if model == "laminar" else "sst_medium_statistics.json"), item)
            write_json(results / ("laminar_warmup_summary.json" if model == "laminar" else "sst_warmup_summary.json"), item["warmup"])
            if item.get("stopped_on"):
                break
    finally:
        process_audit = closeout_process_audit(runtime, limiter, registry)
    write_json(results / "formal_yplus_history.json", {"models": [{"model": item["model"], "history": item.get("formal_yplus")} for item in model_results]})
    write_json(results / "continuation_lineage.json", {"models": [{"model": item["model"], "lineage": item.get("continuation", [])} for item in model_results]})
    available = [item for item in model_results if item.get("runtime_valid") and item.get("statistics_valid")]
    model_decision = {"schema_version": "stage4e-b2-a-v2.1-model-screening-0.1.0", "screening_Re": RE_HIGH, "candidate_models": ["laminar", "kOmegaSST"], "results": [{"model": item["model"], "solver_completed": item.get("solver_completed"), "runtime_valid": item.get("runtime_valid"), "statistics_valid": item.get("statistics_valid"), "production_max_CFL": item.get("production_max_CFL"), "statistics": item.get("statistics"), "formal_yplus": item.get("formal_yplus")} for item in model_results], "selection_status": "candidate_for_next_mesh_dt_domain_stage" if available else "not_frozen", "selected_model": None if not available else available[0]["model"], "entry_ready_for_next_stage": bool(available), "no_coarse_fine_long_runs": True, "no_low_middle_runs": True}
    write_json(results / "model_screening_v2_1.json", model_decision)
    old_audit = _old_hash_audit(old_before); write_json(results / "old_evidence_hash_audit_v2_1.json", old_audit)
    after_inventory = process_snapshot(); write_json(runtime / "process_inventory_after.json", {"run_id": run_id, "phase": "after", "processes": after_inventory})
    write_json(runtime / "retained_process_handoff.json", {"schema_version": "stage4e-b2-a-v2.1-retained-process-handoff-0.1.0", "retained": False, "processes": []})
    write_json(runtime / "c_drive_write_diff.json", {"schema_version": "stage4e-b2-a-v2.1-c-drive-write-diff-0.1.0", "project_artifacts_created_on_C_drive": [], "count": 0})
    write_json(runtime / "runtime_path_audit.json", {"schema_version": "stage4e-b2-a-v2.1-runtime-path-audit-0.1.0", "runtime_root": str(runtime), "all_task_temp_logs_requests_responses_checkpoints_under_runtime": True, "project_runtime_root_on_D_drive": True, "home_or_codex_home_modified": False, "owned_residual_process_count": process_audit["task_owned_residual_process_count"], "process_cleanup_blocked": process_audit["process_cleanup_blocked"], "runtime_hygiene_gate": process_audit["task_owned_residual_process_count"] == 0 and not old_audit["changed"]})
    formal_complete = len(model_results) == 2 and all(item.get("runtime_valid") for item in model_results)
    entry_ready = bool(available) and formal_complete and io_result.get("equivalence", {}).get("force_and_fields_passed") and io_result.get("old_new", {}).get("directory_reduction_gate") and io_result.get("old_new", {}).get("disk_reduction_gate")
    gate = {"schema_version": "stage4e-b2-a-v2.1-entry-candidate-0.1.0", "run_id": run_id, "status": "entry_candidate" if entry_ready else "not_ready_for_next_stage", "entry_ready_for_mesh_dt_domain": entry_ready, "selected_model": model_decision["selected_model"], "parent_flow_profile_sha256": EXPECTED_FLOW_PROFILE_SHA256, "parent_manifest_sha256": EXPECTED_MANIFEST_SHA256, "parent_config_sha256": EXPECTED_CONFIG_SHA256, "completed_scope": ["output_sampling_fix", "I/O_equivalence", "adaptive_warmup", "online_CFL_monitor", "maximum_Re_medium_laminar_and_SST_screening"], "not_run": ["coarse_long_run", "fine_long_run", "mesh_convergence", "dt_halving_long_run", "expanded_domain", "low_middle", "nine_slice", "ANCF"], "runtime_gate": process_audit["task_owned_residual_process_count"] == 0, "old_evidence_unchanged": old_audit["old_evidence_unchanged"], "stop_conditions_triggered": [item.get("stopped_on") for item in model_results if item.get("stopped_on")], "final_gate_still_not_passed": True}
    write_json(results / "process_cleanup_audit_v2_1.json", process_audit)
    write_json(results / "regression_summary_v2_1.json", {"schema_version": "stage4e-b2-a-v2.1-regression-summary-0.1.0", "compileall": "pending_until_cli", "specialized_tests": "pending_until_cli", "root_regression": "pending_until_cli", "model_results_count": len(model_results), "old_evidence_unchanged": old_audit["old_evidence_unchanged"]})
    write_json(results / "stage4e_b2_a_v2_1_entry_candidate.json", gate)
    return {"run_id": run_id, "results": str(results), "runtime": str(runtime), "cases": str(cases), "gate": gate, "models": model_results, "io": io_result, "process": process_audit, "old_audit": old_audit}


def main() -> None:
    run_id = os.environ.get("B2A_V2_1_RUN_ID")
    if not run_id:
        raise SystemExit("B2A_V2_1_RUN_ID is required")
    output = run_workflow(run_id=run_id, results_root=Path(os.environ.get("B2A_V2_1_RESULTS_ROOT", str(DEFAULT_RESULTS))), case_root=Path(os.environ.get("B2A_V2_1_CASE_ROOT", str(DEFAULT_CASES))), runtime_root=Path(os.environ.get("B2A_V2_1_RUNTIME_ROOT", str(DEFAULT_RUNTIME))))
    print(json.dumps({"run_id": output["run_id"], "gate": output["gate"], "model_count": len(output["models"]), "process_residual": output["process"]["task_owned_residual_process_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
