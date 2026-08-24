#!/usr/bin/env python3
"""Whole-cycle quantitative analysis for prescribed-motion cylinder loads.

This is an audit-side post-processor. It consumes the already validated load
CSV contract and does not alter the CSV reader/writer or ANCF production code.
The window is aligned to complete periods of the known input frequency.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 8,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "axes.linewidth": 0.8,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
    }
)

from csv_contract import validate_load_csv


def read_loads(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = validate_load_csv(path)
    time = np.asarray([float(row["time_s"]) for row in rows], dtype=float)
    fx = np.asarray([float(row["force_x_N"]) for row in rows], dtype=float)
    fy = np.asarray([float(row["force_y_N"]) for row in rows], dtype=float)
    if len(time) < 20 or not np.all(np.isfinite(np.column_stack((time, fx, fy)))):
        raise ValueError("load CSV is too short or contains NaN/Inf")
    dt = np.diff(time)
    if np.any(dt <= 0) or not np.allclose(dt, np.median(dt), rtol=1e-8, atol=1e-12):
        raise ValueError("load CSV time stamps must be strictly increasing and uniform")
    return time, fx, fy


def trapz(y: np.ndarray, x: np.ndarray) -> float:
    if hasattr(np, "trapezoid"):
        return float(np.trapezoid(y, x))
    return float(np.trapz(y, x))


def harmonic_fit(t: np.ndarray, signal: np.ndarray, omega: float) -> dict[str, float]:
    design = np.column_stack((np.sin(omega * t), np.cos(omega * t), np.ones_like(t)))
    coeff, *_ = np.linalg.lstsq(design, signal, rcond=None)
    amp = float(math.hypot(coeff[0], coeff[1]))
    phase = float(math.degrees(math.atan2(coeff[1], coeff[0])))
    return {
        "sin_coefficient": float(coeff[0]),
        "cos_coefficient": float(coeff[1]),
        "mean": float(coeff[2]),
        "amplitude": amp,
        "phase_vs_sine_deg": phase,
    }


def demod(signal: np.ndarray, t: np.ndarray, omega: float) -> complex:
    centered = signal - np.mean(signal)
    return complex(np.mean(centered * np.exp(-1j * omega * t)))


def phase_deg(numerator: complex, denominator: complex) -> float:
    ratio = numerator / denominator
    return float(math.degrees(math.atan2(ratio.imag, ratio.real)))


def cycle_slice(time: np.ndarray, start: float, end: float) -> np.ndarray:
    tol = max(1e-10, 1e-7 * max(1.0, abs(end)))
    return np.flatnonzero((time >= start - tol) & (time <= end + tol))


def write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loads", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--amplitude", type=float, required=True)
    parser.add_argument("--frequency", type=float, required=True)
    parser.add_argument("--transient-end", type=float, default=20.0)
    parser.add_argument("--rho", type=float, default=1000.0)
    parser.add_argument("--u-inf", type=float, default=1.0)
    parser.add_argument("--D", type=float, default=1.0)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    time, fx, fy = read_loads(args.loads)
    omega = 2.0 * math.pi * args.frequency
    period = 1.0 / args.frequency
    y = args.amplitude * np.sin(omega * time)
    vy = args.amplitude * omega * np.cos(omega * time)

    # Align the statistics to the prescribed input phase and retain only whole
    # cycles after the requested transient cut.
    first_start = math.ceil((args.transient_end - 1e-10) / period) * period
    last_end = math.floor((time[-1] + 1e-10) / period) * period
    n_cycles = int(math.floor((last_end - first_start) / period + 1e-9))
    if n_cycles < 1:
        raise ValueError("the run does not contain one complete post-transient cycle")
    window_start = first_start
    window_end = first_start + n_cycles * period
    window_idx = cycle_slice(time, window_start, window_end)
    if len(window_idx) < 20:
        raise ValueError("whole-cycle window contains too few samples")

    t = time[window_idx]
    dx = fx[window_idx]
    f = fy[window_idx]
    yy = y[window_idx]
    vv = vy[window_idx]
    dt = float(np.median(np.diff(time)))
    reference_force = 0.5 * args.rho * args.u_inf**2 * args.D
    force_fit = harmonic_fit(t, f, omega)
    fx_fit = harmonic_fit(t, dx, omega)
    zf = demod(f, t, omega)
    zy = demod(yy, t, omega)
    zv = demod(vv, t, omega)

    cycle_rows: list[list[object]] = []
    for cycle in range(n_cycles):
        start = window_start + cycle * period
        end = start + period
        idx = cycle_slice(time, start, end)
        tc = time[idx]
        fc = fy[idx]
        xc = fx[idx]
        yc = y[idx]
        vc = vy[idx]
        fit_c = harmonic_fit(tc, fc, omega)
        zfc = demod(fc, tc, omega)
        zyc = demod(yc, tc, omega)
        zvc = demod(vc, tc, omega)
        work = trapz(fc * vc, tc)
        cycle_rows.append(
            [
                cycle + 1,
                start,
                end,
                float(np.mean(xc) / reference_force),
                float(fit_c["amplitude"] / reference_force),
                fit_c["phase_vs_sine_deg"],
                phase_deg(zfc, zyc),
                phase_deg(zfc, zvc),
                work,
                work / period,
                float(np.max(np.abs(fc))),
                len(idx),
            ]
        )

    cycle_header = [
        "cycle",
        "start_s",
        "end_s",
        "Cd_mean",
        "Cy_half_amplitude",
        "harmonic_phase_vs_displacement_deg",
        "demod_phase_vs_displacement_deg",
        "demod_phase_vs_velocity_deg",
        "fluid_work_J",
        "mean_power_W",
        "max_abs_Fy_N",
        "n_samples",
    ]
    write_csv(args.output / "cycle_metrics.csv", cycle_header, cycle_rows)

    centered = f - np.mean(f)
    window = np.hanning(len(centered))
    spectrum = np.abs(np.fft.rfft(centered * window))
    frequencies = np.fft.rfftfreq(len(centered), dt)
    nearest = int(np.argmin(np.abs(frequencies - args.frequency)))
    nonzero = np.arange(1, len(spectrum))
    dominant_index = int(nonzero[np.argmax(spectrum[nonzero])]) if len(nonzero) else 0
    force_fft = np.fft.rfft(centered * window)
    y_fft = np.fft.rfft((yy - np.mean(yy)) * window)
    v_fft = np.fft.rfft((vv - np.mean(vv)) * window)
    cross_fy = force_fft[nearest] * np.conj(y_fft[nearest])
    cross_fv = force_fft[nearest] * np.conj(v_fft[nearest])
    write_csv(
        args.output / "force_spectrum.csv",
        ["frequency_Hz", "amplitude", "known_frequency_marker"],
        [
            [float(freq), float(amp), int(i == nearest)]
            for i, (freq, amp) in enumerate(zip(frequencies, spectrum))
        ],
    )
    np.savetxt(
        args.output / "whole_cycle_hysteresis.csv",
        np.column_stack((t, yy, f, vv, f * vv)),
        delimiter=",",
        header="time_s,displacement_y_m,force_y_N,velocity_y_mps,power_W",
        comments="",
    )

    cycle_array = np.asarray(cycle_rows, dtype=float)
    work_values = cycle_array[:, 8]
    power_values = cycle_array[:, 9]
    amp_values = cycle_array[:, 4]
    phase_values = cycle_array[:, 6]
    relative_work_change = (
        float(np.max(np.abs(np.diff(work_values))) / max(np.max(np.abs(work_values)), 1e-30))
        if len(work_values) > 1
        else 0.0
    )
    relative_amp_change = (
        float(np.max(np.abs(np.diff(amp_values))) / max(np.max(np.abs(amp_values)), 1e-30))
        if len(amp_values) > 1
        else 0.0
    )
    summary = {
        "loads": str(args.loads),
        "input_amplitude_m": args.amplitude,
        "input_frequency_Hz": args.frequency,
        "period_s": period,
        "transient_cut_requested_s": args.transient_end,
        "whole_cycle_window_start_s": float(window_start),
        "whole_cycle_window_end_s": float(window_end),
        "whole_cycle_count": n_cycles,
        "dt_s": dt,
        "n_samples": int(len(window_idx)),
        "known_frequency_harmonic_force_amplitude_N": force_fit["amplitude"],
        "known_frequency_harmonic_force_amplitude_Cy": force_fit["amplitude"] / reference_force,
        "known_frequency_harmonic_drag_mean_Cd": fx_fit["mean"] / reference_force,
        "known_frequency_harmonic_phase_vs_displacement_deg": force_fit["phase_vs_sine_deg"],
        "known_frequency_harmonic_phase_vs_velocity_deg": force_fit["phase_vs_sine_deg"] - 90.0,
        "complex_demod_phase_vs_displacement_deg": phase_deg(zf, zy),
        "complex_demod_phase_vs_velocity_deg": phase_deg(zf, zv),
        "cross_spectrum_phase_vs_displacement_deg": float(math.degrees(math.atan2(cross_fy.imag, cross_fy.real))),
        "cross_spectrum_phase_vs_velocity_deg": float(math.degrees(math.atan2(cross_fv.imag, cross_fv.real))),
        "dominant_fft_frequency_Hz": float(frequencies[dominant_index]),
        "mean_Cd": float(np.mean(dx) / reference_force),
        "mean_Cy": float(np.mean(f) / reference_force),
        "whole_window_mean_power_W": float(np.mean(f * vv)),
        "whole_window_fluid_work_J": trapz(f * vv, t),
        "mean_cycle_work_J": float(np.mean(work_values)),
        "mean_cycle_power_W": float(np.mean(power_values)),
        "cycle_work_std_J": float(np.std(work_values, ddof=1)) if len(work_values) > 1 else 0.0,
        "cycle_amplitude_std_Cy": float(np.std(amp_values, ddof=1)) if len(amp_values) > 1 else 0.0,
        "cycle_phase_std_deg": float(np.std(phase_values, ddof=1)) if len(phase_values) > 1 else 0.0,
        "max_adjacent_relative_cycle_work_change": relative_work_change,
        "max_adjacent_relative_cycle_amplitude_change": relative_amp_change,
        "finite": bool(np.all(np.isfinite(np.column_stack((t, f, yy, vv, f * vv))))),
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    fig, axes = plt.subplots(2, 3, figsize=(7.2, 4.7))
    axes[0, 0].plot(t, f, lw=0.55, color="#2a6fbb")
    axes[0, 0].set(xlabel="time [s]", ylabel="Fy [N]", title="whole-cycle window")
    axes[0, 1].plot(frequencies, spectrum, lw=0.7)
    axes[0, 1].axvline(args.frequency, color="#c43c39", ls="--", lw=0.8)
    axes[0, 1].set(xlabel="frequency [Hz]", ylabel="FFT amplitude")
    axes[0, 1].set_xlim(0, max(0.5, 4 * args.frequency))
    axes[0, 2].plot(yy, f, lw=0.55)
    axes[0, 2].set(xlabel="y [m]", ylabel="Fy [N]")
    axes[1, 0].plot(cycle_array[:, 0], work_values, "o-", ms=2, lw=0.7)
    axes[1, 0].axhline(np.mean(work_values), color="k", lw=0.5)
    axes[1, 0].set(xlabel="cycle", ylabel="fluid work [J]")
    axes[1, 1].plot(cycle_array[:, 0], amp_values, "o-", ms=2, lw=0.7)
    axes[1, 1].set(xlabel="cycle", ylabel="Cy half amplitude")
    axes[1, 2].plot(cycle_array[:, 0], phase_values, "o-", ms=2, lw=0.7)
    axes[1, 2].set(xlabel="cycle", ylabel="phase Fy-y [deg]")
    for axis, label in zip(axes.flat, "abcdef"):
        axis.text(-0.14, 1.05, label, transform=axis.transAxes, fontweight="bold")
    fig.tight_layout()
    stem = args.output / "extended_forced_summary"
    fig.savefig(stem.with_suffix(".svg"), bbox_inches="tight")
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(stem.with_suffix(".tiff"), dpi=600, bbox_inches="tight")
    fig.savefig(stem.with_suffix(".png"), dpi=600, bbox_inches="tight")
    plt.close(fig)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
