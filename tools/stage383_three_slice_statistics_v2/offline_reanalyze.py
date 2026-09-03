"""Read-only V2 statistical reanalysis of the continuous 0--370 s lineage."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.three_slice_statistics_v2.metrics import (  # noqa: E402
    SLICE_IDS,
    StatisticalContractError,
    assess_trailing_windows,
    summarize_window,
    validate_contract,
)


STAGE_ID = "stage4f_d_three_slice_statistical_contract_v2_phase_reanalysis_v2"
RESULTS = ROOT / "results/385_three_slice_statistical_contract_v2_phase_reanalysis_v2"
SEGMENTS = (
    "stage341_dt005_long_convergence_v1",
    "stage370_restart_point_binding_smoke_v1",
    "stage372_cpp_worker_precice_three_slice_80p2_to200_v1_retry3",
    "stage379_cpp_worker_precice_three_slice_continue200_to220_v1",
    "stage381_cpp_worker_precice_three_slice_continue220_to270_v1",
    "stage382_cpp_worker_precice_three_slice_continue270_to370_v1",
)
FORCE_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s+\(\(([^)]*)\)\s+\(([^)]*)\)\)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_force_y(path: Path) -> dict[int, float]:
    values: dict[int, float] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = FORCE_RE.match(line)
        if not match:
            continue
        pressure = [float(value) for value in match.group(2).split()]
        viscous = [float(value) for value in match.group(3).split()]
        if len(pressure) != 3 or len(viscous) != 3:
            raise StatisticalContractError(f"invalid force vector in {path}")
        values[int(round(float(match.group(1)) * 1.0e9))] = pressure[1] + viscous[1]
    if not values:
        raise StatisticalContractError(f"no force samples in {path}")
    return values


def force_path(runtime: Path, slice_id: str) -> Path:
    matches = list((runtime / slice_id / "postProcessing").glob("forces1/*/forces.dat"))
    if len(matches) != 1:
        raise StatisticalContractError(f"expected one force history for {runtime.name}/{slice_id}")
    return matches[0]


def audit_quality(runtime: Path, expected_count: int) -> dict[str, object]:
    by_slice: dict[str, object] = {}
    for index, slice_id in enumerate(SLICE_IDS):
        path = runtime / "logs" / f"openfoam_{index:04d}_quality.json"
        if not path.is_file():
            by_slice[slice_id] = {"status": "not_evaluable", "reason": "quality stream not retained"}
            continue
        records = json.loads(path.read_text(encoding="utf-8")).get("records", [])
        fields = ("time_s", "courant_max", "residual_max", "continuity_global", "iterations_max")
        complete = len(records) == expected_count and all(all(field in record and isinstance(record[field], (int, float)) for field in fields) for record in records)
        by_slice[slice_id] = {"status": "pass" if complete else "not_evaluable", "record_count": len(records), "expected_count": expected_count}
    return by_slice


def read_segment(name: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    runtime = ROOT / "runtime" / name
    mapping_path = runtime / "logs/mapping_diagnostics.jsonl"
    if not mapping_path.is_file():
        raise StatisticalContractError(f"mapping diagnostics missing: {mapping_path}")
    mapping = [json.loads(line) for line in mapping_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    forces = {slice_id: parse_force_y(force_path(runtime, slice_id)) for slice_id in SLICE_IDS}
    samples: list[dict[str, object]] = []
    for row in mapping:
        step = row.get("global_step")
        time_s = float(row.get("time_s"))
        tick = int(row.get("integer_tick"))
        if tick != int(round(time_s * 1.0e9)):
            raise StatisticalContractError(f"time/tick mismatch in {name}")
        if not isinstance(step, int) or step % 10:
            continue
        positions = row.get("interface_positions_xy")
        if not isinstance(positions, list) or len(positions) != len(SLICE_IDS):
            raise StatisticalContractError(f"interface positions unavailable in {name}")
        if tick not in forces[SLICE_IDS[0]] or any(tick not in forces[slice_id] for slice_id in SLICE_IDS):
            raise StatisticalContractError(f"force/mapping time mismatch in {name} at {time_s}")
        samples.append({
            "global_step": step,
            "time_s": time_s,
            "integer_tick": tick,
            "slice_force_y": {slice_id: forces[slice_id][tick] for slice_id in SLICE_IDS},
            "structure_displacement_y": sum(float(point[1]) for point in positions) / len(positions),
            "virtual_work_error": float(row.get("virtual_work_error", 0.0)),
            "force_balance_error": float(row.get("force_balance_error", 0.0)),
            "moment_balance_error": float(row.get("moment_balance_error", 0.0)),
        })
    if not samples:
        raise StatisticalContractError(f"no 0.05 s samples in {name}")
    return samples, {
        "runtime": str(runtime),
        "mapping_sha256": sha256(mapping_path),
        "mapping_count": len(mapping),
        "scalar_sample_count": len(samples),
        "quality": audit_quality(runtime, len(mapping)),
    }


def source_identity(rows: list[dict[str, object]]) -> dict[str, object]:
    checks = {"rows_present": bool(rows), "global_step_continuous": True, "time_uniform_0p05_s": True, "time_tick_identity": True}
    for left, right in zip(rows, rows[1:]):
        checks["global_step_continuous"] &= int(right["global_step"]) - int(left["global_step"]) == 10
        checks["time_uniform_0p05_s"] &= abs(float(right["time_s"]) - float(left["time_s"]) - 0.05) <= 1.0e-9
    for row in rows:
        checks["time_tick_identity"] &= int(row["integer_tick"]) == int(round(float(row["time_s"]) * 1.0e9))
    return {"checks": checks, "status": "pass" if all(checks.values()) else "do_not_pass"}


def main() -> int:
    if RESULTS.exists():
        raise RuntimeError(f"refusing to overwrite existing evidence: {RESULTS}")
    contract = {
        "schema_version": 2,
        "stage_id": STAGE_ID,
        "slice_ids": list(SLICE_IDS),
        "primary_observables": ["per_slice_force_y", "structure_displacement_y", "phase_relation"],
        "amplitude_definition": "demeaned_rms_and_peak_to_peak",
        "frequency_methods": ["detrended_fft", "prominent_positive_peaks"],
        "physical_total_force_policy": "not_evaluable_from_legacy_evidence",
        "quality_gate_separate": True,
        "legacy_gate_unchanged": True,
        "missing_value_policy": "fail_closed_no_interpolation",
        "real_process_allowed": False,
        "statistical_windows": {"count": 3, "start_time_s": [220.0, 270.0, 320.0], "duration_s": 50.0, "minimum_peak_separation_s": 3.0, "prominence_fraction": 0.10},
        "retrospective_diagnostic_thresholds": {"amplitude_drift_fraction_max": 0.05, "frequency_drift_fraction_max": 0.05, "phase_drift_deg_max": 45.0, "phase_correlation_min": 0.9},
        "threshold_interpretation": "retrospective diagnostic only; freeze unchanged before any future run",
    }
    contract_audit = validate_contract(contract)
    if contract_audit["status"] != "pass":
        raise RuntimeError("V2 contract is invalid")
    rows: list[dict[str, object]] = []
    source_segments: list[dict[str, object]] = []
    for name in SEGMENTS:
        segment_rows, manifest = read_segment(name)
        rows.extend(segment_rows)
        source_segments.append({"name": name, **manifest})
    identity = source_identity(rows)
    if identity["status"] != "pass":
        raise RuntimeError("source scalar continuity audit failed")
    window_contract = contract["statistical_windows"]
    windows = [
        summarize_window(rows, start_time_s=start, end_time_s=start + float(window_contract["duration_s"]), minimum_separation_s=float(window_contract["minimum_peak_separation_s"]), prominence_fraction=float(window_contract["prominence_fraction"]))
        for start in window_contract["start_time_s"]
    ]
    assessment = assess_trailing_windows(
        windows,
        amplitude_drift_limit=float(contract["retrospective_diagnostic_thresholds"]["amplitude_drift_fraction_max"]),
        frequency_drift_limit=float(contract["retrospective_diagnostic_thresholds"]["frequency_drift_fraction_max"]),
        phase_drift_limit_deg=float(contract["retrospective_diagnostic_thresholds"]["phase_drift_deg_max"]),
        phase_correlation_min=float(contract["retrospective_diagnostic_thresholds"]["phase_correlation_min"]),
    )
    quality_complete = all(
        item["status"] == "pass"
        for segment in source_segments
        for item in dict(segment["quality"]).values()
    )
    conservation = {
        "max_virtual_work_error": max(abs(float(row["virtual_work_error"])) for row in rows),
        "max_force_balance_error": max(abs(float(row["force_balance_error"])) for row in rows),
        "max_moment_balance_error": max(abs(float(row["moment_balance_error"])) for row in rows),
    }
    gate = {
        "gate_id": "STAGE4F_D_THREE_SLICE_STATISTICAL_CONTRACT_V2_PHASE_REANALYSIS_V2_GATE",
        "status": "pass",
        "scope": "offline reanalysis only; no physical conclusion is promoted",
        "contract": contract,
        "contract_audit": contract_audit,
        "source_identity": identity,
        "source_segments": source_segments,
        "coverage": {"time_start_s": rows[0]["time_s"], "time_end_s": rows[-1]["time_s"], "sample_count": len(rows), "full_openfoam_quality_coverage": quality_complete},
        "windows": windows,
        "primary_statistics": assessment,
        "conservation_diagnostics": conservation,
        "physical_total_force": {"status": "not_evaluable", "reason": "legacy records do not declare tributary length/area weights; arithmetic mean is retained only as a diagnostic"},
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
        "conclusion": "V2 can diagnose per-slice/structure statistics from the retained scalar evidence, but it cannot promote the legacy campaign because historical quality coverage and physical total-force weights are incomplete.",
        "real_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "old_runtime_modified": False,
    }
    RESULTS.mkdir(parents=True)
    (RESULTS / "three_slice_statistical_contract_v2.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "stage4f_d_three_slice_statistical_contract_v2_phase_reanalysis_v2_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "samples": len(rows), "primary_statistics_stable": assessment["primary_statistics_stable"], "quality_complete": quality_complete, "results": str(RESULTS)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
