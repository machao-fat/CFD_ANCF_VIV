"""Read-only V3 local analysis of historical Stage381--382 evidence (220--370 s)."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.three_slice_statistics_v3.metrics import (  # noqa: E402
    SLICE_IDS, StatisticsV3Error, beat_diagnostic, cross_spectrum_at_targets,
    local_stationarity, power_summary, signal_summary,
)


SEGMENTS = (
    "stage381_cpp_worker_precice_three_slice_continue220_to270_v1",
    "stage382_cpp_worker_precice_three_slice_continue270_to370_v1",
)
RESULTS = ROOT / "results/solver_validation_v3"
RESULT = RESULTS / "three_slice_statistical_contract_v3.json"
GATE = RESULTS / "three_slice_statistical_contract_v3_gate.json"
FORCE_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s+\(\(([^)]*)\)\s+\(([^)]*)\)\)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def force_path(runtime: Path, sid: str) -> Path:
    matches = list((runtime / sid / "postProcessing").glob("forces1/*/forces.dat"))
    if len(matches) != 1:
        raise StatisticsV3Error(f"expected exactly one force file for {runtime.name}/{sid}")
    return matches[0]


def force_y(path: Path) -> dict[int, float]:
    result: dict[int, float] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = FORCE_RE.match(line)
        if not match:
            continue
        pressure = [float(value) for value in match.group(2).split()]
        viscous = [float(value) for value in match.group(3).split()]
        if len(pressure) != 3 or len(viscous) != 3:
            raise StatisticsV3Error(f"invalid force vector in {path}")
        value = pressure[1] + viscous[1]
        if not math.isfinite(value):
            raise StatisticsV3Error(f"non-finite transverse force in {path}")
        tick = int(round(float(match.group(1)) * 1.0e9))
        if tick in result:
            raise StatisticsV3Error(f"duplicate force tick in {path}")
        result[tick] = value
    if not result:
        raise StatisticsV3Error(f"no force samples parsed from {path}")
    return result


def valid_xy(value: object, *, name: str) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != len(SLICE_IDS):
        raise StatisticsV3Error(f"{name} lacks three slice vectors")
    converted: list[list[float]] = []
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            raise StatisticsV3Error(f"{name} has malformed vector")
        coordinate = [float(item) for item in point]
        if not all(math.isfinite(item) for item in coordinate):
            raise StatisticsV3Error(f"{name} has non-finite value")
        converted.append(coordinate)
    return converted


def read_segment(name: str) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    runtime = ROOT / "runtime" / name
    mapping_path = runtime / "logs/mapping_diagnostics.jsonl"
    if not mapping_path.is_file():
        raise StatisticsV3Error(f"missing mapping diagnostics {mapping_path}")
    mapping = [json.loads(line) for line in mapping_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    source_forces = {sid: force_y(force_path(runtime, sid)) for sid in SLICE_IDS}
    rows: list[dict[str, Any]] = []
    for source in mapping:
        step = source.get("global_step")
        time_s = float(source.get("time_s"))
        tick = int(source.get("integer_tick"))
        if not isinstance(step, int) or tick != int(round(time_s * 1.0e9)):
            raise StatisticsV3Error(f"time identity failure in {name}")
        if step % 10:
            continue
        positions = valid_xy(source.get("interface_positions_xy"), name="interface_positions_xy")
        velocities = valid_xy(source.get("interface_velocities_xy"), name="interface_velocities_xy")
        if any(tick not in source_forces[sid] for sid in SLICE_IDS):
            raise StatisticsV3Error(f"force/mapping alignment failure at {time_s}")
        rows.append({
            "global_step": step, "time_s": time_s, "integer_tick": tick,
            "Fy": {sid: source_forces[sid][tick] for sid in SLICE_IDS},
            "y": {sid: positions[index][1] for index, sid in enumerate(SLICE_IDS)},
            "vy": {sid: velocities[index][1] for index, sid in enumerate(SLICE_IDS)},
        })
    if not rows:
        raise StatisticsV3Error(f"no 0.05 s scalar rows in {name}")
    max_errors = {
        key: max(abs(float(row.get(key, float("nan")))) for row in mapping)
        for key in ("virtual_work_error", "force_balance_error", "moment_balance_error")
    }
    if not all(math.isfinite(value) for value in max_errors.values()):
        raise StatisticsV3Error(f"non-finite mapping integrity evidence in {name}")
    manifest = {
        "runtime": str(runtime), "mapping_path": str(mapping_path), "mapping_sha256": sha256(mapping_path),
        "mapping_record_count": len(mapping), "scalar_record_count": len(rows), "force_files": {
            sid: {"path": str(force_path(runtime, sid)), "sha256": sha256(force_path(runtime, sid))} for sid in SLICE_IDS
        }, "max_mapping_errors": max_errors,
    }
    return rows, manifest, mapping


def identity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    checks = {"records_present": bool(rows), "time_tick_identity": True, "global_step_continuity": True, "uniform_sample_dt_0p05_s": True, "finite_local_observables": True, "no_interpolation": True}
    for row in rows:
        checks["time_tick_identity"] &= int(row["integer_tick"]) == int(round(float(row["time_s"]) * 1.0e9))
        checks["finite_local_observables"] &= all(math.isfinite(float(item)) for group in (row["Fy"], row["y"], row["vy"]) for item in group.values())
    for left, right in zip(rows, rows[1:]):
        checks["global_step_continuity"] &= int(right["global_step"]) - int(left["global_step"]) == 10
        checks["uniform_sample_dt_0p05_s"] &= abs(float(right["time_s"]) - float(left["time_s"]) - 0.05) <= 1.0e-9
    return {"checks": checks, "status": "pass" if all(checks.values()) else "fail"}


def window_summary(rows: list[dict[str, Any]], start: float, end: float) -> dict[str, Any]:
    selected = [row for row in rows if start <= float(row["time_s"]) < end]
    if len(selected) < 8:
        raise StatisticsV3Error(f"insufficient V3 data for {start}--{end}")
    times = [float(row["time_s"]) for row in selected]
    slices: dict[str, Any] = {}
    for sid in SLICE_IDS:
        fy = [float(row["Fy"][sid]) for row in selected]
        y = [float(row["y"][sid]) for row in selected]
        vy = [float(row["vy"][sid]) for row in selected]
        slices[sid] = {
            "Fy": signal_summary(times, fy), "y": signal_summary(times, y),
            "vy_rms": math.sqrt(sum(value * value for value in vy) / len(vy)),
            "Fy_y_cross_spectrum": cross_spectrum_at_targets(times, fy, y),
            "fluid_to_structure_power": power_summary(times, fy, vy),
        }
    pairs = {
        f"{left}__{right}": cross_spectrum_at_targets(times, [row["Fy"][left] for row in selected], [row["Fy"][right] for row in selected])
        for left, right in ((SLICE_IDS[0], SLICE_IDS[1]), (SLICE_IDS[0], SLICE_IDS[2]), (SLICE_IDS[1], SLICE_IDS[2]))
    }
    return {"start_time_s": start, "end_time_s": float(selected[-1]["time_s"]), "sample_count": len(selected), "slices": slices, "slice_slice_cross_spectrum": pairs}


def main() -> int:
    if RESULT.exists() or GATE.exists():
        raise RuntimeError(f"refusing to overwrite V3 historical evidence: {RESULTS}")
    rows: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    raw_mapping: list[dict[str, Any]] = []
    for segment in SEGMENTS:
        segment_rows, manifest, mapping = read_segment(segment)
        rows.extend(segment_rows)
        manifests.append({"name": segment, **manifest})
        raw_mapping.extend(mapping)
    source = identity(rows)
    if source["status"] != "pass":
        raise RuntimeError("source-data integrity failed closed")
    windows = [window_summary(rows, start, end) for start, end in ((220.0, 270.0), (270.0, 320.0), (320.0, 370.0), (270.0, 370.0), (220.0, 370.0))]
    local = local_stationarity(windows[:3])
    mapping_max = {key: max(abs(float(row[key])) for row in raw_mapping) for key in ("virtual_work_error", "force_balance_error", "moment_balance_error")}
    mapping = {"threshold_relative": 1.0e-10, "max_errors": mapping_max,
               "status": "pass" if all(value < 1.0e-10 for value in mapping_max.values()) else "fail",
               "scope": "mathematical H/H^T conservation only; this does not validate the physical force unit scale"}
    full = windows[-1]
    beat = beat_diagnostic(full)
    projection = ROOT / "src/coupling/stage303_interface_mapping_repair_v1/canonical_projection.py"
    writer = ROOT / "tools/stage305_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"
    metadata = {
        "interface_coordinate_semantics": {
            "status": "established_by_source_inspection",
            "value": "absolute_ANCF_projected_position",
            "evidence": "project_interface() returns positions as its first value; the Stage305 writer aliases that result as displacement_xy before writing preCICE Displacement.",
            "analysis_policy": "V3 reports the retained y coordinate as local_y_coordinate_m. It does not relabel it as displacement relative to an independently retained static equilibrium.",
            "projection_source_sha256": sha256(projection), "writer_source_sha256": sha256(writer),
        },
        "force_semantics": {
            "Fy_source": "OpenFOAM forces.dat: pressure_y + viscous_y per slice",
            "physical_force_scaling": "not_evaluable",
            "reason": "Stage381/382 diagnostics do not declare unit_span_m or tributary/slice length; mapping conservation cannot supply missing physical scale.",
        },
    }
    contract = {
        "schema_version": 3, "scope": "read-only historical 220--370 s local three-slice diagnostic", "sample_dt_s": 0.05,
        "windows_s": [[220.0, 270.0], [270.0, 320.0], [320.0, 370.0], [270.0, 370.0], [220.0, 370.0]],
        "local_stationarity_thresholds": {"rms_drift_fraction_max": 0.05, "frequency_drift_fraction_max": 0.05},
        "slice_phase_policy": "diagnostic_only; no assumption that independent 2D slices must remain phase locked", "no_interpolation": True,
    }
    output = {"contract": contract, "metadata": metadata, "source_integrity": source, "source_segments": manifests, "mapping_integrity": mapping,
              "windows": windows, "local_statistical_stationarity": local, "beat_diagnostic": beat}
    gate = {
        "gate_id": "THREE_SLICE_STATISTICAL_CONTRACT_V3_GATE", "scope": contract["scope"],
        "DATA_INTEGRITY": source["status"], "MAPPING_INTEGRITY": mapping["status"],
        "LOCAL_STATISTICAL_STABILITY": local["status"],
        "LOCAL_FLUID_STRUCTURE_SYNCHRONIZATION": "not_completed",
        "LOCAL_FLUID_STRUCTURE_SYNCHRONIZATION_REASON": "Coherence, frequency ratios and raw-scale power are reported, but no historical force-scale contract or predeclared lock-in acceptance criterion exists.",
        "SLICE_PHASE_COHERENCE": "diagnostic", "PHYSICAL_FORCE_SCALING": "not_evaluable",
        "FORMAL_LOCK_IN": "not_completed", "FORMAL_VIV_VALIDATION": "not_completed",
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
        "conclusion": "V3 separates complete retained data and H/H^T mapping conservation from physically scaled force validation and from local fluid-structure synchronization. Slice-slice phase remains a diagnostic, not a primary stability veto.",
        "old_runtime_modified": False, "real_process_starts": {"CFD": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0},
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    GATE.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": str(RESULT), "gate": {key: gate[key] for key in ("DATA_INTEGRITY", "MAPPING_INTEGRITY", "LOCAL_STATISTICAL_STABILITY", "PHYSICAL_FORCE_SCALING")}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
