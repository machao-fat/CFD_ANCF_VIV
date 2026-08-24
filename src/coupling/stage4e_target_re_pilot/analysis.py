"""Finite force, stationarity and convergence diagnostics for B2-A."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import numpy as np


def _numeric_rows(path: Path) -> np.ndarray:
    rows: list[list[float]] = []
    if not path.exists():
        return np.empty((0, 0), dtype=float)
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        values = re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", line)
        if values:
            try:
                row = [float(value) for value in values]
            except ValueError:
                continue
            if len(row) >= 4:
                rows.append(row)
    if not rows:
        return np.empty((0, 0), dtype=float)
    width = min(len(row) for row in rows)
    return np.asarray([row[:width] for row in rows], dtype=float)


def _dominant_frequency(time: np.ndarray, signal: np.ndarray) -> float | None:
    if len(time) < 8:
        return None
    dt = float(np.median(np.diff(time)))
    if not math.isfinite(dt) or dt <= 0:
        return None
    demeaned = signal - float(np.mean(signal))
    frequencies = np.fft.rfftfreq(len(demeaned), d=dt)
    power = np.abs(np.fft.rfft(demeaned)) ** 2
    if len(power) < 2:
        return None
    power[0] = 0.0
    idx = int(np.argmax(power))
    return float(frequencies[idx]) if frequencies[idx] > 0 else None


def _zero_crossing_frequency(time: np.ndarray, signal: np.ndarray) -> float | None:
    if len(time) < 4:
        return None
    centered = signal - float(np.mean(signal))
    crossings = np.flatnonzero((centered[:-1] <= 0) & (centered[1:] > 0))
    if len(crossings) < 2:
        return None
    periods = np.diff(time[crossings])
    periods = periods[periods > 0]
    return float(1.0 / np.mean(periods)) if len(periods) else None


def _window_metrics(time: np.ndarray, cd: np.ndarray, cl: np.ndarray, U: float, D: float, span: int = 3) -> list[dict[str, float | None]]:
    chunks = np.array_split(np.arange(len(time)), span)
    output: list[dict[str, float | None]] = []
    for indexes in chunks:
        if len(indexes) < 3:
            continue
        t = time[indexes]
        cdi, cli = cd[indexes], cl[indexes]
        freq = _dominant_frequency(t, cli)
        zero_freq = _zero_crossing_frequency(t, cli)
        output.append({
            "mean_Cd": float(np.mean(cdi)), "Cd_RMS": float(np.sqrt(np.mean(cdi * cdi))),
            "Cl_RMS": float(np.sqrt(np.mean(cli * cli))), "Cl_peak_to_peak": float(np.ptp(cli)),
            "dominant_frequency_Hz": freq,
            "zero_crossing_frequency_Hz": zero_freq,
            "St_dominant": None if freq is None else float(freq * D / abs(U)),
            "sample_count": float(len(indexes)), "duration_s": float(t[-1] - t[0]),
        })
    return output


def analyze_coefficients(path: Path, *, U: float, D: float = 0.02841, discard_fraction: float = 0.30) -> dict[str, Any]:
    data = _numeric_rows(path)
    if data.shape[0] < 8 or data.shape[1] < 4:
        return {"path": str(path), "available": False, "reason": "force coefficient file has fewer than eight numeric rows"}
    time = data[:, 0]
    cd = data[:, 2]
    cl = data[:, 3]
    if not np.all(np.isfinite(data)):
        raise ValueError(f"non-finite force coefficient data: {path}")
    cut = max(1, min(len(data) - 3, int(round(discard_fraction * len(data)))))
    t, cdi, cli = time[cut:], cd[cut:], cl[cut:]
    windows = _window_metrics(t, cdi, cli, U, D)
    dominant = _dominant_frequency(t, cli)
    result: dict[str, Any] = {
        "path": str(path), "available": True, "all_sample_count": int(len(data)),
        "discarded_transient_sample_count": int(cut), "statistics_sample_count": int(len(t)),
        "statistics_window_start_s": float(t[0]), "statistics_window_end_s": float(t[-1]),
        "effective_time_s": float(t[-1] - t[0]),
        "mean_Cd": float(np.mean(cdi)), "Cd_RMS": float(np.sqrt(np.mean(cdi * cdi))),
        "Cl_RMS": float(np.sqrt(np.mean(cli * cli))), "Cl_peak_to_peak": float(np.ptp(cli)),
        "dominant_frequency_Hz": dominant,
        "zero_crossing_frequency_Hz": _zero_crossing_frequency(t, cli),
        "St": None if dominant is None else float(dominant * D / abs(U)),
        "effective_cycles": None if dominant is None else float((t[-1] - t[0]) * dominant),
        "three_consecutive_windows": windows,
        "finite": True,
    }
    if len(windows) >= 3:
        result["three_window_relative_changes"] = {
            "mean_Cd": [abs(windows[i + 1]["mean_Cd"] - windows[i]["mean_Cd"]) / max(abs(windows[i]["mean_Cd"]), 1e-12) for i in range(2)],
            "Cl_RMS": [abs(windows[i + 1]["Cl_RMS"] - windows[i]["Cl_RMS"]) / max(abs(windows[i]["Cl_RMS"]), 1e-12) for i in range(2)],
            "dominant_frequency_Hz": [None if windows[i]["dominant_frequency_Hz"] is None or windows[i + 1]["dominant_frequency_Hz"] is None else abs(windows[i + 1]["dominant_frequency_Hz"] - windows[i]["dominant_frequency_Hz"]) / max(abs(windows[i]["dominant_frequency_Hz"]), 1e-12) for i in range(2)],
            "Cl_peak_to_peak": [abs(windows[i + 1]["Cl_peak_to_peak"] - windows[i]["Cl_peak_to_peak"]) / max(abs(windows[i]["Cl_peak_to_peak"]), 1e-12) for i in range(2)],
        }
    return result


def compare_metrics(a: dict[str, Any], b: dict[str, Any], tolerances: dict[str, float]) -> dict[str, Any]:
    comparisons: dict[str, Any] = {}
    passed = True
    for key, tolerance in tolerances.items():
        av, bv = a.get(key), b.get(key)
        if av is None or bv is None:
            comparisons[key] = {"available": False, "passed": False}
            passed = False
            continue
        denominator = max(abs(float(bv)), 1e-12)
        relative = abs(float(av) - float(bv)) / denominator
        comparisons[key] = {"relative_difference": relative, "threshold": tolerance, "passed": relative <= tolerance}
        passed = passed and relative <= tolerance
    return {"comparisons": comparisons, "passed": passed}


def yplus_audit(log_path: Path) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    values = [float(item) for item in re.findall(r"y\+[^\d]*(\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)]
    return {
        "reported_values": values, "max_y_plus": max(values) if values else None,
        "p95_y_plus": float(np.percentile(values, 95)) if values else None,
        "wall_resolved_yplus_le_1_95_percent": bool(values and np.percentile(values, 95) <= 1.0),
        "audit_status": "reported_by_solver_or_postprocess" if values else "not_reported_by_default_solver_log",
    }
