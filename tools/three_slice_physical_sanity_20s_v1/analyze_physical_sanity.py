#!/usr/bin/env python3
"""Offline, exploratory-only local response and fluid-work analysis for 20 s."""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime" / "three_slice_physical_sanity_20s_v1_run_001"
RESULTS = ROOT / "results" / "three_slice_physical_sanity_20s_v1_run_001"
CONTRACT = Path(__file__).with_name("three_slice_physical_sanity_20s_v1_contract.json")


def mean(values: list[float]) -> float: return sum(values) / len(values)
def rms(values: list[float]) -> float: return math.sqrt(sum(value * value for value in values) / len(values))
def stats(values: list[float]) -> dict[str, float]: return {"mean": mean(values), "rms": rms(values), "peak_to_peak": max(values) - min(values), "max_abs": max(abs(value) for value in values)}
def window(rows: list[dict[str, object]], start: float, end: float) -> list[dict[str, object]]: return [row for row in rows if float(row["time_s"]) > start and float(row["time_s"]) <= end]


def crossing_frequency(values: list[float], dt: float) -> dict[str, object]:
    centered = [value - mean(values) for value in values]; crossings: list[float] = []
    for index in range(1, len(centered)):
        if centered[index - 1] <= 0.0 < centered[index]:
            denominator = centered[index] - centered[index - 1]
            crossings.append((index - 1 + (-centered[index - 1] / denominator)) * dt)
    cycles = max(0, len(crossings) - 1)
    return {"estimate_Hz": cycles / (crossings[-1] - crossings[0]) if cycles else None, "complete_cycles": cycles, "confidence": "low_confidence" if cycles < 3 else "exploratory"}


def projection_amplitude(values: list[float], dt: float, frequency_hz: float) -> float:
    n = len(values); centered = [value - mean(values) for value in values]
    cosine = sum(value * math.cos(2.0 * math.pi * frequency_hz * index * dt) for index, value in enumerate(centered))
    sine = sum(value * math.sin(2.0 * math.pi * frequency_hz * index * dt) for index, value in enumerate(centered))
    return 2.0 * math.hypot(cosine, sine) / n


def cross_correlation(a: list[float], b: list[float], dt: float) -> dict[str, float]:
    aa = [x - mean(a) for x in a]; bb = [x - mean(b) for x in b]
    normal = math.sqrt(sum(x*x for x in aa) * sum(x*x for x in bb))
    best = (0.0, 0)
    maximum = min(400, len(a) - 1)
    for lag in range(-maximum, maximum + 1):
        value = sum(aa[index] * bb[index + lag] for index in range(max(0, -lag), min(len(a), len(a) - lag))) / normal if normal else 0.0
        if abs(value) > abs(best[0]): best = (value, lag)
    return {"peak_correlation": best[0], "lag_s": best[1] * dt}


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8")); dt = float(contract["dt_s"])
    rows = [json.loads(line) for line in (RUNTIME / "records.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != int(contract["number_of_steps"]): raise RuntimeError("incomplete runtime cannot be physically analysed")
    windows = contract["physical_sanity_contract"]["windows_s"]
    result: dict[str, object] = {"schema_version": "three-slice-physical-sanity-analysis-v1", "run_id": contract["run_id"], "window_definition_s": windows, "fft_resolution_Hz": 1.0 / float(contract["duration_s"]), "MODAL_PROJECTION": "not_available", "structural_energy": "not_available_from_current_C++_wire", "slices": {}, "total": {}}
    total_power = [0.0] * len(rows)
    for sid in range(3):
        fy = [float(row["loads"][sid]["force_y_N"]) for row in rows]
        y = [float(row["motion"][sid]["uy_m"]) for row in rows]
        vy = [float(row["motion"][sid]["vy_mps"]) for row in rows]
        ay = [float(row["motion"][sid]["ay_mps2"]) for row in rows]
        power = [force * velocity for force, velocity in zip(fy, vy)]
        total_power = [old + value for old, value in zip(total_power, power)]
        cumulative = []; current = 0.0
        for value in power: current += value * dt; cumulative.append(current)
        by_window = {}
        for name, interval in windows.items():
            indexes = [index for index, row in enumerate(rows) if float(row["time_s"]) > float(interval[0]) and float(row["time_s"]) <= float(interval[1])]
            by_window[name] = {"Fy_N": stats([fy[index] for index in indexes]), "y_m": stats([y[index] for index in indexes]), "vy_mps": stats([vy[index] for index in indexes]), "mean_crossflow_power_W": mean([power[index] for index in indexes])}
        early, middle, late = (by_window[name]["y_m"]["rms"] for name in ("EARLY", "MID", "LATE"))
        classification = "GROWING" if late > 1.5 * max(middle, early, 1e-30) else "DECAYING" if late < .67 * max(middle, early, 1e-30) else "BOUNDED"
        y_at_mode = projection_amplitude(y, dt, .198761)
        scan = {f: projection_amplitude(y, dt, f) for f in [0.05 * index for index in range(1, 21)]}
        strongest = max(scan, key=scan.get)
        result["slices"][str(sid)] = {"full": {"Fy_N": stats(fy), "y_m": stats(y), "y_over_D": stats(y), "vy_mps": stats(vy), "ay_mps2": stats(ay)}, "windows": by_window, "power": {"mean_crossflow_W": mean(power), "positive_fraction": sum(value > 0 for value in power) / len(power), "negative_fraction": sum(value < 0 for value in power) / len(power), "cumulative_crossflow_work_J": cumulative[-1]}, "growth_classification": classification, "force_y_crossflow_y": cross_correlation(fy, y, dt), "force_y_crossflow_velocity": cross_correlation(fy, vy, dt), "frequency_exploratory": {"y_zero_crossing": crossing_frequency(y, dt), "Fy_zero_crossing": crossing_frequency(fy, dt), "mode_0p198761_projection_amplitude_m": y_at_mode, "strongest_0p05Hz_grid_Hz": strongest, "grid_peak_amplitude_m": scan[strongest], "status": "exploratory_short_window"}}
    total_work = sum(total_power) * dt
    result["total"] = {"mean_crossflow_power_W": mean(total_power), "cumulative_crossflow_work_J": total_work, "sign": "positive" if total_work > 0 else "negative" if total_work < 0 else "zero"}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "physical_sanity_analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(RESULTS / "physical_sanity_analysis.json")
    return 0


if __name__ == "__main__": raise SystemExit(main())
