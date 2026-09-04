from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from pathlib import Path
from typing import Iterable, Mapping, Sequence


class AuditError(ValueError):
    """Raised when immutable evidence violates the offline audit contract."""


_NUMBER = r"([^,\s]+)"
_COURANT = re.compile(rf"Courant Number mean:\s*{_NUMBER}\s+max:\s*{_NUMBER}")
_CONTINUITY = re.compile(
    rf"time step continuity errors\s*:\s*sum local\s*=\s*{_NUMBER},\s*global\s*=\s*{_NUMBER},\s*cumulative\s*=\s*{_NUMBER}"
)
_TIME = re.compile(r"^Time\s*=\s*([^\s]+)")


def finite(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditError(f"{name} is not numeric") from exc
    if not math.isfinite(result):
        raise AuditError(f"{name} is NaN/Inf")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError(f"invalid JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"JSON evidence is not an object: {path}")
    return value


def parse_openfoam_log(path: Path) -> dict[str, object]:
    courant_count = 0
    continuity_count = 0
    courant_max = -math.inf
    continuity_global_abs_max = -math.inf
    last_time_s: float | None = None
    end_marker = False
    with path.open("r", encoding="utf-8", errors="strict") as stream:
        for line_number, line in enumerate(stream, 1):
            if "Courant Number" in line:
                match = _COURANT.search(line)
                if match is None:
                    raise AuditError(f"malformed Courant record at {path}:{line_number}")
                mean_value = finite(match.group(1), "courant_mean")
                max_value = finite(match.group(2), "courant_max")
                if mean_value < 0.0 or max_value < 0.0:
                    raise AuditError(f"negative Courant record at {path}:{line_number}")
                courant_count += 1
                courant_max = max(courant_max, max_value)
            if "time step continuity errors" in line:
                match = _CONTINUITY.search(line)
                if match is None:
                    raise AuditError(f"malformed continuity record at {path}:{line_number}")
                finite(match.group(1), "continuity_local")
                global_value = finite(match.group(2), "continuity_global")
                finite(match.group(3), "continuity_cumulative")
                continuity_count += 1
                continuity_global_abs_max = max(continuity_global_abs_max, abs(global_value))
            time_match = _TIME.match(line.strip())
            if time_match is not None:
                raw_time = time_match.group(1).rstrip("s")
                last_time_s = finite(raw_time, "OpenFOAM time")
            if line.strip() == "End":
                end_marker = True
    if courant_count == 0:
        raise AuditError(f"Courant evidence is missing: {path}")
    if continuity_count == 0:
        raise AuditError(f"continuity evidence is missing: {path}")
    if not end_marker:
        raise AuditError(f"OpenFOAM End marker is missing: {path}")
    return {
        "path": str(path),
        "courant_count": courant_count,
        "courant_max": courant_max,
        "continuity_global_count": continuity_count,
        "continuity_global_abs_max": continuity_global_abs_max,
        "last_time_s": last_time_s,
        "end_marker": end_marker,
        "finite": True,
    }


def _read_json_lines(path: Path) -> Iterable[tuple[int, dict[str, object]]]:
    with path.open("r", encoding="utf-8", errors="strict") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AuditError(f"invalid JSONL at {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise AuditError(f"JSONL record is not an object at {path}:{line_number}")
            yield line_number, value


def parse_mapping_diagnostics(
    path: Path,
    *,
    source_step: int,
    source_time_s: float,
    dt_s: float,
    expected_count: int,
    slice_count: int,
    sample_every_steps: int = 10,
) -> dict[str, object]:
    if expected_count < 1 or slice_count < 1 or sample_every_steps < 1:
        raise AuditError("invalid mapping audit contract")
    samples: list[dict[str, float | int]] = []
    maxima = {
        "virtual_work_error": 0.0,
        "force_balance_error": 0.0,
        "moment_balance_error": 0.0,
    }
    record_count = 0
    equal_force_hash_count = 0
    for line_number, row in _read_json_lines(path):
        record_count += 1
        expected_local = record_count
        expected_global = source_step + expected_local
        expected_time = source_time_s + expected_local * dt_s
        expected_tick = int(round(expected_time * 1.0e9))
        if row.get("global_step") != expected_global:
            raise AuditError(f"global_step discontinuity at {path}:{line_number}")
        if row.get("case_local_bridge_step") != expected_local:
            raise AuditError(f"bridge_step discontinuity at {path}:{line_number}")
        actual_time = finite(row.get("time_s"), "mapping time_s")
        if not math.isclose(actual_time, expected_time, rel_tol=0.0, abs_tol=5.0e-12):
            raise AuditError(f"mapping time mismatch at {path}:{line_number}")
        if row.get("integer_tick") != expected_tick:
            raise AuditError(f"mapping tick mismatch at {path}:{line_number}")
        for vector_name in ("fluid_resultant", "mapped_resultant"):
            vector = row.get(vector_name)
            if not isinstance(vector, list) or len(vector) != 3:
                raise AuditError(f"{vector_name} shape mismatch at {path}:{line_number}")
            for index, value in enumerate(vector):
                finite(value, f"{vector_name}[{index}]")
        for name in maxima:
            value = abs(finite(row.get(name), name))
            maxima[name] = max(maxima[name], value)
        hashes = row.get("force_hashes")
        if not isinstance(hashes, list) or len(hashes) != slice_count or not all(isinstance(value, str) and len(value) == 64 for value in hashes):
            raise AuditError(f"force hash identity mismatch at {path}:{line_number}")
        if len(set(hashes)) == 1:
            equal_force_hash_count += 1
        if expected_global % sample_every_steps == 0:
            fluid_resultant = row["fluid_resultant"]
            assert isinstance(fluid_resultant, list)
            samples.append({
                "global_step": expected_global,
                "time_s": actual_time,
                "force_y": finite(fluid_resultant[1], "fluid_resultant_y") / slice_count,
            })
    if record_count != expected_count:
        raise AuditError(f"mapping record count {record_count} != {expected_count}")
    return {
        "record_count": record_count,
        "sample_count": len(samples),
        "samples": samples,
        "max_errors": maxima,
        "all_values_finite": True,
        "equal_force_hash_count": equal_force_hash_count,
        "all_slice_force_hashes_equal": equal_force_hash_count == record_count,
    }


def validate_checkpoints(
    path: Path,
    *,
    source_step: int,
    source_time_s: float,
    target_step: int,
    dt_s: float,
    interval: int = 100,
) -> dict[str, object]:
    expected_count = (target_step - source_step) // interval
    records = list(_read_json_lines(path))
    if len(records) != expected_count:
        raise AuditError(f"checkpoint count {len(records)} != {expected_count}")
    for index, (line_number, row) in enumerate(records, 1):
        bridge_step = index * interval
        global_step = source_step + bridge_step
        time_s = source_time_s + bridge_step * dt_s
        if row.get("global_step") != global_step or row.get("case_local_bridge_step") != bridge_step:
            raise AuditError(f"checkpoint step identity mismatch at {path}:{line_number}")
        if not math.isclose(finite(row.get("time_s"), "checkpoint time_s"), time_s, rel_tol=0.0, abs_tol=5.0e-12):
            raise AuditError(f"checkpoint time mismatch at {path}:{line_number}")
        if row.get("integer_tick") != int(round(time_s * 1.0e9)):
            raise AuditError(f"checkpoint tick mismatch at {path}:{line_number}")
        for name in ("worker_payload_sha256", "q_sha256"):
            value = row.get(name)
            if not isinstance(value, str) or len(value) != 64:
                raise AuditError(f"checkpoint {name} mismatch at {path}:{line_number}")
    return {"count": len(records), "interval_steps": interval, "first_global_step": source_step + interval, "last_global_step": target_step, "identity_continuous": True}


def _peaks(samples: Sequence[Mapping[str, float | int]], minimum_separation_s: float = 2.0) -> list[dict[str, float]]:
    peaks: list[dict[str, float]] = []
    for index in range(1, len(samples) - 1):
        left = finite(samples[index - 1]["force_y"], "force_y")
        current = finite(samples[index]["force_y"], "force_y")
        right = finite(samples[index + 1]["force_y"], "force_y")
        time_s = finite(samples[index]["time_s"], "time_s")
        if current >= left and current > right:
            if peaks and time_s - peaks[-1]["time_s"] < minimum_separation_s:
                if current > peaks[-1]["value"]:
                    peaks[-1] = {"time_s": time_s, "value": current}
            else:
                peaks.append({"time_s": time_s, "value": current})
    return peaks


def _fft_frequency(samples: Sequence[Mapping[str, float | int]]) -> float:
    try:
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise AuditError("NumPy is required for the formal FFT audit") from exc
    values = np.asarray([finite(row["force_y"], "force_y") for row in samples], dtype=float)
    times = np.asarray([finite(row["time_s"], "time_s") for row in samples], dtype=float)
    if len(values) < 4:
        raise AuditError("insufficient samples for FFT")
    sample_dt = float(np.median(np.diff(times)))
    if not math.isfinite(sample_dt) or sample_dt <= 0.0:
        raise AuditError("invalid FFT sample interval")
    indices = np.arange(len(values), dtype=float)
    values = values - np.polyval(np.polyfit(indices, values, 1), indices)
    spectrum = np.abs(np.fft.rfft(values))
    if len(spectrum) < 2 or not np.isfinite(spectrum).all():
        raise AuditError("invalid FFT spectrum")
    peak_index = int(np.argmax(spectrum[1:]) + 1)
    return float(np.fft.rfftfreq(len(values), d=sample_dt)[peak_index])


def _relative_span(values: Sequence[float]) -> float:
    if not values:
        raise AuditError("relative span has no values")
    return (max(values) - min(values)) / max(abs(statistics.median(values)), 1.0e-30)


def statistics_from_samples(
    samples: Sequence[Mapping[str, float | int]],
    *,
    required_cycles: int = 15,
    fft_frequency_override: float | None = None,
) -> dict[str, object]:
    peaks = _peaks(samples)
    if len(peaks) - 1 < required_cycles:
        return {
            "sample_count": len(samples),
            "peak_count": len(peaks),
            "cycle_count": max(0, len(peaks) - 1),
            "late_window_available": False,
            "windows": [],
        }
    boundary_peaks = peaks[-(required_cycles + 1):]
    cycles_per_window = required_cycles // 3
    if cycles_per_window * 3 != required_cycles:
        raise AuditError("required_cycles must divide into three adjacent windows")
    windows: list[dict[str, object]] = []
    for index in range(3):
        peak_group = boundary_peaks[index * cycles_per_window:index * cycles_per_window + cycles_per_window + 1]
        start_time = peak_group[0]["time_s"]
        end_time = peak_group[-1]["time_s"]
        part = [row for row in samples if start_time <= finite(row["time_s"], "time_s") <= end_time]
        values = [finite(row["force_y"], "force_y") for row in part]
        periods = [peak_group[i + 1]["time_s"] - peak_group[i]["time_s"] for i in range(cycles_per_window)]
        mean_value = statistics.fmean(values)
        windows.append({
            "start_time_s": start_time,
            "end_time_s": end_time,
            "sample_count": len(part),
            "cycle_count": cycles_per_window,
            "mean_force_y": mean_value,
            "rms_force_y": math.sqrt(statistics.fmean(value * value for value in values)),
            "peak_to_peak_force_y": max(values) - min(values),
            "mean_period_s": statistics.fmean(periods),
            "frequency_hz": 1.0 / statistics.fmean(periods),
        })
    late_samples = [row for row in samples if boundary_peaks[0]["time_s"] <= finite(row["time_s"], "time_s") <= boundary_peaks[-1]["time_s"]]
    peak_frequency = required_cycles / (boundary_peaks[-1]["time_s"] - boundary_peaks[0]["time_s"])
    fft_frequency = finite(fft_frequency_override, "FFT frequency") if fft_frequency_override is not None else _fft_frequency(late_samples)
    frequencies = [finite(row["frequency_hz"], "frequency_hz") for row in windows]
    rms_values = [finite(row["rms_force_y"], "rms_force_y") for row in windows]
    amplitudes = [finite(row["peak_to_peak_force_y"], "peak_to_peak_force_y") for row in windows]
    means = [finite(row["mean_force_y"], "mean_force_y") for row in windows]
    average_rms = statistics.fmean(rms_values)
    return {
        "sample_count": len(samples),
        "peak_count": len(peaks),
        "cycle_count": len(peaks) - 1,
        "late_window_available": True,
        "late_cycle_count": required_cycles,
        "late_start_time_s": boundary_peaks[0]["time_s"],
        "late_end_time_s": boundary_peaks[-1]["time_s"],
        "late_peak_frequency_hz": peak_frequency,
        "late_fft_frequency_hz": fft_frequency,
        "fft_peak_relative_difference": abs(fft_frequency - peak_frequency) / max(abs(fft_frequency), abs(peak_frequency), 1.0e-30),
        "frequency_drift_fraction": _relative_span(frequencies),
        "rms_drift_fraction": _relative_span(rms_values),
        "peak_to_peak_drift_fraction": _relative_span(amplitudes),
        "mean_span_over_average_rms": (max(means) - min(means)) / max(abs(average_rms), 1.0e-30),
        "windows": windows,
    }


def evaluate_formal_checks(
    statistics_summary: Mapping[str, object],
    fluid_quality: Sequence[Mapping[str, object]],
    *,
    drift_tolerance: float = 0.05,
    cfl_limit: float = 0.8,
) -> dict[str, bool]:
    late_available = statistics_summary.get("late_window_available") is True
    late_cycles = int(statistics_summary.get("late_cycle_count", 0))
    quality_present = len(fluid_quality) == 3 and all(int(row.get("courant_count", 0)) > 0 and int(row.get("continuity_global_count", 0)) > 0 for row in fluid_quality)
    quality_finite = quality_present and all(row.get("finite") is True and math.isfinite(finite(row.get("courant_max"), "courant_max")) and math.isfinite(finite(row.get("continuity_global_abs_max"), "continuity_global_abs_max")) for row in fluid_quality)
    cfl_below_limit = quality_finite and max(finite(row["courant_max"], "courant_max") for row in fluid_quality) < cfl_limit
    return {
        "at_least_15_late_cycles": late_available and late_cycles >= 15,
        "three_adjacent_five_cycle_windows": late_available and len(statistics_summary.get("windows", [])) == 3,
        "frequency_drift_le_5pct": late_available and finite(statistics_summary.get("frequency_drift_fraction"), "frequency drift") <= drift_tolerance,
        "rms_drift_le_5pct": late_available and finite(statistics_summary.get("rms_drift_fraction"), "RMS drift") <= drift_tolerance,
        "peak_to_peak_drift_le_5pct": late_available and finite(statistics_summary.get("peak_to_peak_drift_fraction"), "peak-to-peak drift") <= drift_tolerance,
        "mean_span_over_rms_le_5pct": late_available and finite(statistics_summary.get("mean_span_over_average_rms"), "mean span") <= drift_tolerance,
        "fft_peak_difference_le_5pct": late_available and finite(statistics_summary.get("fft_peak_relative_difference"), "FFT/peak difference") <= drift_tolerance,
        "three_slice_quality_evidence_present": quality_present,
        "quality_values_finite": quality_finite,
        "courant_max_lt_0_8": cfl_below_limit,
        "continuity_global_present_and_finite": quality_finite,
    }
