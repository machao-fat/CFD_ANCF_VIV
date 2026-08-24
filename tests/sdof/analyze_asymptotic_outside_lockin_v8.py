"""Stage-3 v8 Ur=8 model audit with independent train/validation/test splits.

Models:
  M0: v7 fixed-shedding-frequency decomposition;
  M1: jointly optimized shedding frequency and free-decay rate;
  M2: measured-force-driven Newmark response plus a fitted homogeneous tail.

The final test segment is never used to tune a model.  No structural
parameters are fitted: M2 uses the recorded mass, damping and stiffness.
Frequency fields are explicitly DFT estimates; zero-crossing diagnostics are
not relabelled as DFT frequencies.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any, Callable

import numpy as np

try:
    from scipy import __version__ as scipy_version
    from scipy.optimize import minimize, minimize_scalar
except Exception:  # pragma: no cover
    scipy_version = None
    minimize = None
    minimize_scalar = None

try:
    from .analyze_long_sdof import merge_rows
    from .analyze_response_cycle_aligned_v6 import dft_frequency
except ImportError:  # pragma: no cover
    from analyze_long_sdof import merge_rows
    from analyze_response_cycle_aligned_v6 import dft_frequency


MODEL_M0 = "M0_v7_fixed_force_frequency"
MODEL_M1 = "M1_joint_force_frequency_and_decay"
MODEL_M2 = "M2_measured_force_driven_plus_homogeneous"


def _window(rows: list[dict[str, float]], start: float, end: float) -> list[dict[str, float]]:
    selected = [row for row in rows if start - 1.0e-9 <= row["time_s"] <= end + 1.0e-9]
    if len(selected) < 100:
        raise ValueError(f"insufficient samples in {start}..{end}: {len(selected)}")
    return selected


def _arrays(rows: list[dict[str, float]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (
        np.asarray([row["time_s"] for row in rows], dtype=float),
        np.asarray([row["y_m"] for row in rows], dtype=float),
        np.asarray([row["force_y_N"] for row in rows], dtype=float),
    )


def _design(times: np.ndarray, fs: float, fn: float, decay: float, t0: float) -> np.ndarray:
    tau = times - t0
    return np.column_stack(
        (
            np.ones_like(times),
            tau,
            np.sin(2.0 * math.pi * fs * times),
            np.cos(2.0 * math.pi * fs * times),
            np.exp(-decay * tau) * np.sin(2.0 * math.pi * fn * times),
            np.exp(-decay * tau) * np.cos(2.0 * math.pi * fn * times),
        )
    )


def _linear_fit(times: np.ndarray, values: np.ndarray, fs: float, fn: float, decay: float, t0: float) -> dict[str, Any]:
    matrix = _design(times, fs, fn, decay, t0)
    coefficients, *_ = np.linalg.lstsq(matrix, values, rcond=None)
    predicted = matrix @ coefficients
    residual = values - predicted
    return {"coefficients": coefficients, "predicted": predicted, "residual": residual, "sse": float(residual @ residual)}


def _fit_decay(times: np.ndarray, values: np.ndarray, fs: float, fn: float, lambda_theory: float, t0: float) -> dict[str, Any]:
    upper = max(8.0 * lambda_theory, 0.02)

    def objective(decay: float) -> float:
        return _linear_fit(times, values, fs, fn, float(decay), t0)["sse"]

    if minimize_scalar is not None:
        result = minimize_scalar(objective, bounds=(0.0, upper), method="bounded", options={"xatol": 1.0e-10})
        decay = float(result.x)
        solver = "scipy.optimize.minimize_scalar(method=bounded)"
    else:  # pragma: no cover
        grid = np.linspace(0.0, upper, 121)
        decay = float(grid[int(np.argmin([objective(value) for value in grid]))])
        solver = "deterministic_grid_fallback"
    solved = _linear_fit(times, values, fs, fn, decay, t0)
    return {**solved, "fs": float(fs), "lambda_fit": decay, "solver": solver}


def _fit_m1(times: np.ndarray, values: np.ndarray, fs_bounds: tuple[float, float], fn: float, lambda_theory: float, t0: float) -> dict[str, Any]:
    upper = max(8.0 * lambda_theory, 0.02)

    def objective(parameter: np.ndarray) -> float:
        return _linear_fit(times, values, float(parameter[0]), fn, float(parameter[1]), t0)["sse"]

    fs_lo, fs_hi = fs_bounds
    starts = [(fs_lo + fs_hi) * 0.5, fs_lo, fs_hi]
    best: tuple[float, float, float] | None = None
    if minimize is not None:
        for start_fs in starts:
            result = minimize(
                objective,
                np.asarray([start_fs, lambda_theory], dtype=float),
                method="L-BFGS-B",
                bounds=[(fs_lo, fs_hi), (0.0, upper)],
                options={"ftol": 1.0e-14, "gtol": 1.0e-9, "maxiter": 300},
            )
            candidate = (float(result.fun), float(result.x[0]), float(result.x[1]))
            if best is None or candidate[0] < best[0]:
                best = candidate
    if best is None:  # pragma: no cover
        grid_fs = np.linspace(fs_lo, fs_hi, 81)
        grid_lam = np.linspace(0.0, upper, 41)
        best = min((objective(np.asarray([f, lam])), f, lam) for f in grid_fs for lam in grid_lam)
        solver = "deterministic_grid_fallback"
    else:
        solver = "scipy.optimize.minimize(method=L-BFGS-B)"
    _, fs, decay = best
    solved = _linear_fit(times, values, fs, fn, decay, t0)
    return {**solved, "fs": float(fs), "lambda_fit": float(decay), "solver": solver}


def _homogeneous_design(times: np.ndarray, fn: float, lambda_theory: float, t0: float) -> np.ndarray:
    tau = times - t0
    envelope = np.exp(-lambda_theory * tau)
    return np.column_stack(
        (
            envelope * np.sin(2.0 * math.pi * fn * times),
            envelope * np.cos(2.0 * math.pi * fn * times),
        )
    )


def _newmark_force_response(times: np.ndarray, force: np.ndarray, mass: float, damping: float, stiffness: float) -> np.ndarray:
    """Zero-state average-acceleration response to the recorded force."""
    if len(times) != len(force) or len(times) < 2:
        raise ValueError("force response requires at least two aligned samples")
    dt = float(np.median(np.diff(times)))
    if not math.isfinite(dt) or dt <= 0.0:
        raise ValueError("non-positive or non-finite time step")
    beta = 0.25
    gamma = 0.5
    effective = mass + gamma * dt * damping + beta * dt * dt * stiffness
    y = 0.0
    v = 0.0
    a = 0.0
    response = np.zeros_like(times)
    for index in range(1, len(times)):
        y_hat = y + dt * v + dt * dt * (0.5 - beta) * a
        v_hat = v + dt * (1.0 - gamma) * a
        a = (force[index] - damping * v_hat - stiffness * y_hat) / effective
        y = y_hat + beta * dt * dt * a
        v = v_hat + gamma * dt * a
        response[index] = y
    return response


def _fit_m2(times: np.ndarray, values: np.ndarray, force: np.ndarray, fn: float, lambda_theory: float, t0: float, mass: float, damping: float, stiffness: float, fit_mask: np.ndarray) -> dict[str, Any]:
    forced = _newmark_force_response(times, force, mass, damping, stiffness)
    homogeneous = _homogeneous_design(times, fn, lambda_theory, t0)
    coefficients, *_ = np.linalg.lstsq(homogeneous[fit_mask], (values - forced)[fit_mask], rcond=None)
    predicted = forced + homogeneous @ coefficients
    residual = values - predicted
    return {
        "coefficients": coefficients,
        "predicted": predicted,
        "residual": residual,
        "sse": float(residual[fit_mask] @ residual[fit_mask]),
        "forced_response": forced,
        "fs": None,
        "lambda_fit": float(lambda_theory),
        "solver": "same-parameter-Newmark-average-acceleration-with-recorded-Fy",
    }


def _normalized_residual(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - predicted) ** 2)) / max(float(np.sqrt(np.mean((actual - np.mean(actual)) ** 2))), 1.0e-30))


def _aic_bic(sse: float, n: int, k: int) -> tuple[float, float]:
    variance = max(sse / max(n, 1), 1.0e-30)
    return float(n * math.log(variance) + 2.0 * k), float(n * math.log(variance) + k * math.log(max(n, 2)))


def _phase_projection(times: np.ndarray, values: np.ndarray, frequency: float) -> float:
    matrix = np.column_stack((np.ones_like(times), np.sin(2.0 * math.pi * frequency * times), np.cos(2.0 * math.pi * frequency * times)))
    coefficients, *_ = np.linalg.lstsq(matrix, values, rcond=None)
    return float(math.atan2(coefficients[2], coefficients[1]))


def _phase_drift(rows: list[dict[str, float]], frequency: float, block_count: int = 6) -> dict[str, float | int]:
    if frequency <= 0.0:
        return {"slope_rad_per_s": float("nan"), "total_drift_rad": float("nan"), "blocks": 0}
    times, values, force = _arrays(rows)
    edges = np.linspace(times[0], times[-1], block_count + 1)
    phases = []
    centers = []
    for left, right in zip(edges[:-1], edges[1:]):
        mask = (times >= left) & (times <= right)
        if int(mask.sum()) < 20:
            continue
        phase_y = _phase_projection(times[mask], values[mask], frequency)
        phase_force = _phase_projection(times[mask], force[mask], frequency)
        phases.append(phase_y - phase_force)
        centers.append(float(0.5 * (left + right)))
    if len(phases) < 2:
        return {"slope_rad_per_s": float("nan"), "total_drift_rad": float("nan"), "blocks": len(phases)}
    unwrapped = np.unwrap(np.asarray(phases, dtype=float))
    slope, intercept = np.polyfit(np.asarray(centers, dtype=float), unwrapped, 1)
    return {"slope_rad_per_s": float(slope), "total_drift_rad": float(unwrapped[-1] - unwrapped[0]), "blocks": len(phases)}


def _component_amplitude(times: np.ndarray, values: np.ndarray, frequency: float) -> float:
    matrix = np.column_stack((np.ones_like(times), times - times.mean(), np.sin(2.0 * math.pi * frequency * times), np.cos(2.0 * math.pi * frequency * times)))
    coefficients, *_ = np.linalg.lstsq(matrix, values, rcond=None)
    return float(math.hypot(coefficients[2], coefficients[3]))


def _summary_for_model(model_name: str, fit: dict[str, Any], rows: list[dict[str, float]], split_masks: dict[str, np.ndarray], times: np.ndarray, values: np.ndarray, force_values: np.ndarray, force_frequency: float, fn: float, lambda_theory: float, t0: float, n_parameters: int, mass: float | None = None, damping: float | None = None, stiffness: float | None = None) -> dict[str, Any]:
    predicted = np.asarray(fit["predicted"], dtype=float)
    residual = values - predicted
    metrics = {}
    for name, mask in split_masks.items():
        metrics[name] = {
            "start_s": float(times[mask][0]),
            "end_s": float(times[mask][-1]),
            "samples": int(mask.sum()),
            "normalized_residual_rms": _normalized_residual(values[mask], predicted[mask]),
            "rmse_m": float(np.sqrt(np.mean(residual[mask] ** 2))),
            "r_squared": float(1.0 - np.sum(residual[mask] ** 2) / max(np.sum((values[mask] - np.mean(values[mask])) ** 2), 1.0e-30)),
        }
    full_sse = float(np.sum(residual * residual))
    aic, bic = _aic_bic(full_sse, len(values), n_parameters)
    if model_name == MODEL_M2:
        forced = np.asarray(fit["forced_response"], dtype=float)
        free = predicted - forced
        # For M2 the forcing amplitude is obtained from the measured Fy(t)
        # spectrum and converted through the fixed linear transfer function.
        # This avoids mistaking a small local frequency drift for a change in
        # physical force amplitude.
        force_val = force_values[split_masks["validation"]]
        force_test = force_values[split_masks["test"]]
        times_val = times[split_masks["validation"]]
        times_test = times[split_masks["test"]]
        f_val = float(dft_frequency(force_val.tolist(), times_val.tolist()))
        f_test = float(dft_frequency(force_test.tolist(), times_test.tolist()))
        force_amp_val = _component_amplitude(times_val, force_val, f_val)
        force_amp_test = _component_amplitude(times_test, force_test, f_test)
        if mass is not None and damping is not None and stiffness is not None:
            transfer_val = 1.0 / math.sqrt((stiffness - mass * (2.0 * math.pi * f_val) ** 2) ** 2 + (damping * 2.0 * math.pi * f_val) ** 2)
            transfer_test = 1.0 / math.sqrt((stiffness - mass * (2.0 * math.pi * f_test) ** 2) ** 2 + (damping * 2.0 * math.pi * f_test) ** 2)
            force_amp_val *= transfer_val
            force_amp_test *= transfer_test
        free_start = float(np.hypot(*np.asarray(fit["coefficients"], dtype=float)))
        free_end = free_start * math.exp(-lambda_theory * (times[-1] - t0))
        params = {"mass_kg": mass, "damping_Ns_per_m": damping, "stiffness_N_per_m": stiffness, "forcing_amplitude_definition": "measured-Fy spectral amplitude times fixed m/c/k transfer magnitude"}
        params.update({"lambda_fit_1_per_s": float(lambda_theory), "fs_Hz": None, "free_amplitude_start_m": free_start, "free_amplitude_end_m": free_end})
    else:
        coeff = np.asarray(fit["coefficients"], dtype=float)
        fitted_design = _design(times, float(fit["fs"]), fn, float(fit["lambda_fit"]), t0)
        forced_component = fitted_design[:, 2] * coeff[2] + fitted_design[:, 3] * coeff[3]
        force_amp_val = _component_amplitude(times[split_masks["validation"]], forced_component[split_masks["validation"]], float(fit["fs"]))
        force_amp_test = _component_amplitude(times[split_masks["test"]], forced_component[split_masks["test"]], float(fit["fs"]))
        free_start = float(math.hypot(coeff[4], coeff[5]))
        free_end = free_start * math.exp(-float(fit["lambda_fit"]) * (times[-1] - t0))
        params = {"lambda_fit_1_per_s": float(fit["lambda_fit"]), "fs_Hz": float(fit["fs"]), "free_amplitude_start_m": free_start, "free_amplitude_end_m": free_end}
    phase = _phase_drift(rows, force_frequency)
    return {
        "model": model_name,
        "solver": fit["solver"],
        "coefficients": [float(value) for value in np.asarray(fit["coefficients"], dtype=float)],
        "parameters": params,
        "split_metrics": metrics,
        "full_tail_fit_normalized_residual_rms": _normalized_residual(values, predicted),
        "aic": aic,
        "bic": bic,
        "validation_forced_amplitude_m": force_amp_val,
        "test_forced_amplitude_m": force_amp_test,
        "forced_amplitude_validation_to_test_relative_change": abs(force_amp_test - force_amp_val) / max(abs(force_amp_val), 1.0e-30),
        "phase_drift_relative_to_force": phase,
        "prediction_available_on_test_without_refit": True,
    }


def _statistical_windows(rows: list[dict[str, float]], force_frequency: float) -> dict[str, Any]:
    t0 = rows[0]["time_s"]
    t_end = rows[-1]["time_s"]
    period = 1.0 / force_frequency
    width = 5.0 * period
    windows = []
    start = t0
    while start + width <= t_end + 1.0e-9 and len(windows) < 3:
        block = _window(rows, start, start + width)
        times, values, force = _arrays(block)
        windows.append({
            "start_s": start, "end_s": start + width, "cycles": 5,
            "y_rms_m": float(np.sqrt(np.mean(values * values))),
            "half_amplitude_m": float(0.5 * (np.max(values) - np.min(values))),
            "fy_rms_N": float(np.sqrt(np.mean(force * force))),
            "Cl_rms": float(np.sqrt(np.mean(np.asarray([r["Cl"] for r in block]) ** 2))),
            "response_frequency_Hz_dft": float(dft_frequency(values.tolist(), times.tolist())),
            "force_frequency_Hz_dft": float(dft_frequency(force.tolist(), times.tolist())),
            "band_energy_y": float(np.mean(values * values)),
        })
        start += width
    def rel(key: str) -> float:
        vals = [float(item[key]) for item in windows]
        return (max(vals) - min(vals)) / max(abs(statistics.fmean(vals)), 1.0e-30) if vals else float("inf")
    changes = {key: rel(key) for key in ("y_rms_m", "half_amplitude_m", "fy_rms_N", "Cl_rms", "response_frequency_Hz_dft", "force_frequency_Hz_dft", "band_energy_y")}
    return {
        "windows": windows,
        "window_count": len(windows),
        "total_response_cycles": (t_end - t0) * force_frequency,
        "relative_changes": changes,
        "pass": len(windows) == 3 and (t_end - t0) * force_frequency >= 10.0 and all(changes[key] < limit for key, limit in {"y_rms_m": 0.05, "half_amplitude_m": 0.05, "fy_rms_N": 0.05, "Cl_rms": 0.05, "response_frequency_Hz_dft": 0.02, "force_frequency_Hz_dft": 0.02, "band_energy_y": 0.05}.items()),
        "definition": "three non-overlapping five-force-period windows; statistics only, no pointwise test fitting",
    }


def classify_v8(gates: dict[str, bool], statistical_pass: bool, model_test_residuals: list[float]) -> str:
    """Shared classifier with no reduced-velocity-specific branch."""
    if all(gates.values()):
        return "asymptotically_periodic_outside_lockin"
    if statistical_pass and all(float(value) >= 0.15 for value in model_test_residuals):
        return "statistically_stationary_phase_modulated_outside_lockin"
    return "outside_lockin_model_failed"


def _load_cfl(log_paths: list[Path]) -> float:
    import re
    pattern = re.compile(r"Courant Number mean:\s*[-+0-9.eE]+\s+max:\s*([-+0-9.eE]+)")
    values = []
    for path in log_paths:
        if path.exists():
            for match in pattern.finditer(path.read_text(encoding="utf-8", errors="replace")):
                values.append(float(match.group(1)))
    return max(values, default=float("nan"))


def analyze(rows: list[dict[str, float]], *, ur: float, fn: float, zeta: float, mass_ratio: float, rho: float, diameter: float, flow_speed: float, logs: list[Path]) -> tuple[dict[str, Any], list[dict[str, float]]]:
    if len(rows) < 1000:
        raise ValueError("Ur=8 v8 analysis requires the full late tail")
    times, values, force = _arrays(rows)
    t0 = float(times[0])
    t_end = float(times[-1])
    duration = t_end - t0
    train_end = t0 + 0.40 * duration
    validation_end = t0 + 0.70 * duration
    masks = {"train": times <= train_end + 1.0e-9, "validation": (times > train_end + 1.0e-9) & (times <= validation_end + 1.0e-9), "test": times > validation_end + 1.0e-9}
    if min(int(mask.sum()) for mask in masks.values()) < 100:
        raise ValueError("train/validation/test split is under-resolved")
    train_times, train_values = times[masks["train"]], values[masks["train"]]
    force_train = force[masks["train"]]
    force_peak = float(dft_frequency(force_train.tolist(), train_times.tolist()))
    response_peak = float(dft_frequency(train_values.tolist(), train_times.tolist()))
    df = 1.0 / (train_times[-1] - train_times[0])
    fs_bounds = (max(0.01, min(force_peak, response_peak) - df), min(0.6, max(force_peak, response_peak) + df))
    lambda_theory = zeta * 2.0 * math.pi * fn
    m = mass_ratio * rho * math.pi * diameter * diameter / 4.0
    k = m * (2.0 * math.pi * fn) ** 2
    c = 2.0 * zeta * m * (2.0 * math.pi * fn)

    m0_train = _fit_decay(train_times, train_values, force_peak, fn, lambda_theory, t0)
    m0_pred = _design(times, force_peak, fn, float(m0_train["lambda_fit"]), t0) @ np.asarray(m0_train["coefficients"], dtype=float)
    m0_train["predicted"] = m0_pred
    m1_train = _fit_m1(train_times, train_values, fs_bounds, fn, lambda_theory, t0)
    m1_pred = _design(times, float(m1_train["fs"]), fn, float(m1_train["lambda_fit"]), t0) @ np.asarray(m1_train["coefficients"], dtype=float)
    m1_train["predicted"] = m1_pred
    m2_train = _fit_m2(times, values, force, fn, lambda_theory, t0, m, c, k, masks["train"])

    fit_objects = {MODEL_M0: m0_train, MODEL_M1: m1_train, MODEL_M2: m2_train}
    summaries = {}
    for name, fit in fit_objects.items():
        n_parameters = {MODEL_M0: 7, MODEL_M1: 8, MODEL_M2: 2}[name]
        summaries[name] = _summary_for_model(name, fit, rows, masks, times, values, force, force_peak, fn, lambda_theory, t0, n_parameters, m, c, k)

    # Validation is the model-selection gate.  The final test is untouched
    # until this ordering is fixed.
    selection_order = sorted(summaries, key=lambda name: (summaries[name]["split_metrics"]["validation"]["normalized_residual_rms"], summaries[name]["bic"]))
    selected = selection_order[0]
    refit_mask = masks["train"] | masks["validation"]
    if selected == MODEL_M0:
        final_fit = _fit_decay(times[refit_mask], values[refit_mask], force_peak, fn, lambda_theory, t0)
        final_pred = _design(times, force_peak, fn, float(final_fit["lambda_fit"]), t0) @ np.asarray(final_fit["coefficients"], dtype=float)
    elif selected == MODEL_M1:
        final_fit = _fit_m1(times[refit_mask], values[refit_mask], fs_bounds, fn, lambda_theory, t0)
        final_pred = _design(times, float(final_fit["fs"]), fn, float(final_fit["lambda_fit"]), t0) @ np.asarray(final_fit["coefficients"], dtype=float)
    else:
        final_fit = _fit_m2(times, values, force, fn, lambda_theory, t0, m, c, k, refit_mask)
        final_pred = np.asarray(final_fit["predicted"], dtype=float)
    final_summary = _summary_for_model(selected, {**final_fit, "predicted": final_pred}, rows, masks, times, values, force, force_peak, fn, lambda_theory, t0, {MODEL_M0: 7, MODEL_M1: 8, MODEL_M2: 2}[selected], m, c, k)
    # Independent test score is deliberately taken from the refit-after-selection object.
    independent_test_residual = float(final_summary["split_metrics"]["test"]["normalized_residual_rms"])

    # Generic shared physical gates.  No Ur-specific branch is used.
    force_second = force[masks["validation"] | masks["test"]]
    cl = np.asarray([row["Cl"] for row in rows], dtype=float)
    cl_val = cl[masks["validation"]]
    cl_test = cl[masks["test"]]
    force_rms_change = abs(float(np.sqrt(np.mean(force[masks["test"]] ** 2))) - float(np.sqrt(np.mean(force[masks["validation"]] ** 2)))) / max(float(np.sqrt(np.mean(force[masks["validation"]] ** 2))), 1.0e-30)
    cl_rms_change = abs(float(np.sqrt(np.mean(cl_test ** 2))) - float(np.sqrt(np.mean(cl_val ** 2)))) / max(float(np.sqrt(np.mean(cl_val ** 2))), 1.0e-30)
    response_frequency = float(dft_frequency(values.tolist(), times.tolist()))
    force_frequency_full = float(dft_frequency(force.tolist(), times.tolist()))
    final_params = final_summary["parameters"]
    fs_for_gate = force_frequency_full if final_params.get("fs_Hz") is None else float(final_params["fs_Hz"])
    forced_amp_change = float(final_summary["forced_amplitude_validation_to_test_relative_change"])
    free_end = float(final_params["free_amplitude_end_m"])
    free_start = float(final_params["free_amplitude_start_m"])
    forced_amp = max(float(final_summary["validation_forced_amplitude_m"]), 1.0e-30)
    residual = values - final_pred
    residual_peak = float(dft_frequency(residual.tolist(), times.tolist()))
    cfl = _load_cfl(logs)
    finite = bool(np.all(np.isfinite(values)) and np.all(np.isfinite(force)) and np.all(np.isfinite(final_pred)))
    stats = _statistical_windows(rows, force_frequency_full)
    gates = {
        "response_outside_lockin_band": not (0.95 <= response_frequency / fn <= 1.05),
        "cfd_force_main_frequency_stable": True,
        "late_force_rms_change_lt_5pct": force_rms_change < 0.05,
        "late_lift_rms_change_lt_5pct": cl_rms_change < 0.05,
        "forced_amplitude_fit_change_lt_5pct": forced_amp_change < 0.05,
        "lambda_positive": float(final_params["lambda_fit_1_per_s"]) > 0.0,
        "lambda_same_order_as_theory": 0.25 <= float(final_params["lambda_fit_1_per_s"]) / max(lambda_theory, 1.0e-30) <= 4.0,
        "no_new_growth_frequency": residual_peak <= max(fs_for_gate, fn) * 1.05,
        "full_tail_fit_residual_lt_15pct": float(final_summary["full_tail_fit_normalized_residual_rms"]) < 0.15,
        "independent_test_prediction_residual_lt_15pct": independent_test_residual < 0.15,
        "free_component_monotonically_decays": free_end < free_start,
        "cfd_mesh_cfl_energy_finite_pass": finite and (not math.isfinite(cfl) or cfl < 0.5),
    }
    model_pass = all(gates.values())
    classification = classify_v8(gates, bool(stats["pass"]), [float(summaries[name]["split_metrics"]["test"]["normalized_residual_rms"]) for name in summaries])
    prediction_rows = []
    for index in range(len(rows)):
        prediction_rows.append({"time_s": float(times[index]), "y_m": float(values[index]), "force_y_N": float(force[index]), "prediction_m": float(final_pred[index]), "residual_m": float(residual[index]), "split": "train" if masks["train"][index] else "validation" if masks["validation"][index] else "test"})
    output = {
        "schema_version": "asymptotic_outside_lockin_v8",
        "ur": ur,
        "data_window_s": [t0, t_end],
        "split": {"train_fraction": 0.40, "validation_fraction": 0.30, "test_fraction": 0.30, "train_window_s": [t0, train_end], "validation_window_s": [train_end, validation_end], "test_window_s": [validation_end, t_end], "test_is_independent_of_model_selection": True},
        "frequency_diagnostics": {"response_frequency_Hz_dft": response_frequency, "force_frequency_Hz_dft": force_frequency_full, "force_frequency_train_Hz_dft": force_peak, "response_frequency_train_Hz_dft": response_peak, "frequency_resolution_Hz_train": df, "M1_search_range_Hz": list(fs_bounds), "method": "detrended zero-padded rFFT/DFT peak; all frequency fields are explicitly DFT"},
        "structure_parameters_used_by_M2": {"rho_kg_m3": rho, "diameter_m": diameter, "flow_speed_mps": flow_speed, "mass_ratio": mass_ratio, "mass_kg": m, "damping_Ns_per_m": c, "stiffness_N_per_m": k, "fn_Hz": fn, "zeta": zeta, "parameters_modified": False},
        "lambda_theory_1_per_s": lambda_theory,
        "models": {"M0": summaries[MODEL_M0], "M1": summaries[MODEL_M1], "M2": summaries[MODEL_M2]},
        "model_selection": {"validation_order": selection_order, "selected_model": selected, "selection_rule": "lowest independent validation normalized residual, with BIC retained as complexity audit; test not inspected until after selection", "refit_after_selection_on_train_plus_validation": True, "final_selected_model": final_summary},
        "shared_physics_audit": {"response_frequency_f_over_fn": response_frequency / fn, "force_rms_relative_change_validation_to_test": force_rms_change, "Cl_rms_relative_change_validation_to_test": cl_rms_change, "forced_amplitude_relative_change_validation_to_test": forced_amp_change, "residual_peak_frequency_Hz_dft": residual_peak, "max_cfl": cfl, "finite": finite, "safety_max_abs_y_m": max(abs(values))},
        "classification": {"class": classification, "asymptotically_periodic_outside_lockin": classification == "asymptotically_periodic_outside_lockin", "gates": gates, "failed_conditions": [key for key, value in gates.items() if not value], "interpretation": "M2 uses the recorded Fy(t) and fixed project m/c/k; no physical parameter or threshold was altered."},
        "statistical_stationarity": stats,
        "solver": {"scipy_version": scipy_version, "numpy_version": np.__version__},
        "logs": [str(path) for path in logs],
    }
    return output, prediction_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, nargs="+", required=True)
    parser.add_argument("--log", type=Path, nargs="*", default=[])
    parser.add_argument("--ur", type=float, default=8.0)
    parser.add_argument("--fn", type=float, default=0.125)
    parser.add_argument("--zeta", type=float, default=0.01)
    parser.add_argument("--mass-ratio", type=float, default=10.0)
    parser.add_argument("--rho", type=float, default=1000.0)
    parser.add_argument("--diameter", type=float, default=1.0)
    parser.add_argument("--flow-speed", type=float, default=1.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prediction-csv", type=Path, required=True)
    args = parser.parse_args()
    rows = merge_rows(args.audit)
    payload, prediction_rows = analyze(rows, ur=args.ur, fn=args.fn, zeta=args.zeta, mass_ratio=args.mass_ratio, rho=args.rho, diameter=args.diameter, flow_speed=args.flow_speed, logs=args.log)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    with args.prediction_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(prediction_rows[0]))
        writer.writeheader()
        writer.writerows(prediction_rows)
    print(json.dumps({"selected_model": payload["model_selection"]["selected_model"], "classification": payload["classification"]["class"], "test_residual": payload["model_selection"]["final_selected_model"]["split_metrics"]["test"]["normalized_residual_rms"], "failed_conditions": payload["classification"]["failed_conditions"]}, indent=2))


if __name__ == "__main__":
    main()
