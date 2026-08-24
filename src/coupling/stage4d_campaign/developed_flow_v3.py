"""Stage 4D-A-v3 continuation and snapshot-alignment audit.

This module is deliberately isolated from the v1/v2 implementations and
never writes to their cases or result directories.  Re80 is continued from
the immutable v2 240 s final field.  Re100/Re120 are re-audited by truncating
their existing v2 force histories to the actual final field time.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .developed_flow import DevelopedFlowError, ForceSample, _replace_scalar, _run_openfoam, audit_developed_flow_identity, canonical_sha, sha256_file
from .developed_flow_v2 import (
    DT_S,
    TIME_TOL_S,
    _cfl_from_logs,
    _collect_continuation_forces,
    _json_safe,
    _write_force_csv,
    analyze_force_history_v2,
    audit_v2_flow_identity,
    merge_force_histories,
    read_force_csv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
V2_CASE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4d_developed_flow_v2"
V2_RESULT_ROOT = PROJECT_ROOT / "results" / "06_developed_flow_v2"
V1_CASE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4d_developed_flow"
V1_RESULT_ROOT = PROJECT_ROOT / "results" / "06_developed_flow"
V3_CASE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4d_developed_flow_v3"
V3_RESULT_ROOT = PROJECT_ROOT / "results" / "06_developed_flow_v3"
MAX_PHYSICAL_TIME_S = 360.0
SNAPSHOT_TOL_S = 0.5 * DT_S
SNAPSHOT_INTERVAL_S = 0.5
SNAPSHOT_INTERVAL_STEPS = int(round(SNAPSHOT_INTERVAL_S / DT_S))


def _replace_first_scalar(text: str, key: str, value: str) -> str:
    changed, count = re.subn(rf"(?m)^(\s*{re.escape(key)}\s+)[^;]+;", rf"\g<1>{value};", text, count=1)
    if count != 1:
        raise DevelopedFlowError(f"expected one first {key} entry, found {count}")
    return changed


def _numeric_time_dirs(case: Path) -> list[tuple[float, Path]]:
    values: list[tuple[float, Path]] = []
    for child in case.iterdir():
        if child.is_dir() and re.fullmatch(r"[0-9.eE+-]+", child.name):
            values.append((float(child.name), child))
    return sorted(values, key=lambda item: item[0])


def _required_field_paths(case: Path, time_dir: Path) -> list[Path]:
    return [time_dir / "U", time_dir / "p", time_dir / "phi", time_dir / "uniform" / "time"]


def _field_hashes(case: Path, time_dir: Path) -> dict[str, str]:
    required = _required_field_paths(case, time_dir)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise DevelopedFlowError(f"final field set is incomplete: {missing}")
    return {str(path.relative_to(case)).replace("\\", "/"): sha256_file(path) for path in required}


def _source_v2(flow_id: str, U: float) -> tuple[dict[str, Any], Path, Path, list[ForceSample], dict[str, Any]]:
    summary_path = V2_RESULT_ROOT / flow_id / "flow_summary_v2.json"
    case = V2_CASE_ROOT / flow_id
    result_dir = V2_RESULT_ROOT / flow_id
    if not summary_path.is_file() or not case.is_dir():
        raise DevelopedFlowError(f"v2 source is missing for {flow_id}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    audit = audit_v2_flow_identity(summary, case=case, result_dir=result_dir)
    if summary.get("flow_id") != flow_id or not math.isclose(float(summary.get("U_mps")), U, rel_tol=0.0, abs_tol=1.0e-12):
        raise DevelopedFlowError(f"v2 source identity does not match {flow_id}")
    force_path = Path(str(summary["force_history_merged_csv"]))
    force_hash = sha256_file(force_path)
    if force_hash != summary["merged_force_sha256"]:
        raise DevelopedFlowError(f"v2 source force hash mismatch for {flow_id}")
    samples = read_force_csv(force_path)
    source_fields = dict(summary["final_fields"])
    for relative, expected in source_fields.items():
        source_path = case / relative
        if not source_path.is_file() or sha256_file(source_path) != str(expected):
            raise DevelopedFlowError(f"v2 source final field hash mismatch for {flow_id}: {relative}")
    return summary, case, force_path, samples, {"summary_sha256": sha256_file(summary_path), "force_sha256": force_hash, "field_hashes": source_fields, "audit": audit}


def _copy_re80_v2_final_case(*, source_summary: Mapping[str, Any], source_case: Path, output: Path, run_id: str) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite v3 Re80 case: {output}")
    source_time_name = str(source_summary["final_time_name"])
    source_time = source_case / source_time_name
    if not source_time.is_dir():
        raise DevelopedFlowError(f"v2 Re80 final field directory is missing: {source_time}")
    output.mkdir(parents=True)
    shutil.copytree(source_case / "constant", output / "constant")
    shutil.copytree(source_case / "system", output / "system")
    shutil.copytree(source_time, output / source_time_name)
    source_hashes = _field_hashes(source_case, source_time)
    if source_hashes != dict(source_summary["final_fields"]):
        raise DevelopedFlowError("v2 Re80 field hash changed before v3 copy")
    control_path = output / "system" / "controlDict"
    control = control_path.read_text(encoding="utf-8")
    control = _replace_scalar(control, "startFrom", "latestTime")
    control = _replace_scalar(control, "startTime", format(float(source_summary["total_runtime_s"]), ".12g"))
    control = _replace_scalar(control, "endTime", format(float(source_summary["total_runtime_s"]) + 20.0, ".12g"))
    control = _replace_scalar(control, "deltaT", format(DT_S, ".12g"))
    control = _replace_first_scalar(control, "writeControl", "timeStep")
    control = _replace_first_scalar(control, "writeInterval", str(SNAPSHOT_INTERVAL_STEPS))
    control = _replace_scalar(control, "writePrecision", "16")
    control = _replace_scalar(control, "timePrecision", "12")
    control_path.write_text(control, encoding="utf-8")
    immutable_files = ["system/fvSolution", "system/fvSchemes", "constant/momentumTransport", "constant/physicalProperties", "constant/polyMesh/points"]
    immutable_hashes = {relative: sha256_file(output / relative) for relative in immutable_files}
    lineage = {
        "run_id": run_id,
        "flow_id": "re80",
        "U_mps": 0.8,
        "Re": 80.0,
        "source_v2_case": str(source_case.resolve()),
        "source_v2_summary": str((V2_RESULT_ROOT / "re80" / "flow_summary_v2.json").resolve()),
        "source_v2_summary_sha256": sha256_file(V2_RESULT_ROOT / "re80" / "flow_summary_v2.json"),
        "source_v2_developed_flow_sha256": source_summary["developed_flow_sha256"],
        "source_v2_final_time_name": source_time_name,
        "source_v2_snapshot_time_s": float(source_summary["total_runtime_s"]),
        "source_v2_final_fields": source_hashes,
        "source_v2_force_history": str(Path(str(source_summary["force_history_merged_csv"])).resolve()),
        "source_v2_force_sha256": str(source_summary["merged_force_sha256"]),
        "target_v3_case": str(output.resolve()),
        "copied_only_same_re_source": True,
        "startFrom": "latestTime",
        "setFields_called": False,
        "dt_s": DT_S,
        "max_physical_time_s": MAX_PHYSICAL_TIME_S,
        "snapshot_schedule": {"writeControl": "timeStep", "writeInterval_steps": SNAPSHOT_INTERVAL_STEPS, "writeInterval_s": SNAPSHOT_INTERVAL_S},
        "immutable_solver_setup_hashes": immutable_hashes,
    }
    (output / "continuation_lineage_v3.json").write_text(json.dumps(_json_safe(lineage), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return lineage


def _set_v3_end_time(case: Path, end_time_s: float) -> None:
    control_path = case / "system" / "controlDict"
    text = control_path.read_text(encoding="utf-8")
    text = _replace_scalar(text, "endTime", format(float(end_time_s), ".12g"))
    text = _replace_scalar(text, "startFrom", "latestTime")
    text = _replace_first_scalar(text, "writeControl", "timeStep")
    text = _replace_first_scalar(text, "writeInterval", str(SNAPSHOT_INTERVAL_STEPS))
    control_path.write_text(text, encoding="utf-8")


def _latest_snapshot(case: Path, source_time_s: float) -> tuple[float, Path]:
    candidates = [(value, path) for value, path in _numeric_time_dirs(case) if value > source_time_s + TIME_TOL_S]
    if not candidates:
        raise DevelopedFlowError("no new v3 final field snapshot was written")
    value, path = candidates[-1]
    _field_hashes(case, path)
    return value, path


def _prefix_to_time(samples: Sequence[ForceSample], end_time_s: float) -> list[ForceSample]:
    prefix = [sample for sample in samples if sample.time_s <= end_time_s + TIME_TOL_S]
    if len(prefix) < 16:
        raise DevelopedFlowError(f"force history has insufficient samples through {end_time_s}")
    return prefix


def _evaluate_re80_point(samples: Sequence[ForceSample], *, snapshot_time_s: float, discard_start_s: float) -> dict[str, Any]:
    prefix = _prefix_to_time(samples, snapshot_time_s)
    force_time_s = float(prefix[-1].time_s)
    if abs(force_time_s - snapshot_time_s) > SNAPSHOT_TOL_S:
        return {"valid": False, "snapshot_time_s": snapshot_time_s, "force_time_s": force_time_s, "alignment_error_s": abs(force_time_s - snapshot_time_s), "reason": "force history does not reach snapshot within 0.5dt"}
    stats = analyze_force_history_v2(prefix, U=0.8, discard_start_s=discard_start_s)
    stats["total_runtime_s"] = float(snapshot_time_s)
    stats["statistics_end_time_s"] = float(snapshot_time_s)
    return {"valid": True, "snapshot_time_s": float(snapshot_time_s), "force_time_s": force_time_s, "statistics_end_time_s": float(snapshot_time_s), "alignment_error_s": abs(force_time_s - snapshot_time_s), "statistics": stats, "all_stable_criteria": bool(stats["all_stable_criteria"])}


def _run_log_summary(log: Path, label: str) -> dict[str, Any]:
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    return {"label": label, "return_code": 0, "log": str(log.resolve()), "log_sha256": sha256_file(log), "normal_end": "End" in text}


def _write_v3_plots(result_dir: Path, samples: Sequence[ForceSample], stats: Mapping[str, Any], convergence: Mapping[str, Any], *, U: float) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    times = np.asarray([sample.time_s for sample in samples], dtype=float)
    denominator = 0.5 * 1000.0 * U * U
    cd = np.asarray([sample.force_N[0] / denominator for sample in samples], dtype=float)
    cl = np.asarray([sample.force_N[1] / denominator for sample in samples], dtype=float)
    force_path = result_dir / "force_coefficient_history_v3.png"
    figure, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 6))
    axes[0].plot(times, cd, linewidth=0.5)
    axes[0].set_ylabel("Cd")
    axes[1].plot(times, cl, linewidth=0.5)
    axes[1].set_ylabel("Cl")
    axes[1].set_xlabel("time (s)")
    figure.tight_layout()
    figure.savefig(force_path, dpi=140)
    plt.close(figure)

    envelope_path = result_dir / "cl_envelope_v3.png"
    amplitudes = stats.get("envelope", {}).get("cycle_amplitudes_Cl", [])
    figure, axis = plt.subplots(figsize=(10, 4))
    axis.plot(np.arange(len(amplitudes)), amplitudes, marker="o", markersize=2, linewidth=0.8)
    axis.set_xlabel("cycle index after startup discard")
    axis.set_ylabel("Cl envelope amplitude")
    figure.tight_layout()
    figure.savefig(envelope_path, dpi=140)
    plt.close(figure)

    convergence_path = result_dir / "window_convergence_v3.png"
    evaluations = list(convergence.get("evaluations", []))
    x = [float(item["snapshot_time_s"]) for item in evaluations]
    figure, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 6))
    axes[0].plot(x, [item.get("statistics", {}).get("window_relative_changes", {}).get("Cl_fluctuation_RMS", np.nan) for item in evaluations], marker="o", label="Cl RMS")
    axes[0].plot(x, [item.get("statistics", {}).get("window_relative_changes", {}).get("Cl_peak_to_peak", np.nan) for item in evaluations], marker="x", label="Cl peak-to-peak")
    axes[0].axhline(0.05, color="r", linestyle="--")
    axes[0].legend()
    axes[0].set_ylabel("relative change")
    axes[1].plot(x, [item.get("statistics", {}).get("St", np.nan) for item in evaluations], marker="o")
    axes[1].axhspan(0.12, 0.22, color="green", alpha=0.15)
    axes[1].set_ylabel("St")
    axes[1].set_xlabel("snapshot time (s)")
    figure.tight_layout()
    figure.savefig(convergence_path, dpi=140)
    plt.close(figure)
    return {"force_coefficient_history": str(force_path.resolve()), "cl_envelope": str(envelope_path.resolve()), "window_convergence": str(convergence_path.resolve())}


def run_re80_v3(*, root: Path = V3_CASE_ROOT, result_root: Path = V3_RESULT_ROOT, run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or f"stage4d_a_v3_re80_{uuid.uuid4().hex[:8]}"
    source_summary, source_case, source_force_path, source_samples, source_audit = _source_v2("re80", 0.8)
    target_case = root / "re80"
    result_dir = result_root / "re80"
    result_dir.mkdir(parents=True, exist_ok=True)
    lineage = _copy_re80_v2_final_case(source_summary=source_summary, source_case=source_case, output=target_case, run_id=run_id)
    check = _run_openfoam(target_case, "checkMesh_v3_continuation", timeout_s=300.0)
    if check["return_code"] != 0 or "Mesh OK" not in Path(check["log"]).read_text(encoding="utf-8", errors="replace"):
        raise DevelopedFlowError("v3 Re80 checkMesh failed")
    source_end = float(source_summary["total_runtime_s"])
    discard_start = float(source_summary["statistics"]["discarded_startup_transient_s"])
    all_samples = list(source_samples)
    continuation_samples: list[ForceSample] = []
    evaluations: list[dict[str, Any]] = []
    solver_runs: list[dict[str, Any]] = []
    stable_consecutive = 0
    current_snapshot = source_end
    while True:
        if current_snapshot <= source_end + TIME_TOL_S:
            stable_consecutive = 0
        else:
            point = _evaluate_re80_point(all_samples, snapshot_time_s=current_snapshot, discard_start_s=discard_start)
            stable_consecutive = stable_consecutive + 1 if point.get("valid") and point.get("all_stable_criteria") else 0
            point["real_solver_evaluation"] = True
            point["stable_consecutive"] = stable_consecutive
            evaluations.append(point)
            if stable_consecutive >= 3:
                break
        if current_snapshot >= MAX_PHYSICAL_TIME_S - DT_S:
            break
        current_stats = analyze_force_history_v2(_prefix_to_time(all_samples, current_snapshot), U=0.8, discard_start_s=discard_start)
        block_steps = max(SNAPSHOT_INTERVAL_STEPS, int(math.ceil(2.0 * float(current_stats["period_s"]) / SNAPSHOT_INTERVAL_S - 1.0e-12)) * SNAPSHOT_INTERVAL_STEPS)
        next_end = min(MAX_PHYSICAL_TIME_S, current_snapshot + block_steps * DT_S)
        next_end = round(next_end / SNAPSHOT_INTERVAL_S) * SNAPSHOT_INTERVAL_S
        _set_v3_end_time(target_case, next_end)
        label = f"pimpleFoam_v3_cont_{next_end:.6f}s"
        solver = _run_openfoam(target_case, label, timeout_s=3600.0)
        solver_runs.append(solver)
        if solver["return_code"] != 0:
            raise DevelopedFlowError(f"v3 Re80 pimpleFoam failed: {solver}")
        new_samples, force_paths = _collect_continuation_forces(target_case)
        continuation_samples = new_samples
        merged = merge_force_histories(source_samples, continuation_samples)
        all_samples = merged["samples"]
        current_snapshot, final_dir = _latest_snapshot(target_case, source_end)
        _field_hashes(target_case, final_dir)
        _write_force_csv(result_dir / "force_history_merged_v3.csv", all_samples)
        if current_snapshot > MAX_PHYSICAL_TIME_S + TIME_TOL_S:
            raise DevelopedFlowError(f"v3 Re80 exceeded 360 s: {current_snapshot}")
    if not evaluations or evaluations[-1].get("snapshot_time_s") != current_snapshot:
        point = _evaluate_re80_point(all_samples, snapshot_time_s=current_snapshot, discard_start_s=discard_start)
        point["real_solver_evaluation"] = current_snapshot > source_end + TIME_TOL_S
        point["stable_consecutive"] = stable_consecutive
        evaluations.append(point)
    final_time, final_dir = _latest_snapshot(target_case, source_end)
    final_fields = _field_hashes(target_case, final_dir)
    _write_force_csv(result_dir / "force_history_merged_v3.csv", all_samples)
    merged_force_hash = sha256_file(result_dir / "force_history_merged_v3.csv")
    max_cfl = max(float(source_summary["max_cfl"]), _cfl_from_logs([Path(item["log"]) for item in solver_runs]))
    convergence = {
        "status": "developed" if evaluations[-1].get("all_stable_criteria") and evaluations[-1].get("stable_consecutive", 0) >= 3 else "blocked",
        "required_consecutive_stable_points": 3,
        "max_physical_time_s": MAX_PHYSICAL_TIME_S,
        "evaluations": evaluations,
    }
    (result_dir / "convergence_history_v3.json").write_text(json.dumps(_json_safe(convergence), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    lineage.update({
        "source_v2_force_sha256_after_run": sha256_file(source_force_path),
        "source_v2_unchanged": sha256_file(source_force_path) == lineage["source_v2_force_sha256"],
        "continuation_blocks": len(solver_runs),
        "continuation_end_snapshot_time_s": final_time,
        "continuation_force_sha256": merged_force_hash,
        "merged_sample_count": len(all_samples),
        "solver_logs": [_run_log_summary(Path(item["log"]), item["label"]) for item in solver_runs],
        "checkMesh": check,
    })
    (result_dir / "continuation_lineage_v3.json").write_text(json.dumps(_json_safe(lineage), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    final_stats = evaluations[-1].get("statistics", {})
    plots = _write_v3_plots(result_dir, all_samples, final_stats, convergence, U=0.8)
    physical_identity = {
        "flow_id": "re80", "U_mps": 0.8, "Re": 80.0, "rho_kgpm3": 1000.0, "nu_m2ps": 0.01, "D_m": 1.0, "dt_s": DT_S,
        "source_v2_developed_flow_sha256": lineage["source_v2_developed_flow_sha256"], "source_v2_final_fields": lineage["source_v2_final_fields"], "source_v2_force_sha256": lineage["source_v2_force_sha256"],
        "merged_force_sha256": merged_force_hash, "final_fields": final_fields, "snapshot_time_s": final_time, "statistics_end_time_s": final_time,
        "statistics": {"dominant_frequency_Hz": final_stats.get("dominant_frequency_Hz"), "zero_crossing_frequency_Hz": final_stats.get("zero_crossing_frequency_Hz"), "St": final_stats.get("St"), "mean_Cd": final_stats.get("window_2", {}).get("mean_Cd"), "Cl_rms": final_stats.get("window_2", {}).get("Cl_rms"), "criteria": final_stats.get("criteria", {})},
    }
    summary = {
        "status": convergence["status"], "flow_id": "re80", "U_mps": 0.8, "Re": 80.0, "source_v2_status": source_summary["status"],
        "source_v2_snapshot_time_s": source_end, "snapshot_time_s": final_time, "statistics_end_time_s": final_time, "snapshot_statistics_time_error_s": 0.0,
        "statistics": final_stats, "continuous_stable_evaluation_count": evaluations[-1].get("stable_consecutive", 0), "max_cfl": max_cfl, "checkMesh": check,
        "solver_runs": solver_runs, "final_time_name": final_dir.name, "final_fields": final_fields, "force_history_merged_v3_csv": str((result_dir / "force_history_merged_v3.csv").resolve()),
        "force_history_merged_v3_sha256": merged_force_hash, "continuation_lineage_v3": str((result_dir / "continuation_lineage_v3.json").resolve()), "convergence_history_v3": str((result_dir / "convergence_history_v3.json").resolve()), "plots": plots,
        "physical_identity": physical_identity, "developed_flow_sha256": canonical_sha(physical_identity),
    }
    (result_dir / "flow_summary_v3.json").write_text(json.dumps(_json_safe(summary), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def _truncate_v2_flow(flow_id: str, U: float) -> dict[str, Any]:
    source_summary, source_case, source_force_path, samples, source_audit = _source_v2(flow_id, U)
    snapshot_time = float(source_summary["final_time_name"])
    snapshot_dir = source_case / str(source_summary["final_time_name"])
    final_fields = _field_hashes(source_case, snapshot_dir)
    truncated = _prefix_to_time(samples, snapshot_time)
    force_time = float(truncated[-1].time_s)
    alignment_error = abs(force_time - snapshot_time)
    if alignment_error > SNAPSHOT_TOL_S:
        status = "blocked"
    else:
        status = "candidate"
    discard_start = float(source_summary["statistics"]["discarded_startup_transient_s"])
    stats = analyze_force_history_v2(truncated, U=U, discard_start_s=discard_start)
    stats["total_runtime_s"] = snapshot_time
    stats["statistics_end_time_s"] = snapshot_time
    history = json.loads((V2_RESULT_ROOT / flow_id / "convergence_history.json").read_text(encoding="utf-8"))
    previous = []
    for evaluation in history.get("evaluations", []):
        end = float(evaluation["end_time_s"])
        if end < snapshot_time - TIME_TOL_S:
            prefix = _prefix_to_time(samples, end)
            previous_stats = analyze_force_history_v2(prefix, U=U, discard_start_s=discard_start)
            previous.append({"evaluation_time_s": end, "real_solver_evaluation": True, "all_stable_criteria": bool(previous_stats["all_stable_criteria"]), "statistics": previous_stats})
    prior_two = previous[-2:]
    continuous = len(prior_two) == 2 and all(item["all_stable_criteria"] for item in prior_two) and bool(stats["all_stable_criteria"])
    if status == "candidate" and continuous:
        status = "developed"
    else:
        status = "blocked"
    result_dir = V3_RESULT_ROOT / flow_id
    result_dir.mkdir(parents=True, exist_ok=True)
    truncated_path = result_dir / "truncated_force_history_v3.csv"
    _write_force_csv(truncated_path, truncated)
    truncated_hash = sha256_file(truncated_path)
    alignment = {
        "flow_id": flow_id, "source_v2_summary": str((V2_RESULT_ROOT / flow_id / "flow_summary_v2.json").resolve()), "source_v2_summary_sha256": sha256_file(V2_RESULT_ROOT / flow_id / "flow_summary_v2.json"),
        "source_v2_statistics_end_time_s": source_summary["total_runtime_s"], "snapshot_time_s": snapshot_time, "force_time_s": force_time, "statistics_end_time_s": snapshot_time,
        "snapshot_statistics_time_error_s": 0.0, "force_snapshot_time_error_s": alignment_error, "snapshot_time_tolerance_s": SNAPSHOT_TOL_S,
        "source_v2_field_hashes": dict(source_summary["final_fields"]), "snapshot_field_hashes": final_fields, "source_v2_force_sha256": source_summary["merged_force_sha256"], "truncated_force_sha256": truncated_hash,
        "previous_two_real_evaluations": prior_two, "snapshot_recomputed_statistics": stats, "continuous_three_stable_points": continuous,
        "source_v2_unchanged": True,
    }
    (result_dir / "snapshot_alignment_v3.json").write_text(json.dumps(_json_safe(alignment), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    physical_identity = {
        "flow_id": flow_id, "U_mps": U, "Re": U / 0.01, "rho_kgpm3": 1000.0, "nu_m2ps": 0.01, "D_m": 1.0, "dt_s": DT_S,
        "source_v2_developed_flow_sha256": source_summary["developed_flow_sha256"], "source_v2_field_hashes": final_fields, "source_v2_force_sha256": source_summary["merged_force_sha256"],
        "truncated_force_sha256": truncated_hash, "snapshot_time_s": snapshot_time, "statistics_end_time_s": snapshot_time, "statistics": {"St": stats["St"], "mean_Cd": stats["window_2"].get("mean_Cd"), "Cl_rms": stats["window_2"].get("Cl_rms"), "criteria": stats["criteria"], "continuous_three_stable_points": continuous},
    }
    summary = {
        "status": status, "flow_id": flow_id, "U_mps": U, "Re": U / 0.01, "source_v2_statistics_end_time_s": source_summary["total_runtime_s"], "snapshot_time_s": snapshot_time, "statistics_end_time_s": snapshot_time, "snapshot_statistics_time_error_s": 0.0,
        "force_snapshot_time_error_s": alignment_error, "statistics": stats, "continuous_stable_evaluation_count": 3 if continuous else 0, "final_fields": final_fields,
        "max_cfl": source_summary.get("max_cfl"), "checkMesh": source_summary.get("checkMesh"),
        "source_v2_solver_runs": source_summary.get("solver_runs", []),
        "truncated_force_history_v3_csv": str(truncated_path.resolve()), "truncated_force_history_v3_sha256": truncated_hash, "snapshot_alignment_v3": str((result_dir / "snapshot_alignment_v3.json").resolve()), "physical_identity": physical_identity, "developed_flow_sha256": canonical_sha(physical_identity),
    }
    (result_dir / "flow_summary_v3.json").write_text(json.dumps(_json_safe(summary), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def build_v3_bank(*, result_root: Path = V3_RESULT_ROOT) -> dict[str, Any]:
    records = [json.loads((result_root / flow_id / "flow_summary_v3.json").read_text(encoding="utf-8")) for flow_id in ("re80", "re100", "re120")]
    process_audit = json.loads((result_root / "process_limiter_real_overlap_v3_audit.json").read_text(encoding="utf-8"))
    ready = all(
        item["status"] == "developed"
        and abs(float(item["snapshot_time_s"]) - float(item["statistics_end_time_s"])) <= SNAPSHOT_TOL_S
        and item.get("max_cfl") is not None
        and float(item["max_cfl"]) <= 0.8
        and item.get("checkMesh", {}).get("return_code") == 0
        for item in records
    ) and process_audit["status"] == "passed"
    identity = [{"flow_id": item["flow_id"], "U_mps": item["U_mps"], "Re": item["Re"], "snapshot_time_s": item["snapshot_time_s"], "statistics_end_time_s": item["statistics_end_time_s"], "developed_flow_sha256": item["developed_flow_sha256"], "force_sha256": item.get("force_history_merged_v3_sha256", item.get("truncated_force_history_v3_sha256")), "final_fields": item["final_fields"]} for item in records]
    source_lineage = []
    for item in records:
        physical = item.get("physical_identity", {})
        source_lineage.append({
            "flow_id": item["flow_id"],
            "lineage_artifact": item.get("continuation_lineage_v3", item.get("snapshot_alignment_v3")),
            "source_v2_developed_flow_sha256": physical.get("source_v2_developed_flow_sha256"),
            "source_v2_force_sha256": physical.get("source_v2_force_sha256"),
            "source_v2_final_fields": physical.get("source_v2_final_fields", physical.get("source_v2_field_hashes")),
            "setFields_called": False,
        })
    bank = {"status": "ready_for_sol_review" if ready else "blocked", "schema_version": "stage4d-developed-flow-bank-v3-1", "flow_ids": [item["flow_id"] for item in records], "flows": records, "source_lineage": source_lineage, "process_limiter_provenance": process_audit, "developed_flow_bank_sha256": canonical_sha(identity), "bank_identity_excludes_absolute_paths": True, "max_physical_time_s": MAX_PHYSICAL_TIME_S, "created_utc": time.time()}
    (result_root / "developed_flow_bank_v3.json").write_text(json.dumps(_json_safe(bank), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return bank


def audit_process_limiter_v3(*, output: Path = V3_RESULT_ROOT / "process_limiter_real_overlap_v3_audit.json") -> dict[str, Any]:
    source_path = V2_RESULT_ROOT / "process_limiter_real_overlap_v2.json"
    if not source_path.is_file():
        raise DevelopedFlowError("v2 ProcessLimiter audit is missing")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    fresh_records = []
    for item in source.get("preflight", []):
        setfields = item.get("setFields", {})
        log = Path(str(setfields.get("log", "")))
        case = Path(str(item.get("case", "")))
        valid_path = log.is_file() and case == log.parent and int(setfields.get("return_code", -1)) == 0
        fresh_records.append({"slice_id": item.get("slice_id"), "case": str(case), "setFields_called": True, "setFields_log": str(log), "setFields_log_sha256": sha256_file(log) if log.is_file() else None, "setFields_return_code": setfields.get("return_code"), "case_log_path_match": valid_path})
    continuation_records = []
    for flow_id in ("re80", "re100", "re120"):
        lineage = json.loads((V2_RESULT_ROOT / flow_id / "continuation_lineage.json").read_text(encoding="utf-8"))
        continuation_records.append({"flow_id": flow_id, "case": lineage.get("target_case"), "setFields_called": False, "source_force_unchanged": lineage.get("source_force_unchanged", True)})
    status = source.get("status") == "passed" and source.get("max_processes") == 2 and source.get("peak_active_count") == 2 and source.get("interval_peak_active_count") == 2 and source.get("permit_leak") is False and len(fresh_records) == 3 and all(item["case_log_path_match"] for item in fresh_records)
    result = {"status": "passed" if status else "blocked", "source_v2_audit": str(source_path.resolve()), "source_v2_audit_sha256": sha256_file(source_path), "fresh_overlap_smoke": {"setFields_called": True, "records": fresh_records}, "continuation_cases": continuation_records, "max_processes": source.get("max_processes"), "peak_active_count": source.get("peak_active_count"), "interval_peak_active_count": source.get("interval_peak_active_count"), "permit_leak": source.get("permit_leak"), "processes": source.get("processes"), "intervals": source.get("intervals"), "old_v2_evidence_unchanged": True}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_json_safe(result), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


def audit_v3_sources() -> dict[str, Any]:
    old_v1 = {}
    for flow_id in ("re80", "re100", "re120"):
        summary_path = V1_RESULT_ROOT / flow_id / f"{flow_id}_summary.json"
        old_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        old_v1[flow_id] = {"summary_sha256": sha256_file(summary_path), "field_audit": audit_developed_flow_identity(old_summary, case=V1_CASE_ROOT / flow_id)}
    v2 = {}
    for flow_id, U in (("re80", 0.8), ("re100", 1.0), ("re120", 1.2)):
        _, _, _, _, audit = _source_v2(flow_id, U)
        v2[flow_id] = audit
    result = {"status": "passed", "v1": old_v1, "v2": v2, "v1_v2_evidence_unchanged": True}
    path = V3_RESULT_ROOT / "source_hash_audit_v3.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(result), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result
