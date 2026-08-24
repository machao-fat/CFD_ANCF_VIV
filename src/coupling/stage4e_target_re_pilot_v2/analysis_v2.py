"""Corrected force, frequency, yPlus and convergence diagnostics for B2-A-v2."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .identity_v2 import D, NU, RHO, finite, sha256_file


NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def numeric_rows(path: Path, minimum: int = 4) -> np.ndarray:
    rows: list[list[float]] = []
    if not path.exists():
        return np.empty((0, 0), dtype=float)
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        values = re.findall(NUMBER, line)
        if len(values) < minimum:
            continue
        try:
            rows.append([float(v) for v in values])
        except ValueError:
            continue
    if not rows:
        return np.empty((0, 0), dtype=float)
    width = min(len(row) for row in rows)
    return np.asarray([row[:width] for row in rows], dtype=float)


def mesh_span_from_bbox(bbox: dict[str, Any], diameter: float = D) -> float:
    zmin, zmax = float(bbox["z_min_m"]), float(bbox["z_max_m"])
    span = zmax - zmin
    if not math.isfinite(span) or span <= 0:
        raise ValueError("mesh extrusion thickness is unknown or non-positive")
    return float(span)


def normalization_contract(bbox: dict[str, Any], *, aref_from_control: float | None = None, diameter: float = D) -> dict[str, Any]:
    b_mesh = mesh_span_from_bbox(bbox, diameter)
    aref = diameter * b_mesh
    return {
        "diameter_m": diameter,
        "mesh_extrusion_thickness_b_mesh_m": b_mesh,
        "force_output_is_total_N": True,
        "force_per_span_definition": "f_2D_N_per_m = F_OF_N / b_mesh_m",
        "Aref_definition": "Aref_OF_m2 = D_m * b_mesh_m",
        "Aref_OF_m2": aref,
        "controlDict_Aref_m2": aref_from_control,
        "controlDict_Aref_matches_geometry": None if aref_from_control is None else abs(float(aref_from_control) - aref) <= 1e-14,
        "slice_length_used": False,
        "coefficient_definition": "Cd=Fx_global/(0.5*rho*abs(U)^2*D*b_mesh); Cl=Fy_global/(0.5*rho*abs(U)^2*D*b_mesh)",
    }


def parse_raw_forces(path: Path) -> dict[str, Any]:
    data = numeric_rows(path, minimum=7)
    if data.shape[0] == 0 or data.shape[1] < 7:
        return {"available": False, "path": str(path), "rows": 0}
    if not np.all(np.isfinite(data)):
        raise ValueError(f"non-finite raw force file: {path}")
    pressure = data[:, 1:4]
    viscous = data[:, 4:7]
    total = pressure + viscous
    return {"available": True, "path": str(path), "sha256": sha256_file(path), "data": data, "time_s": data[:, 0], "pressure_N": pressure, "viscous_N": viscous, "total_N": total}


def parse_force_coefficients(path: Path) -> dict[str, Any]:
    data = numeric_rows(path, minimum=4)
    if data.shape[0] == 0 or data.shape[1] < 4:
        return {"available": False, "path": str(path), "rows": 0}
    if not np.all(np.isfinite(data)):
        raise ValueError(f"non-finite force coefficient file: {path}")
    return {"available": True, "path": str(path), "sha256": sha256_file(path), "data": data, "time_s": data[:, 0], "cm": data[:, 1], "cd": data[:, 2], "cl": data[:, 3]}


def corrected_coefficients_from_raw(raw: dict[str, Any], *, U_abs: float, b_mesh: float, diameter: float = D, rho: float = RHO) -> dict[str, Any]:
    if not raw.get("available"):
        return {"available": False}
    denom = 0.5 * rho * float(U_abs) ** 2 * diameter * b_mesh
    if denom <= 0:
        raise ValueError("invalid force normalization denominator")
    total = np.asarray(raw["total_N"], dtype=float)
    if total.ndim != 2 or total.shape[0] == 0:
        return {"available": False, "reason": "raw force file has no numeric force rows"}
    return {
        "available": True,
        "time_s": np.asarray(raw["time_s"], dtype=float),
        "Fx_global_N": total[:, 0],
        "Fy_global_N": total[:, 1],
        "f2D_x_N_per_m": total[:, 0] / b_mesh,
        "f2D_y_N_per_m": total[:, 1] / b_mesh,
        "Cd": total[:, 0] / denom,
        "Cl": total[:, 1] / denom,
        "F_ref_N": denom,
        "b_mesh_m": b_mesh,
    }


def force_crosscheck(raw_coeff: dict[str, Any], coeff: dict[str, Any], *, U_abs: float, b_mesh: float, old_aref: float, diameter: float = D, rho: float = RHO, tolerance: float = 1e-10) -> dict[str, Any]:
    corrected = corrected_coefficients_from_raw(raw_coeff, U_abs=U_abs, b_mesh=b_mesh, diameter=diameter, rho=rho)
    if not corrected.get("available") or not coeff.get("available"):
        return {"available": False, "passed": False}
    n = min(len(corrected["Cd"]), len(coeff["cd"]))
    expected_cd = np.asarray(coeff["cd"][:n], dtype=float) * old_aref / (diameter * b_mesh)
    expected_cl = np.asarray(coeff["cl"][:n], dtype=float) * old_aref / (diameter * b_mesh)
    actual_cd, actual_cl = corrected["Cd"][:n], corrected["Cl"][:n]
    cd_err = float(np.max(np.abs(actual_cd - expected_cd)))
    cl_err = float(np.max(np.abs(actual_cl - expected_cl)))
    return finite({"available": True, "raw_rows": len(corrected["Cd"]), "forceCoeffs_rows": len(coeff["cd"]), "old_Aref_m2": old_aref, "corrected_Aref_m2": diameter * b_mesh, "max_abs_Cd_error": cd_err, "max_abs_Cl_error": cl_err, "tolerance": tolerance, "passed": cd_err <= tolerance and cl_err <= tolerance})


def _fft_frequency(time: np.ndarray, signal: np.ndarray) -> tuple[float | None, float | None]:
    if len(time) < 8:
        return None, None
    dt = float(np.median(np.diff(time)))
    if not math.isfinite(dt) or dt <= 0:
        return None, None
    x = signal - float(np.mean(signal))
    power = np.abs(np.fft.rfft(x)) ** 2
    freq = np.fft.rfftfreq(len(x), d=dt)
    if len(power) < 3:
        return None, None
    power[0] = 0
    idx = int(np.argmax(power))
    noise = float(np.median(power[1:]))
    snr = float(power[idx] / max(noise, 1e-30))
    return (float(freq[idx]) if freq[idx] > 0 else None), snr


def _zero_frequency(time: np.ndarray, signal: np.ndarray) -> float | None:
    if len(time) < 4:
        return None
    x = signal - float(np.mean(signal))
    crossings: list[float] = []
    for i in np.flatnonzero((x[:-1] <= 0) & (x[1:] > 0)):
        den = x[i + 1] - x[i]
        frac = 0.0 if den == 0 else -x[i] / den
        crossings.append(float(time[i] + frac * (time[i + 1] - time[i])))
    if len(crossings) < 2:
        return None
    return float(1.0 / np.mean(np.diff(crossings)))


def _autocorrelation_frequency(time: np.ndarray, signal: np.ndarray) -> float | None:
    x = signal - float(np.mean(signal))
    if len(x) < 8 or float(np.std(x)) <= 0:
        return None
    corr = np.correlate(x, x, mode="full")[len(x) - 1:]
    corr[0] = 0
    dt = float(np.median(np.diff(time)))
    min_lag = max(1, int(round(0.2 / max(dt, 1e-12))))
    if min_lag >= len(corr):
        return None
    idx = min_lag + int(np.argmax(corr[min_lag:]))
    return float(1.0 / (idx * dt)) if idx > 0 else None


def _frequency_gate(time: np.ndarray, cl: np.ndarray, *, U_abs: float, diameter: float, amplitude_threshold: float = 1.0e-4) -> dict[str, Any]:
    p2p = float(np.ptp(cl))
    rms = float(np.sqrt(np.mean((cl - np.mean(cl)) ** 2)))
    if p2p <= amplitude_threshold or rms <= amplitude_threshold / 4.0:
        return {"frequency_status": "not_evaluable_low_amplitude", "dominant_frequency_Hz": None, "zero_crossing_frequency_Hz": None, "autocorrelation_frequency_Hz": None, "St": None, "effective_cycles": 0.0, "fft_snr": None, "frequency_consistency_relative": None, "frequency_thresholds": {"absolute_lift_peak_to_peak_min": amplitude_threshold, "minimum_effective_cycles": 15.0, "maximum_consistency_relative": 0.05}}
    fft_freq, snr = _fft_frequency(time, cl)
    zero = _zero_frequency(time, cl)
    autocorr = _autocorrelation_frequency(time, cl)
    candidates = [v for v in (fft_freq, zero, autocorr) if v is not None and v > 0]
    consistency = None if len(candidates) < 2 else float(max(candidates) - min(candidates)) / max(float(np.mean(candidates)), 1e-30)
    cycles = 0.0 if fft_freq is None else float((time[-1] - time[0]) * fft_freq)
    passed = bool(fft_freq and zero and snr is not None and snr >= 10.0 and cycles >= 15.0 and consistency is not None and consistency <= 0.05)
    status = "evaluable_pass" if passed else "not_evaluable_frequency_consistency_or_cycles"
    return {"frequency_status": status, "dominant_frequency_Hz": fft_freq if passed else None, "zero_crossing_frequency_Hz": zero if passed else None, "autocorrelation_frequency_Hz": autocorr if passed else None, "St": None if not passed else float(fft_freq * diameter / U_abs), "effective_cycles": cycles if passed else 0.0, "fft_snr": snr, "frequency_consistency_relative": consistency, "frequency_thresholds": {"absolute_lift_peak_to_peak_min": amplitude_threshold, "minimum_effective_cycles": 15.0, "maximum_consistency_relative": 0.05}}


def corrected_statistics(corrected: dict[str, Any], *, U_abs: float, diameter: float = D, discard_fraction: float = 0.30, amplitude_threshold: float = 1.0e-4) -> dict[str, Any]:
    if not corrected.get("available"):
        return {"available": False}
    time = np.asarray(corrected["time_s"]); cd = np.asarray(corrected["Cd"]); cl = np.asarray(corrected["Cl"])
    if len(time) < 3 or len(cd) < 3 or len(cl) < 3:
        return {"available": False, "reason": "force history has fewer than three numeric samples", "sample_count": int(len(time))}
    cut = max(1, min(len(time) - 3, int(round(discard_fraction * len(time)))))
    t, cdx, clx = time[cut:], cd[cut:], cl[cut:]
    mean_cd = float(np.mean(cdx)); mean_cl = float(np.mean(cl))
    cd_fluct = cdx - mean_cd; cl_fluct = clx - mean_cl
    freq = _frequency_gate(t, clx, U_abs=U_abs, diameter=diameter, amplitude_threshold=amplitude_threshold)
    chunks = np.array_split(np.arange(len(t)), 3)
    windows = []
    for idx in chunks:
        if len(idx) < 3: continue
        tw, cw, lw = t[idx], cdx[idx], clx[idx]
        wf = _frequency_gate(tw, lw, U_abs=U_abs, diameter=diameter, amplitude_threshold=amplitude_threshold)
        windows.append({"mean_Cd": float(np.mean(cw)), "Cd_total_RMS": float(np.sqrt(np.mean(cw * cw))), "Cd_fluctuation_RMS": float(np.sqrt(np.mean((cw - np.mean(cw)) ** 2))), "mean_Cl": float(np.mean(lw)), "Cl_total_RMS": float(np.sqrt(np.mean(lw * lw))), "Cl_fluctuation_RMS": float(np.sqrt(np.mean((lw - np.mean(lw)) ** 2))), "Cl_peak_to_peak": float(np.ptp(lw)), "frequency_status": wf["frequency_status"], "St": wf["St"], "sample_count": int(len(idx)), "duration_s": float(tw[-1] - tw[0])})
    return finite({"available": True, "all_sample_count": int(len(time)), "discarded_transient_sample_count": int(cut), "statistics_sample_count": int(len(t)), "statistics_window_start_s": float(t[0]), "statistics_window_end_s": float(t[-1]), "effective_time_s": float(t[-1] - t[0]), "mean_Cd": mean_cd, "Cd_total_RMS": float(np.sqrt(np.mean(cdx * cdx))), "Cd_fluctuation_RMS": float(np.sqrt(np.mean(cd_fluct * cd_fluct))), "mean_Cl": mean_cl, "Cl_total_RMS": float(np.sqrt(np.mean(clx * clx))), "Cl_fluctuation_RMS": float(np.sqrt(np.mean(cl_fluct * cl_fluct))), "Cl_peak_to_peak": float(np.ptp(clx)), **freq, "three_consecutive_windows": windows, "finite": True})


def relative_changes(windows: Iterable[dict[str, Any]], keys: Iterable[str]) -> dict[str, list[float | None]]:
    rows = list(windows); result: dict[str, list[float | None]] = {}
    for key in keys:
        values = [row.get(key) for row in rows]
        changes = []
        for a, b in zip(values, values[1:]):
            changes.append(None if a is None or b is None else abs(float(b) - float(a)) / max(abs(float(a)), 1e-12))
        result[key] = changes
    return result


def parse_yplus_file(path: Path) -> dict[str, Any]:
    data = numeric_rows(path, minimum=2)
    if data.size == 0:
        return {"available": False, "path": str(path), "p95_y_plus": None, "max_y_plus": None}
    values = data[:, -1]
    return finite({"available": True, "path": str(path), "sha256": sha256_file(path), "sample_count": int(len(values)), "p95_y_plus": float(np.percentile(values, 95)), "max_y_plus": float(np.max(values)), "mean_y_plus": float(np.mean(values))})


def parse_cfl(log_path: Path) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    rows = [(float(a), float(b)) for a, b in re.findall(r"Courant Number mean:\s*(%s)\s*max:\s*(%s)" % (NUMBER, NUMBER), text)]
    return {"samples": len(rows), "mean_cfl_max": max((row[0] for row in rows), default=None), "max_cfl": max((row[1] for row in rows), default=None), "hard_stop_threshold": 0.8, "formal_target": 0.5, "passed": bool(rows) and max(row[1] for row in rows) < 0.8}
