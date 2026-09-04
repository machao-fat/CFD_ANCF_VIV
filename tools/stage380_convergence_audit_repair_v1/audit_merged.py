"""Read-only merged convergence audit for the 80.2--220 s evidence chain.

The source runtimes are never modified.  This audit uses the declared robust
observable (three-slice mean lateral force), a one-second moving average and
positive peaks separated by at least four seconds.  Missing OpenFOAM quality
fields are reported as an evidence gap; values are never interpolated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from pathlib import Path


SLICE_IDS = tuple(f"slice_{i:04d}" for i in range(3))
DT = 0.005
SAMPLE_EVERY_STEPS = 10
QUALITY_FIELDS = ("time_s", "courant_max", "residual_max", "continuity_global", "iterations_max")
FORCE_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)\s+\(\(([^)]*)\)\s+\(([^)]*)\)\)")


class AuditError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_forces(path: Path) -> tuple[list[float], list[float]]:
    times: list[float] = []
    values: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = FORCE_RE.match(line)
        if not match:
            continue
        pressure = [float(value) for value in match.group(2).split()]
        viscous = [float(value) for value in match.group(3).split()]
        if len(pressure) < 2 or len(viscous) < 2:
            raise AuditError(f"force vector is incomplete: {path}")
        times.append(float(match.group(1)))
        values.append(pressure[1] + viscous[1])
    if len(times) < 3 or any(not math.isfinite(value) for value in times + values):
        raise AuditError(f"force evidence is empty or non-finite: {path}")
    if any(right <= left for left, right in zip(times, times[1:])):
        raise AuditError(f"force timestamps are not increasing: {path}")
    return times, values


def merge_force_streams(runtimes: tuple[Path, Path]) -> tuple[list[float], list[list[float]]]:
    streams: list[tuple[list[float], list[float]]] = []
    for index in range(3):
        chunks = []
        for runtime in runtimes:
            candidates = list((runtime / SLICE_IDS[index] / "postProcessing" / "forces1").glob("*/forces.dat"))
            if not candidates:
                raise AuditError(f"missing force evidence for {SLICE_IDS[index]} in {runtime}")
            chunks.append(parse_forces(sorted(candidates, key=lambda p: float(p.parent.name))[0]))
        if abs(chunks[0][0][-1] - chunks[1][0][0]) > 1.0e-9:
            raise AuditError(f"runtime boundary is not aligned for {SLICE_IDS[index]}")
        streams.append((chunks[0][0] + chunks[1][0][1:], chunks[0][1] + chunks[1][1][1:]))
    reference = streams[0][0]
    if any(times != reference for times, _ in streams[1:]):
        raise AuditError("slice force timestamps are not aligned")
    return reference, [values for _, values in streams]


def sample_mean_force(times: list[float], values: list[list[float]]) -> tuple[list[float], list[float]]:
    sampled_times: list[float] = []
    sampled_values: list[float] = []
    for index, time_s in enumerate(times):
        local = round((time_s - times[0]) / DT)
        if local >= 0 and local % SAMPLE_EVERY_STEPS == 0:
            sampled_times.append(time_s)
            sampled_values.append(statistics.fmean(stream[index] for stream in values))
    if len(sampled_times) < 3:
        raise AuditError("fewer than three scalar samples")
    return sampled_times, sampled_values


def positive_peaks(times: list[float], values: list[float], smoothing_s: float = 1.0, minimum_separation_s: float = 4.0) -> list[tuple[float, float]]:
    if len(times) != len(values) or len(times) < 3:
        raise AuditError("mismatched scalar stream")
    dt = statistics.median(right - left for left, right in zip(times, times[1:]))
    span = max(1, int(round(smoothing_s / dt)))
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    smooth = list(values)
    half = span // 2
    for index in range(half, len(values) - (span - half - 1)):
        smooth[index] = (prefix[index + span - half] - prefix[index - half]) / span
    peaks: list[tuple[float, float]] = []
    for index in range(span, len(smooth) - span):
        if smooth[index] <= 0.0 or smooth[index] < smooth[index - 1] or smooth[index] <= smooth[index + 1]:
            continue
        candidate = (times[index], smooth[index])
        if peaks and candidate[0] - peaks[-1][0] < minimum_separation_s:
            if candidate[1] > peaks[-1][1]:
                peaks[-1] = candidate
        else:
            peaks.append(candidate)
    return peaks


def relative_drift(values: list[float]) -> float | None:
    if not values:
        return None
    return (max(values) - min(values)) / max(abs(statistics.median(values)), 1.0e-30)


def window_summary(times: list[float], values: list[float], peaks: list[tuple[float, float]], windows: list[tuple[float, float]]) -> list[dict[str, object]]:
    output = []
    for start, stop in windows:
        selected = [value for time_s, value in zip(times, values) if start <= time_s < stop]
        selected_peaks = [peak for peak in peaks if start <= peak[0] < stop]
        periods = [right[0] - left[0] for left, right in zip(selected_peaks, selected_peaks[1:])]
        if not selected:
            raise AuditError(f"empty window: {start}:{stop}")
        output.append({
            "start_time_s": start,
            "end_time_s": min(stop, max(times)),
            "sample_count": len(selected),
            "peak_count": len(selected_peaks),
            "frequency_hz": 1.0 / statistics.fmean(periods) if periods else None,
            "mean_force_y": statistics.fmean(selected),
            "rms_force_y": math.sqrt(statistics.fmean(value * value for value in selected)),
            "peak_to_peak_force_y": max(selected) - min(selected),
            "periods_s": periods,
        })
    return output


def audit_quality(runtime: Path, expected_start: float, expected_end: float) -> dict[str, object]:
    result: dict[str, object] = {}
    expected_count = round((expected_end - expected_start) / DT)
    for index, sid in enumerate(SLICE_IDS):
        records: list[dict[str, object]] = []
        path = runtime / "logs" / f"openfoam_{index:04d}_quality.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = list(payload.get("records", []))
        counts = {field: sum(field in record and isinstance(record[field], (int, float)) and math.isfinite(float(record[field])) for record in records) for field in QUALITY_FIELDS}
        result[sid] = {
            "record_count": len(records),
            "expected_count": expected_count,
            "field_counts": counts,
            "complete": len(records) == expected_count and all(counts[field] == expected_count for field in QUALITY_FIELDS),
            "missing_fields": {field: expected_count - counts[field] for field in QUALITY_FIELDS},
        }
    return result


def audit(runtimes: tuple[Path, Path]) -> dict[str, object]:
    times, streams = merge_force_streams(runtimes)
    sampled_times, mean_force = sample_mean_force(times, streams)
    peaks = positive_peaks(sampled_times, mean_force)
    windows = window_summary(sampled_times, mean_force, peaks, [(80.2, 120.2), (120.2, 160.2), (160.2, 200.2), (200.2, 220.001)])
    frequencies = [float(item["frequency_hz"]) for item in windows if item["frequency_hz"] is not None]
    amplitudes = [float(item["peak_to_peak_force_y"]) for item in windows]
    quality = {str(runtime): audit_quality(runtime, 80.2 if index == 0 else 200.0, 200.0 if index == 0 else 220.0) for index, runtime in enumerate(runtimes)}
    quality_complete = all(item["complete"] for runtime in quality.values() for item in runtime.values())
    return {
        "schema_version": 1,
        "stage_id": "stage4f_d_convergence_audit_repair_v1",
        "scope": {"start_time_s": 80.2, "end_time_s": 220.0, "dt_s": DT, "slice_count": 3, "offline_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0}},
        "identity": {"force_samples": len(times), "sampled_scalar_count": len(sampled_times), "slice_timestamps_aligned": True, "boundary_duplicate_removed": True},
        "method": {"response_scalar": "three_slice_mean_force_y", "sample_interval_s": 0.05, "smoothing_s": 1.0, "positive_peaks_only": True, "minimum_peak_separation_s": 4.0, "missing_value_policy": "fail_closed_no_interpolation"},
        "peaks": [{"time_s": time_s, "value": value} for time_s, value in peaks],
        "windows": windows,
        "frequency_drift_fraction": relative_drift(frequencies),
        "amplitude_drift_fraction": relative_drift(amplitudes),
        "quality": quality,
        "quality_complete": quality_complete,
        "formal_convergence": "pass" if len(peaks) - 1 >= 15 and (relative_drift(frequencies) or 1.0) <= 0.05 and (relative_drift(amplitudes) or 1.0) <= 0.05 and quality_complete else "not_completed",
        "reasons": (["fewer than 15 valid cycles"] if len(peaks) - 1 < 15 else []) + (["window frequency drift exceeds 5% or is unavailable"] if relative_drift(frequencies) is None or relative_drift(frequencies) > 0.05 else []) + (["window amplitude drift exceeds 5% or is unavailable"] if relative_drift(amplitudes) is None or relative_drift(amplitudes) > 0.05 else []) + ([] if quality_complete else ["OpenFOAM quality coverage is incomplete; no interpolation performed"]),
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    runtimes = (args.root / "runtime/stage372_cpp_worker_precice_three_slice_80p2_to200_v1_retry3", args.root / "runtime/stage379_cpp_worker_precice_three_slice_continue200_to220_v1")
    report = audit(runtimes)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": "pass" if report["formal_convergence"] == "pass" else "not_evaluable", "formal_convergence": report["formal_convergence"], "frequency_drift_fraction": report["frequency_drift_fraction"], "amplitude_drift_fraction": report["amplitude_drift_fraction"], "quality_complete": report["quality_complete"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
