"""Offline reclassification and dt1 statistics for v2.2.2."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from src.coupling.stage4e_target_re_pilot_v2.analysis_v2 import (
    corrected_coefficients_from_raw,
    _frequency_gate,
    numeric_rows,
    parse_raw_forces,
)
from src.coupling.stage4e_target_re_pilot_v2_2.analysis_v2_2 import (
    _force_paths,
    coefficient_crosscheck_all,
    log_health,
    merge_force_history,
    numeric_time_directories,
    parse_cfl,
    parse_checkmesh,
    checkpoint_alignment,
)
from .identity_v2_2_2 import (
    BOOTSTRAP_SEED,
    D,
    FORMAL_CFL_TARGET,
    HARD_CFL,
    MAX_CYCLES,
    MIN_CYCLES,
    U_HIGH,
    B_MESH,
    finite,
    sha256_file,
)

METRICS = ("mean_Cd", "Cd_fluctuation_RMS", "Cl_fluctuation_RMS", "Cl_peak_to_peak", "St")
TIME_LIMITS = {"mean_Cd": 0.02, "St": 0.02, "Cd_fluctuation_RMS": 0.05, "Cl_fluctuation_RMS": 0.05, "Cl_peak_to_peak": 0.05}
SPATIAL_LIMITS = {"mean_Cd": 0.02, "St": 0.02, "Cd_fluctuation_RMS": 0.05, "Cl_fluctuation_RMS": 0.05}


def overlap_force_audit_fast(paths: list[Path], *, time_tolerance: float = 1.0e-10, force_absolute_tolerance: float = 1.0e-10, l2_tolerance: float = 1.0e-10, component_floor_N: float = 1.0e-10) -> dict[str, Any]:
    """Vectorized equivalent of the upstream overlap audit."""
    ordered = sorted(paths, key=lambda path: float(path.parent.name))
    records: list[dict[str, Any]] = []
    for first, second in zip(ordered, ordered[1:]):
        a = numeric_rows(first, minimum=7)
        b = numeric_rows(second, minimum=7)
        if not a.size or not b.size:
            records.append({"first": str(first), "second": str(second), "passed": False, "reason": "empty force history"})
            continue
        positions = np.searchsorted(b[:, 0], a[:, 0], side="left")
        left = np.clip(positions - 1, 0, len(b) - 1)
        right = np.clip(positions, 0, len(b) - 1)
        left_diff = np.abs(b[left, 0] - a[:, 0])
        right_diff = np.abs(b[right, 0] - a[:, 0])
        indices = np.where(right_diff < left_diff, right, left)
        time_diff = a[:, 0] - b[indices, 0]
        matched = np.abs(time_diff) <= time_tolerance
        if not np.any(matched):
            records.append({"first": str(first), "second": str(second), "overlap_sample_count": 0, "passed": True, "reason": "no common physical-time rows"})
            continue
        ia = np.flatnonzero(matched)
        ib = indices[matched]
        diff = a[ia] - b[ib]
        force_diff = diff[:, 1:7]
        ref = a[ia, 1:7]
        l2 = float(np.linalg.norm(force_diff) / max(np.linalg.norm(ref), 1.0e-30))
        component_rel = float(np.max(np.abs(force_diff) / np.maximum(np.abs(ref), component_floor_N)))
        records.append(finite({"first": str(first), "second": str(second), "overlap_start_s": float(max(a[ia[0], 0], b[ib[0], 0])), "overlap_end_s": float(min(a[ia[-1], 0], b[ib[-1], 0])), "overlap_sample_count": int(len(ia)), "maximum_time_error_s": float(np.max(np.abs(time_diff[matched]))), "maximum_absolute_force_error_N": float(np.max(np.abs(force_diff))), "normalized_l2_relative_error": l2, "maximum_component_relative_error": component_rel, "component_absolute_floor_N": component_floor_N, "passed": bool(np.max(np.abs(time_diff[matched])) <= time_tolerance and np.max(np.abs(force_diff)) <= force_absolute_tolerance and l2 <= l2_tolerance)}))
    return finite({"schema_version": "stage4e-b2-a-v2.2.2-overlap-force-audit-0.1.0", "thresholds": {"time_s": time_tolerance, "absolute_force_N": force_absolute_tolerance, "normalized_l2": l2_tolerance}, "records": records, "passed": bool(records) and all(item.get("passed", False) for item in records)})


def relative_change(a: float | None, b: float | None, epsilon: float = 1.0e-12) -> float | None:
    """Return |a-b|/max(|b|, epsilon), with b as the frozen reference."""
    if a is None or b is None:
        return None
    return abs(float(a) - float(b)) / max(abs(float(b)), epsilon)


def compare_metrics(a: dict[str, Any], b: dict[str, Any], limits: dict[str, float]) -> dict[str, Any]:
    changes = {key: relative_change(a.get(key), b.get(key)) for key in limits}
    return finite({"reference_direction": "relative_change(a,b)=abs(a-b)/max(abs(b),epsilon); b is reference", "relative_changes": changes, "limits": limits, "passed": all(value is not None and value <= limits[key] for key, value in changes.items())})


def _trend(values: list[float]) -> str:
    if len(values) < 3:
        return "insufficient_data"
    increments = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    if all(value >= 0.0 for value in increments) or all(value <= 0.0 for value in increments):
        return "monotonic"
    return "non_monotonic"


def offline_reclassification(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    levels = ("coarse", "medium", "fine")
    values = {metric: [summaries[level].get("statistics", {}).get(metric) for level in levels] for metric in METRICS}
    rows = {}
    for metric, series in values.items():
        rows[metric] = {
            "coarse_medium": relative_change(series[0], series[1]),
            "medium_fine": relative_change(series[1], series[2]),
            "values": series,
            "trend": _trend([float(value) for value in series if value is not None]),
        }
    fine_gate = summaries["fine"].get("statistics_gate", {})
    stability = fine_gate.get("stability", {})
    changes = stability.get("changes", {})
    over_limit = {key: max((float(value) for value in values if value is not None), default=None) for key, values in changes.items()}
    over_limit_keys = [key for key, value in over_limit.items() if value is not None and value > 0.05]
    marginal = over_limit_keys == ["Cd_fluctuation_RMS"] and abs(float(over_limit["Cd_fluctuation_RMS"]) - 0.05) < 0.001
    cfl = summaries["fine"].get("production_max_CFL")
    return finite({
        "schema_version": "stage4e-b2-a-v2.2.2-offline-reclassification-0.1.0",
        "reference_direction": "coarse_to_medium and medium_to_fine; relative_change(a,b) uses b as reference",
        "fine_status": {
            "solver_completed": bool(summaries["fine"].get("runtime_valid")),
            "runtime_valid": bool(summaries["fine"].get("runtime_valid")),
            "statistics_valid": bool(summaries["fine"].get("statistics_valid")),
            "production_max_CFL": cfl,
            "formal_target": FORMAL_CFL_TARGET,
            "hard_stop": HARD_CFL,
            "cfl_target_failed_but_hard_stop_not_crossed": cfl is not None and float(cfl) > FORMAL_CFL_TARGET and float(cfl) < HARD_CFL,
            "stationarity_classification": "marginal_stationarity_failure" if marginal else ("stationarity_failure" if over_limit_keys else "passed"),
            "stability_changes": changes,
            "stability_over_limit_keys": over_limit_keys,
        },
        "metrics": rows,
        "gci_eligible": False,
        "gci_not_used_reason": "fine formal statistics are invalid under the frozen CFL/stationarity gate",
        "diagnostic_trend_not_hidden": True,
    })


def spatial_trend_diagnostic(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    audit = offline_reclassification(summaries)
    classifications = {metric: row["trend"] for metric, row in audit["metrics"].items()}
    non_monotonic = [metric for metric, trend in classifications.items() if trend == "non_monotonic"]
    return finite({
        "schema_version": "stage4e-b2-a-v2.2.2-spatial-trend-diagnostic-0.1.0",
        "effective_h": {level: 1.0 / math.sqrt(float(summaries[level]["mesh_audit"]["cells"])) for level in ("coarse", "medium", "fine")},
        "trend_classification": classifications,
        "non_monotonic_metrics": non_monotonic,
        "overall_interpretation": "non_monotonic_or_not_asymptotic" if non_monotonic else "monotonic_but_not_yet_proven_asymptotic",
        "fine_is_diagnostic_not_formal": True,
        "audit": audit,
    })


def _zero_crossings(time: np.ndarray, signal: np.ndarray) -> list[float]:
    x = signal - float(np.mean(signal))
    result: list[float] = []
    for index in np.flatnonzero((x[:-1] <= 0.0) & (x[1:] > 0.0)):
        denominator = x[index + 1] - x[index]
        fraction = 0.0 if denominator == 0.0 else -x[index] / denominator
        result.append(float(time[index] + fraction * (time[index + 1] - time[index])))
    return result


def _window_row(time: np.ndarray, cd: np.ndarray, cl: np.ndarray) -> dict[str, Any]:
    freq = _frequency_gate(time, cl, U_abs=U_HIGH, diameter=D)
    mean_cd = float(np.mean(cd))
    return finite({
        "mean_Cd": mean_cd,
        "Cd_fluctuation_RMS": float(np.sqrt(np.mean((cd - mean_cd) ** 2))),
        "Cl_fluctuation_RMS": float(np.sqrt(np.mean((cl - np.mean(cl)) ** 2))),
        "Cl_peak_to_peak": float(np.ptp(cl)),
        "St": freq.get("St"),
        "frequency_status": freq.get("frequency_status"),
        "sample_count": int(len(time)),
        "duration_s": float(time[-1] - time[0]) if len(time) else 0.0,
    })


def _bootstrap(values: np.ndarray, rng: np.random.Generator, count: int = 2000) -> dict[str, Any]:
    if len(values) == 0:
        return {"sample_count": 0, "mean": None, "std": None, "ci95": [None, None], "bootstrap_seed": BOOTSTRAP_SEED}
    means = np.empty(count, dtype=float)
    for index in range(count):
        means[index] = float(np.mean(rng.choice(values, size=len(values), replace=True)))
    return finite({"sample_count": int(len(values)), "mean": float(np.mean(values)), "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0, "ci95": [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))], "bootstrap_seed": BOOTSTRAP_SEED, "bootstrap_replicates": count})


def cycle_block_uncertainty(case_dir: Path, *, discard_cycles: int = 5) -> dict[str, Any]:
    paths = _force_paths(case_dir)
    merged = merge_force_history(paths)
    if not merged.get("available"):
        return {"available": False, "reason": "force history unavailable", "force_paths": [str(path) for path in paths]}
    corrected = corrected_coefficients_from_raw(merged, U_abs=U_HIGH, b_mesh=B_MESH)
    time = np.asarray(corrected["time_s"], dtype=float)
    cd = np.asarray(corrected["Cd"], dtype=float)
    cl = np.asarray(corrected["Cl"], dtype=float)
    crossings = _zero_crossings(time, cl)
    if len(crossings) <= discard_cycles + 2:
        return {"available": False, "reason": "fewer than discard_cycles plus two complete cycles", "crossing_count": len(crossings), "force_paths": [str(path) for path in paths]}
    start_time = crossings[discard_cycles]
    mask = time >= start_time
    t, cdx, clx = time[mask], cd[mask], cl[mask]
    freq = _frequency_gate(t, clx, U_abs=U_HIGH, diameter=D)
    windows = [_window_row(t[idx], cdx[idx], clx[idx]) for idx in np.array_split(np.arange(len(t)), 3) if len(idx) >= 3]
    cycle_rows: list[dict[str, Any]] = []
    for left, right in zip(crossings[discard_cycles:-1], crossings[discard_cycles + 1:]):
        cycle_mask = (time >= left) & (time < right)
        if int(np.count_nonzero(cycle_mask)) < 3:
            continue
        tc, cdc, clc = time[cycle_mask], cd[cycle_mask], cl[cycle_mask]
        cycle_rows.append({"start_s": left, "end_s": right, "period_s": right - left, "frequency_Hz": 1.0 / (right - left), "mean_Cd": float(np.mean(cdc)), "Cl_RMS": float(np.sqrt(np.mean((clc - np.mean(clc)) ** 2))), "Cl_peak_to_peak": float(np.ptp(clc))})
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    cycle_arrays = {key: np.asarray([row[key] for row in cycle_rows], dtype=float) for key in ("mean_Cd", "Cl_RMS", "Cl_peak_to_peak", "frequency_Hz")}
    return finite({
        "available": True,
        "force_paths": [str(path) for path in paths],
        "force_sample_count": int(len(time)),
        "discard_cycles": discard_cycles,
        "discard_start_s": float(start_time),
        "crossing_count": int(len(crossings)),
        "complete_cycle_count": int(len(cycle_rows)),
        "effective_cycles": freq.get("effective_cycles"),
        "statistics": _window_row(t, cdx, clx) | {key: value for key, value in freq.items() if key in ("frequency_status", "dominant_frequency_Hz", "zero_crossing_frequency_Hz", "autocorrelation_frequency_Hz", "St", "effective_cycles", "frequency_consistency_relative")},
        "three_windows": windows,
        "cycle_rows": cycle_rows,
        "cycle_summary": {key: _bootstrap(values, rng) for key, values in cycle_arrays.items()},
        "bootstrap_seed": BOOTSTRAP_SEED,
    })


def time_step_comparison(reference_dt2: dict[str, Any], dt1: dict[str, Any]) -> dict[str, Any]:
    comparison = compare_metrics(reference_dt2.get("statistics", {}), dt1.get("statistics", {}), TIME_LIMITS)
    return finite({"dt2_case_id": reference_dt2.get("case_id"), "dt1_case_id": dt1.get("case_id"), "dt2_s": reference_dt2.get("dt_s"), "dt1_s": dt1.get("dt_s"), "comparison": comparison, "dt1_statistics_valid": bool(dt1.get("statistics_valid")), "passed": bool(dt1.get("statistics_valid") and comparison.get("passed"))})


def spatial_dt1_comparison(medium: dict[str, Any], fine: dict[str, Any]) -> dict[str, Any]:
    comparison = compare_metrics(medium.get("statistics", {}), fine.get("statistics", {}), SPATIAL_LIMITS)
    return finite({"reference_direction": "medium_dt1 as a, fine_dt1 as b", "medium_case_id": medium.get("case_id"), "fine_case_id": fine.get("case_id"), "comparison": comparison, "both_statistics_valid": bool(medium.get("statistics_valid") and fine.get("statistics_valid")), "passed": bool(medium.get("statistics_valid") and fine.get("statistics_valid") and comparison.get("passed"))})


def decision_matrix(*, medium_dt1_passed: bool, fine_dt1_passed: bool, time_passed: bool, spatial_passed: bool) -> dict[str, Any]:
    if not medium_dt1_passed:
        status = "rejected_or_blocked_practical_time_nonconvergence"
        reason = "medium_dt1_failed"
    elif not fine_dt1_passed:
        status = "rejected_or_blocked_practical_time_nonconvergence"
        reason = "fine_dt1_failed"
    elif not time_passed:
        status = "rejected_or_blocked_practical_time_nonconvergence"
        reason = "dt2_to_dt1_threshold_failed"
    elif not spatial_passed:
        status = "rejected_spatial_nonconvergence"
        reason = "medium_dt1_to_fine_dt1_threshold_failed"
    else:
        status = "eligible_for_conditional_coarse_dt1"
        reason = "time_and_medium_to_fine_spatial_thresholds_passed"
    return {"LAMINAR_HIGH_RE_MODEL_STATUS": status, "reason": reason, "coarse_dt1_allowed": status == "eligible_for_conditional_coarse_dt1", "domain_and_low_middle_allowed": False}


def mesh_lineage_audit(source_case: Path, target_case: Path, source_time: str, source_run_id: str, target_run_id: str, *, checkmesh: dict[str, Any]) -> dict[str, Any]:
    source_latest = source_case / source_time
    target_local = target_case / "0"
    names = ("U", "p", "phi")
    source_hashes = {name: sha256_file(source_latest / name) for name in names}
    target_hashes = {name: sha256_file(target_local / name) for name in names}
    source_points = sha256_file(source_case / "constant" / "polyMesh" / "points")
    target_points = sha256_file(target_case / "constant" / "polyMesh" / "points")
    identity = {"source_run_id": source_run_id, "source_physical_time_s": float(source_time), "target_run_id": target_run_id, "target_local_time_s": 0.0, "source_field_hashes": source_hashes, "target_initial_field_hashes": target_hashes, "source_points_sha256": source_points, "target_points_sha256": target_points, "points_identical": source_points == target_points, "fields_identical": source_hashes == target_hashes, "checkMesh": checkmesh}
    return finite({**identity, "lineage_sha256": __import__("hashlib").sha256(__import__("json").dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()})


__all__ = ["METRICS", "TIME_LIMITS", "SPATIAL_LIMITS", "relative_change", "offline_reclassification", "spatial_trend_diagnostic", "cycle_block_uncertainty", "time_step_comparison", "spatial_dt1_comparison", "decision_matrix", "mesh_lineage_audit", "coefficient_crosscheck_all", "log_health", "overlap_force_audit_fast", "parse_cfl", "parse_checkmesh", "checkpoint_alignment", "numeric_time_directories", "_force_paths"]
