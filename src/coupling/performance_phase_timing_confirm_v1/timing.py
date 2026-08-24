from __future__ import annotations

import math
import statistics
import threading
import time
from typing import Any, Mapping, Sequence


class PhaseTimingError(ValueError):
    """A phase trace is incomplete, non-monotonic, or inconsistent."""


_PHASES = ("ancf", "openfoam", "exchange", "sync_and_audit", "step")


def _stats(values: Sequence[float], step_mean: float | None = None) -> dict[str, float]:
    if not values:
        raise PhaseTimingError("empty timing sample")
    ordered = sorted(float(item) for item in values)
    n = len(ordered)
    mean = statistics.fmean(ordered)
    p50 = ordered[max(0, int(math.ceil(0.50 * n)) - 1)]
    p95 = ordered[max(0, int(math.ceil(0.95 * n)) - 1)]
    result = {
        "mean_s": mean,
        "p50_s": p50,
        "p95_s": p95,
        "max_s": max(ordered),
        "min_s": min(ordered),
        "stddev_s": statistics.pstdev(ordered) if len(ordered) > 1 else 0.0,
    }
    if step_mean is not None and step_mean > 0.0:
        result["mean_percent_of_step"] = 100.0 * mean / step_mean
    else:
        result["mean_percent_of_step"] = 0.0
    return result


