#!/usr/bin/env python3
"""Post-process prescribed-motion force/velocity phase and power."""

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
    time = np.array([float(row["time_s"]) for row in rows])
    drag = np.array([float(row["force_x_N"]) for row in rows])
    force = np.array([float(row["force_y_N"]) for row in rows])
    return time, drag, force


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loads", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--amplitude", type=float, required=True)
    parser.add_argument("--frequency", type=float, required=True)
    parser.add_argument("--rho", type=float, default=1000.0)
    parser.add_argument("--u-inf", type=float, default=1.0)
    parser.add_argument("--D", type=float, default=1.0)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    time, drag, force = read_loads(args.loads)
    omega = 2.0 * math.pi * args.frequency
    y = args.amplitude * np.sin(omega * time)
    vy = args.amplitude * omega * np.cos(omega * time)
    mask = time >= 0.5 * time[-1]
    t = time[mask]
    dx = drag[mask]
    f = force[mask]
    yy = y[mask]
    vv = vy[mask]
    # F = a*sin(wt) + b*cos(wt) + c.  The velocity is cos(wt).
    design = np.column_stack((np.sin(omega * t), np.cos(omega * t), np.ones_like(t)))
    coeff, *_ = np.linalg.lstsq(design, f, rcond=None)
    force_phase_vs_y = math.degrees(math.atan2(coeff[1], coeff[0]))
    force_phase_vs_v = force_phase_vs_y - 90.0
    average_power = float(np.mean(f * vv))
    cycle_energy = average_power / args.frequency
    reference_force = 0.5 * args.rho * args.u_inf**2 * args.D
    cd_mean = float(np.mean(dx) / reference_force)
    cy_mean = float(np.mean(f) / reference_force)
    lift_amplitude = float(0.5 * (np.max(f) - np.min(f)))
    spectrum = np.abs(np.fft.rfft((f - np.mean(f)) * np.hanning(len(f))))
    frequencies = np.fft.rfftfreq(len(f), np.median(np.diff(t)))
    if len(spectrum) > 1:
        dominant_frequency = float(frequencies[1 + int(np.argmax(spectrum[1:]))])
    else:
        dominant_frequency = float("nan")
    with (args.output / "force_spectrum.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["frequency_Hz", "amplitude"])
        writer.writerows(zip(frequencies, spectrum))
    np.savetxt(
        args.output / "hysteresis.csv",
        np.column_stack((t, yy, f, vv, f * vv)),
        delimiter=",",
        header="time_s,displacement_y_m,force_y_N,velocity_y_mps,power_W",
        comments="",
    )
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 4.6))
    axes[0, 0].plot(t, f, lw=0.7, color="#2a6fbb")
    axes[0, 0].set(xlabel="time [s]", ylabel="Fy [N]", title="steady window")
    axes[0, 1].plot(yy, f, lw=0.7)
    axes[0, 1].set(xlabel="y [m]", ylabel="Fy [N]")
    axes[1, 0].plot(t, f * vv, lw=0.7)
    axes[1, 0].axhline(0, color="k", lw=0.5)
    axes[1, 0].set(xlabel="time [s]", ylabel="P=Fy*vy [W]")
    axes[1, 1].plot(frequencies, spectrum, lw=0.8)
    axes[1, 1].axvline(args.frequency, color="r", ls="--", lw=0.8)
    axes[1, 1].set(xlabel="frequency [Hz]", ylabel="amplitude")
    axes[1, 1].set_xlim(0.0, max(0.5, 4.0 * args.frequency))
    for axis, label in zip(axes.flat, "abcd"):
        axis.text(-0.12, 1.04, label, transform=axis.transAxes, fontweight="bold")
    fig.tight_layout()
    figure_stem = args.output / "prescribed_motion_summary"
    fig.savefig(figure_stem.with_suffix(".svg"), bbox_inches="tight")
    fig.savefig(figure_stem.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(figure_stem.with_suffix(".tiff"), dpi=600, bbox_inches="tight")
    fig.savefig(figure_stem.with_suffix(".png"), dpi=600, bbox_inches="tight")
    plt.close(fig)
    summary = {
        "window_start_s": float(t[0]),
        "window_end_s": float(t[-1]),
        "input_frequency_Hz": args.frequency,
        "dominant_force_frequency_Hz": dominant_frequency,
        "force_phase_vs_displacement_deg": force_phase_vs_y,
        "force_phase_vs_velocity_deg": force_phase_vs_v,
        "average_power_W": average_power,
        "cycle_energy_J": cycle_energy,
        "mean_Cd_from_force_x": cd_mean,
        "mean_Cy_from_force_y": cy_mean,
        "lift_half_amplitude_N": lift_amplitude,
        "lift_half_amplitude_Cy": lift_amplitude / reference_force,
        "max_abs_force_N": float(np.max(np.abs(f))),
        "finite": bool(np.all(np.isfinite(np.column_stack((t, f, yy, vv))))),
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
