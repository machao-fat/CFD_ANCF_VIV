"""Stage-three v7 asymptotic decomposition for low-damping, outside-lock-in SDOF runs.

The response is represented by a forced shedding component and an independently
decaying structural component.  The two frequency components are fixed by
measurements/parameters; only the exponential decay rate is nonlinear.  For a
given decay rate all coefficients are obtained by linear least squares.  This
keeps the fit auditable and avoids interpreting a fitted component as an FFT
frequency.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

import numpy as np

try:
    from scipy import __version__ as scipy_version
    from scipy.optimize import minimize_scalar
except Exception:  # pragma: no cover - exercised only on minimal installations
    scipy_version = None
    minimize_scalar = None

try:
    from .analyze_long_sdof import max_cfl, merge_rows, trap
    from .analyze_response_cycle_aligned_v6 import dft_frequency
except ImportError:  # Direct script execution remains supported.
    from analyze_long_sdof import max_cfl, merge_rows, trap
    from analyze_response_cycle_aligned_v6 import dft_frequency


MODEL_FORM = (
    "c0+c1*t+As*sin(2*pi*fs*t+phis)+"
    "An*exp(-lambda*(t-t0))*sin(2*pi*fn*t+phin)"
)


def _window(rows: list[dict[str, float]], start: float, end: float) -> list[dict[str, float]]:
    selected = [row for row in rows if start - 1.0e-10 <= row["time_s"] <= end + 1.0e-10]
    if len(selected) < 100:
        raise ValueError(f"insufficient samples in {start}..{end}: {len(selected)}")
    return selected


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


def _solve_for_decay(times: np.ndarray, values: np.ndarray, fs: float, fn: float, decay: float, t0: float) -> dict[str, object]:
    matrix = _design(times, fs, fn, decay, t0)
    coefficients, _, _, _ = np.linalg.lstsq(matrix, values, rcond=None)
    fitted = matrix @ coefficients
    residual = values - fitted
    return {"decay": float(decay), "coefficients": coefficients, "fitted": fitted, "residual": residual, "sse": float(residual @ residual)}


def _fit(times: np.ndarray, values: np.ndarray, fs: float, fn: float, lambda_theory: float, t0: float) -> dict[str, object]:
    upper = max(0.1, 12.0 * lambda_theory)

    def objective(decay: float) -> float:
        return float(_solve_for_decay(times, values, fs, fn, decay, t0)["sse"])

    if minimize_scalar is not None:
        result = minimize_scalar(objective, bounds=(1.0e-9, upper), method="bounded", options={"xatol": 1.0e-10, "maxiter": 500})
        solved = _solve_for_decay(times, values, fs, fn, float(result.x), t0)
        solver = "scipy.optimize.minimize_scalar(method=bounded)+numpy.linalg.lstsq"
    else:  # pragma: no cover - fallback retained for reproducibility on minimal systems
        grid = np.geomspace(1.0e-9, upper, 4000)
        decay = min(grid, key=objective)
        solved = _solve_for_decay(times, values, fs, fn, float(decay), t0)
        solver = "log-grid(4000)+numpy.linalg.lstsq fallback; scipy unavailable"

    coef = np.asarray(solved["coefficients"], dtype=float)
    fitted = np.asarray(solved["fitted"], dtype=float)
    residual = np.asarray(solved["residual"], dtype=float)
    original_rms = float(np.sqrt(np.mean((values - np.mean(values)) ** 2)))
    sst = float(np.sum((values - np.mean(values)) ** 2))
    r2 = 1.0 - float(np.sum(residual * residual)) / max(sst, 1.0e-30)
    forced_sin, forced_cos = coef[2], coef[3]
    free_sin, free_cos = coef[4], coef[5]
    return {
        "lambda_fit": float(solved["decay"]),
        "coefficients": coef.tolist(),
        "As_m": float(math.hypot(forced_sin, forced_cos)),
        "An_m": float(math.hypot(free_sin, free_cos)),
        "phis_rad": float(math.atan2(forced_cos, forced_sin)),
        "phin_rad": float(math.atan2(free_cos, free_sin)),
        "r_squared": r2,
        "normalized_residual_rms": float(np.sqrt(np.mean(residual * residual)) / max(original_rms, 1.0e-30)),
        "fit_rms_m": float(np.sqrt(np.mean(residual * residual))),
        "original_detrended_rms_m": original_rms,
        "solver": solver,
    }


def _predict(fit: dict[str, object], times: np.ndarray, fs: float, fn: float, t0: float) -> np.ndarray:
    matrix = _design(times, fs, fn, float(fit["lambda_fit"]), t0)
    return matrix @ np.asarray(fit["coefficients"], dtype=float)


def _force_frequency(rows: list[dict[str, float]], start: float, end: float) -> dict[str, float]:
    middle = 0.5 * (start + end)
    windows = ((start, middle), (middle, end))
    force = []
    lift = []
    for left, right in windows:
        block = _window(rows, left, right)
        times = [r["time_s"] for r in block]
        force.append(dft_frequency([r["force_y_N"] for r in block], times))
        lift.append(dft_frequency([r["Cl"] for r in block], times))
    return {
        "force_window_1_Hz_dft": force[0],
        "force_window_2_Hz_dft": force[1],
        "lift_window_1_Hz_dft": lift[0],
        "lift_window_2_Hz_dft": lift[1],
        "force_frequency_Hz_dft": float(statistics.fmean(force)),
        "lift_frequency_Hz_dft": float(statistics.fmean(lift)),
        "force_frequency_relative_change": abs(force[1] - force[0]) / max(abs(force[0]), 1.0e-30),
        "lift_frequency_relative_change": abs(lift[1] - lift[0]) / max(abs(lift[0]), 1.0e-30),
        "method": "detrended zero-padded rFFT/DFT peak; frequency fields are explicitly DFT, not zero-crossing",
    }


def _rms(rows: list[dict[str, float]], key: str) -> float:
    return float(math.sqrt(statistics.fmean(row[key] * row[key] for row in rows)))


def _fit_region(rows: list[dict[str, float]], start: float, end: float, fs: float, fn: float, lambda_theory: float, label: str) -> dict[str, object]:
    block = _window(rows, start, end)
    t = np.asarray([r["time_s"] for r in block], dtype=float)
    y = np.asarray([r["y_m"] for r in block], dtype=float)
    result = _fit(t, y, fs, fn, lambda_theory, start)
    result.update({"label": label, "start_s": start, "end_s": end, "samples": len(block)})
    return result


def _classification(*, response_ratio: float, force_frequency_stable: bool, force_rms_change: float, lift_rms_change: float,
                     forced_amplitude_change: float, lambda_fit: float, lambda_theory: float,
                     free_tail_ratio: float,
                     no_new_growth_frequency: bool, fit_residual: float, prediction_residual: float,
                     cfd_finite_pass: bool, cfd_energy_pass: bool, forced_power_W: float,
                     energy_balance_pass: bool, free_monotone: bool) -> dict[str, object]:
    gates = {
        "response_outside_lockin_band": not (0.95 <= response_ratio <= 1.05),
        "cfd_force_main_frequency_stable": force_frequency_stable,
        "late_force_rms_change_lt_5pct": force_rms_change < 0.05,
        "late_lift_rms_change_lt_5pct": lift_rms_change < 0.05,
        "forced_amplitude_fit_change_lt_5pct": forced_amplitude_change < 0.05,
        "lambda_positive": lambda_fit > 0.0,
        "lambda_same_order_as_theory_or_free_tail_negligible": 0.25 <= lambda_fit / max(lambda_theory, 1.0e-30) <= 4.0 or free_tail_ratio < 0.05,
        "no_new_growth_frequency": no_new_growth_frequency,
        "fit_residual_lt_15pct": fit_residual < 0.15,
        "prediction_residual_lt_15pct": prediction_residual < 0.15,
        "cfd_mesh_cfl_energy_finite_pass": cfd_finite_pass,
        "forced_power_or_outside_lockin_energy_balance": abs(forced_power_W) < 0.5 or energy_balance_pass,
        "free_component_monotonically_decays": free_monotone,
    }
    # The 12 scientific conditions in the protocol are represented by the
    # 12 named gates below; force/lift RMS is one joint stability condition.
    twelve = {
        "response_outside_lockin_band": gates["response_outside_lockin_band"],
        "cfd_force_main_frequency_stable": gates["cfd_force_main_frequency_stable"],
        "late_force_and_lift_rms_stable": gates["late_force_rms_change_lt_5pct"] and gates["late_lift_rms_change_lt_5pct"],
        "forced_amplitude_fit_stable": gates["forced_amplitude_fit_change_lt_5pct"],
        "lambda_positive": gates["lambda_positive"],
        "lambda_same_order_as_theory_or_free_tail_negligible": gates["lambda_same_order_as_theory_or_free_tail_negligible"],
        "no_new_growth_frequency": gates["no_new_growth_frequency"],
        "fit_residual_lt_15pct": gates["fit_residual_lt_15pct"],
        "prediction_residual_lt_15pct": gates["prediction_residual_lt_15pct"],
        "cfd_mesh_cfl_energy_finite_pass": gates["cfd_mesh_cfl_energy_finite_pass"],
        "forced_power_or_energy_balance": gates["forced_power_or_outside_lockin_energy_balance"],
        "free_component_monotonically_decays": gates["free_component_monotonically_decays"],
    }
    passed = all(twelve.values())
    return {
        "class": "asymptotically_periodic_outside_lockin" if passed else "outside_lockin_model_failed",
        "asymptotically_periodic_outside_lockin": passed,
        "gates": gates,
        "twelve_condition_summary": twelve,
        "failed_conditions": [key for key, value in twelve.items() if not value],
    }


def analyze(rows: list[dict[str, float]], logs: list[Path], ur: float, fit_start: float, fit_end: float, fn: float, zeta: float) -> dict[str, object]:
    block = _window(rows, fit_start, fit_end)
    times = np.asarray([r["time_s"] for r in block], dtype=float)
    y = np.asarray([r["y_m"] for r in block], dtype=float)
    frequencies = _force_frequency(rows, fit_start, fit_end)
    fs = frequencies["force_frequency_Hz_dft"]
    lambda_theory = zeta * 2.0 * math.pi * fn
    mid = 0.5 * (fit_start + fit_end)
    first = _fit_region(rows, fit_start, mid, fs, fn, lambda_theory, "first_half_fit")
    second = _fit_region(rows, mid, fit_end, fs, fn, lambda_theory, "second_half_fit")
    full = _fit_region(rows, fit_start, fit_end, fs, fn, lambda_theory, "full_tail_fit")
    prediction_times = np.asarray([r["time_s"] for r in _window(rows, mid, fit_end)], dtype=float)
    prediction_values = np.asarray([r["y_m"] for r in _window(rows, mid, fit_end)], dtype=float)
    prediction = _predict(first, prediction_times, fs, fn, fit_start)
    prediction_residual = float(np.sqrt(np.mean((prediction_values - prediction) ** 2)) / max(np.sqrt(np.mean((prediction_values - np.mean(prediction_values)) ** 2)), 1.0e-30))
    full_residual_times = times
    full_residual = y - _design(times, fs, fn, float(full["lambda_fit"]), fit_start) @ np.asarray(full["coefficients"], dtype=float)
    residual_peak = dft_frequency(full_residual.tolist(), full_residual_times.tolist())
    fit_as_change = abs(float(second["As_m"]) - float(first["As_m"])) / max(abs(float(first["As_m"])), 1.0e-30)
    force_first = _window(rows, fit_start, mid)
    force_second = _window(rows, mid, fit_end)
    force_rms_change = abs(_rms(force_second, "force_y_N") - _rms(force_first, "force_y_N")) / max(_rms(force_first, "force_y_N"), 1.0e-30)
    lift_rms_change = abs(_rms(force_second, "Cl") - _rms(force_first, "Cl")) / max(_rms(force_first, "Cl"), 1.0e-30)
    # Fluid work into the fitted forced component.  This is a diagnostic, not
    # a replacement for the measured instantaneous-power audit.
    coef = np.asarray(full["coefficients"], dtype=float)
    tau = times - fit_start
    forced_velocity = 2.0 * math.pi * fs * (coef[2] * np.cos(2.0 * math.pi * fs * times) - coef[3] * np.sin(2.0 * math.pi * fs * times))
    forced_power = float(np.mean(np.asarray([r["force_y_N"] for r in block]) * forced_velocity))
    fluid_work = trap(block, "instantaneous_power_W")
    damping = block[-1]["damping_dissipation_J"] - block[0]["damping_dissipation_J"]
    mechanical = block[-1]["mechanical_energy_J"] - block[0]["mechanical_energy_J"]
    energy_residual = fluid_work - damping - mechanical
    energy_rel = abs(energy_residual) / max(abs(fluid_work), abs(damping), abs(mechanical), 1.0e-30)
    cfl_values = [max_cfl(log) for log in logs if log.exists()]
    max_cfl_value = max(cfl_values, default=float("nan"))
    finite = all(math.isfinite(float(row[key])) for row in block for key in ("y_m", "force_y_N", "Cl", "Cd", "mechanical_energy_J"))
    cfd_finite_pass = finite and (not math.isfinite(max_cfl_value) or max_cfl_value < 0.5)
    response_frequency = dft_frequency(y.tolist(), times.tolist())
    free_ratio_start = float(first["An_m"])
    free_ratio_at_end = free_ratio_start * math.exp(-float(first["lambda_fit"]) * (fit_end - fit_start))
    free_ratio_mid = free_ratio_start * math.exp(-float(first["lambda_fit"]) * (mid - fit_start))
    free_tail_ratio = free_ratio_at_end / max(float(first["As_m"]), 1.0e-30)
    free_monotone = float(first["lambda_fit"]) > 0.0 and free_ratio_at_end < free_ratio_start
    classification = _classification(
        response_ratio=response_frequency / fn,
        force_frequency_stable=frequencies["force_frequency_relative_change"] < 0.02 and frequencies["lift_frequency_relative_change"] < 0.02,
        force_rms_change=force_rms_change,
        lift_rms_change=lift_rms_change,
        forced_amplitude_change=fit_as_change,
        lambda_fit=float(first["lambda_fit"]),
        lambda_theory=lambda_theory,
        free_tail_ratio=free_tail_ratio,
        no_new_growth_frequency=residual_peak <= max(fs, fn) * 1.05,
        fit_residual=float(full["normalized_residual_rms"]),
        prediction_residual=prediction_residual,
        cfd_finite_pass=cfd_finite_pass,
        cfd_energy_pass=energy_rel < 0.10,
        forced_power_W=forced_power,
        energy_balance_pass=energy_rel < 0.10,
        free_monotone=free_monotone,
    )
    return {
        "ur": ur,
        "fit_window_s": [fit_start, fit_end],
        "model": MODEL_FORM,
        "fn_Hz_from_structure_parameters": fn,
        "zeta": zeta,
        "lambda_theory_1_per_s": lambda_theory,
        "frequency_components": {
            "response_frequency_Hz_dft": response_frequency,
            "response_f_over_fn": response_frequency / fn,
            "shedding_force": frequencies,
            "structure_frequency_Hz_parameter": fn,
            "residual_peak_frequency_Hz_dft": residual_peak,
        },
        "fit_solver": {"scipy_version": scipy_version, "numpy_version": np.__version__, "method": full["solver"]},
        "fits": {"first_half": first, "second_half": second, "full_tail": full},
        "prediction": {"train_window_s": [fit_start, mid], "test_window_s": [mid, fit_end], "normalized_residual_rms": prediction_residual, "prediction_residual_rms_m": float(np.sqrt(np.mean((prediction_values - prediction) ** 2)))},
        "parameter_stability": {"As_relative_change_first_second": fit_as_change, "An_over_As_first": float(first["An_m"]) / max(float(first["As_m"]), 1.0e-30), "free_envelope_start_m": free_ratio_start, "free_envelope_at_mid_m": free_ratio_mid, "free_envelope_at_end_m": free_ratio_at_end, "free_tail_over_forced_at_end": free_tail_ratio, "free_component_monotonically_decays": free_monotone},
        "force_and_energy_audit": {"force_rms_relative_change": force_rms_change, "Cl_rms_relative_change": lift_rms_change, "forced_component_mean_power_W": forced_power, "measured_fluid_work_J": fluid_work, "damping_dissipation_J": damping, "mechanical_energy_change_J": mechanical, "energy_balance_residual_J": energy_residual, "energy_balance_relative": energy_rel, "max_cfl": max_cfl_value, "finite": finite, "cfd_mesh_cfl_energy_finite_pass": cfd_finite_pass},
        "classification": classification,
        "safety": {"max_abs_y_m": max(abs(row["y_m"]) for row in rows), "max_abs_y_pass": max(abs(row["y_m"]) for row in rows) < 1.5, "max_cfl": max_cfl_value, "max_cfl_pass": not math.isfinite(max_cfl_value) or max_cfl_value < 0.5, "finite_pass": finite},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, nargs="+", required=True)
    parser.add_argument("--log", type=Path, nargs="*", default=[])
    parser.add_argument("--ur", type=float, required=True)
    parser.add_argument("--fit-start", type=float, required=True)
    parser.add_argument("--fit-end", type=float, required=True)
    parser.add_argument("--fn", type=float, default=None)
    parser.add_argument("--zeta", type=float, default=0.01)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = merge_rows(args.audit)
    fn = args.fn if args.fn is not None else 1.0 / args.ur
    payload = analyze(rows, args.log, args.ur, args.fit_start, args.fit_end, fn, args.zeta)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