class PhaseTimingRecorder:
    """Thread-safe monotonic timestamp recorder for one bounded segment.

    Exchange is an envelope around the two file-bridge exchange portions.  It
    is intentionally kept as an interval because it may overlap OpenFOAM and
    ANCF work; the overlap is reported rather than silently allocated away.
    """

    def __init__(self, *, run_id: str, case_id: str, source_global_step: int,
                 source_time_s: float, source_tick: int, dt_s: float,
                 slice_ids: Sequence[int] = (0, 1, 2)) -> None:
        self.run_id = str(run_id)
        self.case_id = str(case_id)
        self.source_global_step = int(source_global_step)
        self.source_time_s = float(source_time_s)
        self.source_tick = int(source_tick)
        self.dt_s = float(dt_s)
        self.slice_ids = tuple(int(item) for item in slice_ids)
        if len(set(self.slice_ids)) != len(self.slice_ids) or not self.slice_ids:
            raise PhaseTimingError("slice identity is invalid")
        self._rows: dict[int, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def _row(self, step: int) -> dict[str, Any]:
        return self._rows.setdefault(int(step), {"openfoam": {}})

    def begin_step(self, step: int, time_s: float) -> None:
        now = time.perf_counter_ns()
        step = int(step)
        expected = self.source_time_s + (step - self.source_global_step) * self.dt_s
        if not math.isclose(float(time_s), expected, rel_tol=0.0, abs_tol=1e-12):
            raise PhaseTimingError("step time does not match source mapping")
        with self._lock:
            row = self._row(step)
            if "step_start_ns" in row:
                raise PhaseTimingError("duplicate step start")
            row.update({"step_start_ns": now, "time_s": float(time_s),
                        "global_step": step,
                        "case_local_bridge_step": step - self.source_global_step,
                        "integer_tick": int(round(float(time_s) * 1.0e9))})

    def end_step(self, step: int) -> None:
        with self._lock:
            row = self._row(step)
            row["step_end_ns"] = time.perf_counter_ns()

    def ancf_start(self, step: int) -> None:
        with self._lock:
            row = self._row(step)
            row.setdefault("ancf_start_ns", time.perf_counter_ns())

    def ancf_end(self, step: int) -> None:
        with self._lock:
            self._row(step)["ancf_end_ns"] = time.perf_counter_ns()
            self.sync_audit_start(step)

    def exchange_start(self, step: int) -> None:
        with self._lock:
            row = self._row(step)
            stamp = time.perf_counter_ns()
            previous = row.get("exchange_start_ns")
            row["exchange_start_ns"] = stamp if previous is None else min(int(previous), stamp)

    def exchange_end(self, step: int) -> None:
        with self._lock:
            row = self._row(step)
            stamp = time.perf_counter_ns()
            previous = row.get("exchange_end_ns")
            row["exchange_end_ns"] = stamp if previous is None else max(int(previous), stamp)

    def openfoam_start(self, step: int, slice_id: int) -> None:
        with self._lock:
            row = self._row(step)
            slot = row["openfoam"].setdefault(str(int(slice_id)), {})
            if "start_ns" in slot:
                raise PhaseTimingError("duplicate OpenFOAM slice start")
            slot["start_ns"] = time.perf_counter_ns()

    def openfoam_end(self, step: int, slice_id: int) -> None:
        with self._lock:
            slot = self._row(step)["openfoam"].setdefault(str(int(slice_id)), {})
            slot["end_ns"] = time.perf_counter_ns()

    def sync_audit_start(self, step: int) -> None:
        with self._lock:
            row = self._row(step)
            row.setdefault("sync_audit_start_ns", time.perf_counter_ns())

    def sync_audit_end(self, step: int) -> None:
        with self._lock:
            self._row(step)["sync_audit_end_ns"] = time.perf_counter_ns()

    def finalize(self, *, step: int, expected_time_s: float, slice_ids: Sequence[int] | None = None) -> dict[str, Any]:
        with self._lock:
            row = dict(self._row(int(step)))
            row["openfoam"] = {key: dict(value) for key, value in row.get("openfoam", {}).items()}
        required = ("step_start_ns", "step_end_ns", "ancf_start_ns", "ancf_end_ns",
                    "exchange_start_ns", "exchange_end_ns", "sync_audit_start_ns", "sync_audit_end_ns")
        if any(key not in row for key in required):
            raise PhaseTimingError("missing phase timestamp")
        ids = tuple(int(item) for item in (slice_ids or self.slice_ids))
        if set(row["openfoam"]) != {str(item) for item in ids}:
            raise PhaseTimingError("missing or unexpected OpenFOAM slice timestamp")
        stamps = [int(row[key]) for key in required]
        if any(item < 0 for item in stamps):
            raise PhaseTimingError("negative monotonic timestamp")
        if row["step_end_ns"] <= row["step_start_ns"]:
            raise PhaseTimingError("step timestamp is not increasing")
        for key in ("ancf", "exchange", "sync_audit"):
            if row[f"{key}_end_ns"] <= row[f"{key}_start_ns"]:
                raise PhaseTimingError(f"{key} timestamp is not increasing")
        slice_durations: dict[str, float] = {}
        slice_stamps: dict[str, dict[str, int]] = {}
        for sid in ids:
            slot = row["openfoam"][str(sid)]
            if "start_ns" not in slot or "end_ns" not in slot or int(slot["end_ns"]) <= int(slot["start_ns"]):
                raise PhaseTimingError(f"slice {sid} timestamp is invalid")
            slice_stamps[str(sid)] = {"start_ns": int(slot["start_ns"]), "end_ns": int(slot["end_ns"])}
            slice_durations[str(sid)] = (slot["end_ns"] - slot["start_ns"]) / 1.0e9
        if "time_s" not in row or not math.isclose(float(row["time_s"]), float(expected_time_s), rel_tol=0.0, abs_tol=1e-12):
            raise PhaseTimingError("timing row time mismatch")
        bridge_step = int(row["case_local_bridge_step"])
        expected_tick = self.source_tick + int(round(bridge_step * self.dt_s * 1.0e9))
        if bridge_step <= 0 or int(row["integer_tick"]) != expected_tick:
            raise PhaseTimingError("timing row tick/bridge identity mismatch")
        ancf = (row["ancf_end_ns"] - row["ancf_start_ns"]) / 1.0e9
        exchange = (row["exchange_end_ns"] - row["exchange_start_ns"]) / 1.0e9
        sync = (row["sync_audit_end_ns"] - row["sync_audit_start_ns"]) / 1.0e9
        step_total = (row["step_end_ns"] - row["step_start_ns"]) / 1.0e9
        openfoam = max(slice_durations.values())
        openfoam_sum = sum(slice_durations.values())
        values = {"T_ancf": ancf, "T_openfoam": openfoam, "T_openfoam_slice_sum": openfoam_sum,
                  "T_exchange": exchange, "T_sync_and_audit": sync, "T_step": step_total,
                  "overlap_gap": ancf + openfoam + exchange + sync - step_total}
        return {
            "run_id": self.run_id, "case_id": self.case_id, "global_step": int(row["global_step"]),
            "case_local_bridge_step": int(row["case_local_bridge_step"]), "time_s": float(row["time_s"]),
            "integer_tick": int(row["integer_tick"]),
            "request_id": f"performance_phase_timing_motion_{int(row['global_step']):08d}",
            "transaction_id": f"performance_phase_timing_tx_{int(row['global_step']):08d}",
            "timestamps_ns": {
                "step_start": int(row["step_start_ns"]), "step_end": int(row["step_end_ns"]),
                "ancf_start": int(row["ancf_start_ns"]), "ancf_end": int(row["ancf_end_ns"]),
                "exchange_start": int(row["exchange_start_ns"]), "exchange_end": int(row["exchange_end_ns"]),
                "sync_audit_start": int(row["sync_audit_start_ns"]), "sync_audit_end": int(row["sync_audit_end_ns"])},
            "openfoam_timestamps_ns": slice_stamps, "durations_s": values,
            "slice_durations_s": slice_durations,
            "barrier_wait_s": max(slice_stamps[str(sid)]["end_ns"] for sid in ids) / 1.0e9 - min(slice_stamps[str(sid)]["end_ns"] for sid in ids) / 1.0e9,
        }

    def raw_rows(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{key: value for key, value in row.items()} for _, row in sorted(self._rows.items())]


def summarize_phase_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise PhaseTimingError("empty phase records")
    ordered = sorted((dict(item) for item in records), key=lambda item: int(item["global_step"]))
    run_id, case_id = str(ordered[0]["run_id"]), str(ordered[0]["case_id"])
    if any((str(item["run_id"]), str(item["case_id"])) != (run_id, case_id) for item in ordered):
        raise PhaseTimingError("phase record identity mismatch")
    for index, item in enumerate(ordered):
        if int(item["global_step"]) != int(ordered[0]["global_step"]) + index:
            raise PhaseTimingError("phase steps are not contiguous")
        if int(item.get("case_local_bridge_step", 0)) != index + int(ordered[0].get("case_local_bridge_step", 1)):
            raise PhaseTimingError("phase bridge steps are not contiguous")
        if index and int(item.get("integer_tick", 0)) - int(ordered[index - 1].get("integer_tick", 0)) != 1250000:
            raise PhaseTimingError("phase ticks are not contiguous")
    durations = [item["durations_s"] for item in ordered]
    step_mean = statistics.fmean(float(item["T_step"]) for item in durations)
    phase_names = ("T_ancf", "T_openfoam", "T_exchange", "T_sync_and_audit", "T_step", "overlap_gap")
    phase_summary = {name: _stats([float(item[name]) for item in durations], step_mean if name != "overlap_gap" else None) for name in phase_names}
    interval_names = ("T_ancf", "T_openfoam", "T_exchange", "T_sync_and_audit")
    interval_total = sum(sum(float(item[name]) for item in durations) for name in interval_names)
    for name in interval_names:
        phase_summary[name]["interval_weight_percent"] = (
            100.0 * sum(float(item[name]) for item in durations) / interval_total if interval_total > 0.0 else 0.0
        )
    slice_ids = sorted({sid for item in ordered for sid in item.get("slice_durations_s", {})})
    slice_summary = {str(sid): _stats([float(item["slice_durations_s"][str(sid)]) for item in ordered], step_mean) for sid in slice_ids}
    return {"run_id": run_id, "case_id": case_id, "steps": len(ordered), "phase_s": phase_summary,
            "slice_s": slice_summary, "barrier_wait_s": _stats([float(item["barrier_wait_s"]) for item in ordered], step_mean),
            "total_phase_s": {name: sum(float(item[name]) for item in durations) for name in phase_names},
            "overlap_gap_total_s": sum(float(item["overlap_gap"]) for item in durations),
            "segment_step_wall_clock_s": sum(float(item["T_step"]) for item in durations)}
