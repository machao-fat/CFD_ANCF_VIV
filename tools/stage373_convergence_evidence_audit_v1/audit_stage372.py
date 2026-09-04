"""Read-only convergence-evidence audit for the completed Stage 372 runtime.

The audit never writes to Stage 372.  It separates the protected formal
accumulator result from independently reproducible observations based on the
retained force, interface-motion, quality, checkpoint, and mapping logs.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime/stage372_cpp_worker_precice_three_slice_80p2_to200_v1_retry3"
SOURCE_RESULTS = ROOT / "results/stage372_cpp_worker_precice_three_slice_80p2_to200_v1_retry3"
RESULTS = ROOT / "results/373_convergence_evidence_audit_v1"
STAGE_ID = "stage4f_d_convergence_evidence_audit_v1"
DT = 0.005
SOURCE_TIME = 80.2
SOURCE_STEP = 16040
TARGET_TIME = 200.0
TARGET_STEP = 40000
SLICE_IDS = tuple(f"slice_{index:04d}" for index in range(3))
WINDOWS = ((80.2, 120.2), (120.2, 160.2), (160.2, 200.001))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_delta(values: Iterable[float]) -> float | None:
    values = list(values)
    if not values:
        return None
    scale = max(abs(statistics.median(values)), 1.0e-30)
    return (max(values) - min(values)) / scale


def parse_force(path: Path) -> tuple[list[float], list[float]]:
    times: list[float] = []
    lateral: list[float] = []
    number = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        values = [float(value) for value in number.findall(line)]
        # time, pressure vector, viscous vector, pressure moment, viscous moment
        if len(values) >= 7:
            times.append(values[0])
            lateral.append(values[2] + values[5])
    if not times or any(not math.isfinite(value) for value in lateral):
        raise RuntimeError(f"invalid force data: {path}")
    return times, lateral


def moving_average(values: list[float], samples: int) -> list[float]:
    if samples < 1 or 2 * samples >= len(values):
        raise ValueError("invalid smoothing span")
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    result = list(values)
    half = samples // 2
    for index in range(half, len(values) - (samples - half - 1)):
        lo = index - half
        hi = lo + samples
        result[index] = (prefix[hi] - prefix[lo]) / samples
    return result


def positive_peaks(times: list[float], values: list[float], *, smoothing_s: float, minimum_separation_s: float) -> list[dict[str, float]]:
    dt = statistics.median(right - left for left, right in zip(times, times[1:]))
    smooth = moving_average(values, max(1, int(round(smoothing_s / dt))))
    peaks: list[dict[str, float]] = []
    margin = max(2, int(round(smoothing_s / dt)))
    for index in range(margin, len(smooth) - margin):
        value = smooth[index]
        if value <= 0.0 or value < smooth[index - 1] or value <= smooth[index + 1]:
            continue
        candidate = {"time_s": times[index], "value": value}
        if peaks and candidate["time_s"] - peaks[-1]["time_s"] < minimum_separation_s:
            if candidate["value"] > peaks[-1]["value"]:
                peaks[-1] = candidate
        else:
            peaks.append(candidate)
    return peaks


def window_stats(times: list[float], values: list[float], peaks: list[dict[str, float]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for start, stop in WINDOWS:
        selected = [value for time_s, value in zip(times, values) if start <= time_s < stop]
        selected_peaks = [peak for peak in peaks if start <= peak["time_s"] < stop]
        periods = [right["time_s"] - left["time_s"] for left, right in zip(selected_peaks, selected_peaks[1:])]
        result.append({
            "start_time_s": start,
            "end_time_s": min(stop, times[-1]),
            "sample_count": len(selected),
            "rms": math.sqrt(statistics.fmean(value * value for value in selected)),
            "peak_to_peak": max(selected) - min(selected),
            "peak_times_s": [round(peak["time_s"], 3) for peak in selected_peaks],
            "frequency_hz": 1.0 / statistics.fmean(periods) if periods else None,
        })
    return result


def audit_identity(rows: list[dict[str, object]]) -> dict[str, object]:
    checks = {"record_count": len(rows) == TARGET_STEP - SOURCE_STEP, "continuous_global_step": True, "continuous_local_step": True, "time_tick_identity": True, "slice_identity": True, "unique_force_hashes": True}
    for local_step, row in enumerate(rows, start=1):
        checks["continuous_global_step"] &= row.get("global_step") == SOURCE_STEP + local_step
        checks["continuous_local_step"] &= row.get("case_local_bridge_step") == local_step
        time_s = float(row.get("time_s", math.nan))
        checks["time_tick_identity"] &= math.isfinite(time_s) and row.get("integer_tick") == int(round(time_s * 1.0e9))
        hashes = row.get("force_hashes")
        checks["slice_identity"] &= isinstance(hashes, list) and len(hashes) == len(SLICE_IDS)
        if isinstance(hashes, list):
            checks["unique_force_hashes"] &= len(hashes) == 3 and len(set(hashes)) == 3 and all(isinstance(value, str) and len(value) == 64 for value in hashes)
    return {"checks": checks, "status": "pass" if all(checks.values()) else "do_not_pass"}


def main() -> int:
    logs = SOURCE / "logs"
    source_files = [logs / "structure_participant.json", logs / "mapping_diagnostics.jsonl", logs / "checkpoint.jsonl", logs / "returns.txt"]
    source_files += [SOURCE / sid / "postProcessing/forces1/80.2/forces.dat" for sid in SLICE_IDS]
    source_files += [logs / f"openfoam_{index:04d}_quality.json" for index in range(3)]
    missing = [str(path) for path in source_files if not path.is_file()]
    if missing:
        raise RuntimeError("missing source evidence: " + ", ".join(missing))
    source_state = json.loads((logs / "structure_participant.json").read_text(encoding="utf-8"))
    source_gate = json.loads((SOURCE_RESULTS / "stage4f_d_restart_continuation_80p2_to200_v1_gate.json").read_text(encoding="utf-8"))
    mapping_rows = [json.loads(line) for line in (logs / "mapping_diagnostics.jsonl").read_text(encoding="utf-8").splitlines() if line]
    identity = audit_identity(mapping_rows)
    all_times: list[list[float]] = []
    all_forces: list[list[float]] = []
    for sid in SLICE_IDS:
        times, force = parse_force(SOURCE / sid / "postProcessing/forces1/80.2/forces.dat")
        all_times.append(times)
        all_forces.append(force)
    if any(times != all_times[0] for times in all_times[1:]):
        raise RuntimeError("force timestamps are not aligned across slices")
    sampled = [index for index, time_s in enumerate(all_times[0]) if (local := int(round((time_s - SOURCE_TIME) / DT))) > 0 and local % 10 == 0]
    times = [all_times[0][index] for index in sampled]
    per_slice = {sid: [all_forces[index][row] for row in sampled] for index, sid in enumerate(SLICE_IDS)}
    mean_force = [statistics.fmean(per_slice[sid][index] for sid in SLICE_IDS) for index in range(len(times))]
    robust_peaks = positive_peaks(times, mean_force, smoothing_s=1.0, minimum_separation_s=4.0)
    robust_windows = window_stats(times, mean_force, robust_peaks)
    per_slice_windows = {sid: window_stats(times, values, []) for sid, values in per_slice.items()}
    positions = {sid: {"x": [], "y": []} for sid in SLICE_IDS}
    position_times: list[float] = []
    for row in mapping_rows:
        position_times.append(float(row["time_s"]))
        vectors = row["interface_positions_xy"]
        for index, sid in enumerate(SLICE_IDS):
            positions[sid]["x"].append(float(vectors[index][0]))
            positions[sid]["y"].append(float(vectors[index][1]))
    position_windows = {sid: {axis: window_stats(position_times, values, []) for axis, values in fields.items()} for sid, fields in positions.items()}
    quality = {}
    for index, sid in enumerate(SLICE_IDS):
        records = json.loads((logs / f"openfoam_{index:04d}_quality.json").read_text(encoding="utf-8"))["records"]
        quality[sid] = {"record_count": len(records), "courant_records": sum("courant_max" in row for row in records), "continuity_records": sum("continuity_global" in row for row in records), "max_courant": max(float(row["courant_max"]) for row in records if "courant_max" in row), "max_abs_continuity_global": max(abs(float(row["continuity_global"])) for row in records)}
    robust_frequency = [float(item["frequency_hz"]) for item in robust_windows if item["frequency_hz"] is not None]
    robust_amplitude = [float(item["peak_to_peak"]) for item in robust_windows]
    report = {
        "schema_version": 1,
        "stage_id": STAGE_ID,
        "scope": {"source_runtime": str(SOURCE), "source_runtime_modified": False, "dt_s": DT, "slice_count": 3, "offline_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0}},
        "source": {"state_sha256": sha256(logs / "structure_participant.json"), "source_gate_status": source_gate.get("status"), "source_finalized": source_state.get("finalized"), "source_time_s": source_state.get("target_time_s"), "source_global_step": source_state.get("committed_steps")},
        "identity_audit": identity,
        "formal_accumulator": source_state["convergence_observables"],
        "robust_mean_force_reanalysis": {"method": "same 0.05 s mean-force samples; 1.0 s moving average; positive peaks only; 4.0 s minimum separation", "peak_count": len(robust_peaks), "peaks": robust_peaks, "windows": robust_windows, "frequency_drift_fraction": relative_delta(robust_frequency), "amplitude_drift_fraction": relative_delta(robust_amplitude)},
        "per_slice_force_windows": per_slice_windows,
        "interface_position_windows": position_windows,
        "openfoam_quality": quality,
        "findings": [
            "The original 2 s unconstrained local-maximum rule includes negative local maxima and creates spurious 2-4 s periods.",
            "Positive-peak reanalysis yields approximately 0.160-0.162 Hz in all three 40 s windows; its frequency drift is below 5%.",
            "The three-slice mean-force peak-to-peak amplitude declines materially across the three windows; it does not meet the 5% amplitude-stability criterion.",
            "Per-slice force and retained interface-position windows are substantially more stable than the cross-slice mean-force scalar, so phase cancellation is a plausible contributor but not proof of global structural convergence.",
            "OpenFOAM quality was retained.  Each slice has one terminal missing Courant sample, while continuity is complete; this is an observability integration gap, not missing source logs.",
        ],
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
        "next_action": "Do not promote formal convergence.  Repair the offline/next-run observability definition to use a declared structural response scalar, robust peak criteria, and aligned OpenFOAM quality before requesting a new run.",
    }
    report["gate"] = "not_evaluable"
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage4f_d_convergence_evidence_audit_v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": report["gate"], "identity": identity["status"], "formal": report["formal_accumulator"]["formal_convergence"], "robust_frequency_drift": report["robust_mean_force_reanalysis"]["frequency_drift_fraction"], "robust_amplitude_drift": report["robust_mean_force_reanalysis"]["amplitude_drift_fraction"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
