#!/usr/bin/env python3
"""Convert OpenFOAM fixed-cylinder outputs to reproducible CSV/summary files."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import find_peaks


FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def numeric_tokens(line: str) -> list[float]:
    return [float(value) for value in re.findall(FLOAT, line)]


def vector_groups(line: str) -> list[list[float]]:
    groups = []
    for group in re.findall(r"\(([^()]*)\)", line):
        values = numeric_tokens(group)
        if len(values) == 3:
            groups.append(values)
    return groups


def read_force_file(path: Path) -> tuple[np.ndarray, list[str]]:
    rows = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        values = numeric_tokens(line)
        groups = vector_groups(line)
        if not values or len(groups) < 2:
            continue
        # forces.dat is written as time, pressure/viscous vectors and
        # pressure/viscous moments.  Retain both components and their totals.
        pressure = groups[0]
        viscous = groups[1]
        pressure_moment = groups[2] if len(groups) >= 3 else [0.0, 0.0, 0.0]
        viscous_moment = groups[3] if len(groups) >= 4 else [0.0, 0.0, 0.0]
        total_force = [pressure[i] + viscous[i] for i in range(3)]
        total_moment = [pressure_moment[i] + viscous_moment[i] for i in range(3)]
        rows.append([values[0], *pressure, *viscous, *total_force, *total_moment])
    if not rows:
        raise RuntimeError(f"No force rows parsed from {path}")
    return np.asarray(rows, dtype=float), [
        "time_s",
        "pressure_force_x_N",
        "pressure_force_y_N",
        "pressure_force_z_N",
        "viscous_force_x_N",
        "viscous_force_y_N",
        "viscous_force_z_N",
        "total_force_x_N",
        "total_force_y_N",
        "total_force_z_N",
        "moment_x_Nm",
        "moment_y_Nm",
        "moment_z_Nm",
    ]


def read_coeff_file(path: Path) -> tuple[np.ndarray, list[str]]:
    rows = []
    names = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if "Time" in line:
                names = [item for item in line.lstrip("#").split()]
            continue
        values = numeric_tokens(line)
        if len(values) < 4:
            continue
        # OpenFOAM 10 writes: Time, Cm, Cd, Cl, Cl(f), Cl(r).  Reorder to the
        # stable project contract: time, Cd, Cl, Cmz.
        if names:
            index = {name: i for i, name in enumerate(names)}
            if all(name in index for name in ("Time", "Cm", "Cd", "Cl")):
                rows.append([values[index["Time"]], values[index["Cd"]], values[index["Cl"]], values[index["Cm"]]])
                continue
        rows.append(values[:4])
    if not rows:
        raise RuntimeError(f"No force-coefficient rows parsed from {path}")
    if not names:
        names = ["Time", "Cm", "Cd", "Cl"]
    return np.asarray(rows, dtype=float), ["time_s", "Cd", "Cl", "Cmz"]


def write_csv(path: Path, header: list[str], data: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(data.tolist())


def detect_dominant_frequency(time: np.ndarray, signal: np.ndarray) -> tuple[float, float]:
    if len(time) < 8:
        return float("nan"), float("nan")
    dt = float(np.median(np.diff(time)))
    centered = signal - np.mean(signal)
    # Peak-to-peak period is much better resolved than a short-window FFT for
    # the present Re=100 case (the shedding period is several D/U).
    peak_distance = max(1, int(0.5 / dt))
    peak_prominence = max(0.02, 0.25 * float(np.std(centered)))
    peaks, properties = find_peaks(
        centered, distance=peak_distance, prominence=peak_prominence
    )
    if len(peaks) >= 2:
        periods = np.diff(time[peaks])
        frequency = 1.0 / float(np.median(periods))
        return frequency, float(np.max(properties["prominences"]))

    windowed = centered * np.hanning(len(centered))
    spectrum = np.abs(np.fft.rfft(windowed))
    frequencies = np.fft.rfftfreq(len(centered), dt)
    spectrum[0] = 0.0
    index = int(np.argmax(spectrum))
    return float(frequencies[index]), float(spectrum[index])


def parse_log(path: Path) -> tuple[list[list[float]], list[list[float]]]:
    residuals = []
    cfl = []
    current_time = math.nan
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        time_match = re.search(r"^Time = (" + FLOAT + r")", raw)
        if time_match:
            current_time = float(time_match.group(1))
        residual_match = re.search(
            r"Solving for (\w+), Initial residual = (" + FLOAT + r"), Final residual = (" + FLOAT + r")",
            raw,
        )
        if residual_match and math.isfinite(current_time):
            residuals.append(
                [
                    current_time,
                    residual_match.group(1),
                    float(residual_match.group(2)),
                    float(residual_match.group(3)),
                ]
            )
        cfl_match = re.search(
            r"Courant Number mean: (" + FLOAT + r") max: (" + FLOAT + r")", raw
        )
        if cfl_match and math.isfinite(current_time):
            cfl.append([current_time, float(cfl_match.group(1)), float(cfl_match.group(2))])
    return residuals, cfl


def write_residual_csv(path: Path, rows: list[list[float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s", "field", "initial_residual", "final_residual"])
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    case = args.case.resolve()
    result = args.result.resolve()
    result.mkdir(parents=True, exist_ok=True)

    force_path = case / "postProcessing" / "cylinderForces" / "0" / "forces.dat"
    coeff_path = case / "postProcessing" / "cylinderForceCoeffs" / "0" / "forceCoeffs.dat"
    force_data, force_header = read_force_file(force_path)
    coeff_data, coeff_header = read_coeff_file(coeff_path)
    write_csv(result / "forces.csv", force_header, force_data)
    write_csv(result / "force_coeffs.csv", coeff_header, coeff_data)

    time = coeff_data[:, 0]
    cd = coeff_data[:, 1]
    cl = coeff_data[:, 2]
    window_start = 0.5 * float(time[-1])
    mask = time >= window_start
    freq, _ = detect_dominant_frequency(time[mask], cl[mask])
    summary = {
        "case": str(case),
        "solver": "icoFoam",
        "Re": 100.0,
        "D_m": 1.0,
        "U_inf_mps": 1.0,
        "rho_kgpm3": 1000.0,
        "nu_m2ps": 0.01,
        "unit_span_m": 1.0,
        "window_start_s": window_start,
        "window_end_s": float(time[-1]),
        "Cd_mean": float(np.mean(cd[mask])),
        "Cl_mean": float(np.mean(cl[mask])),
        "Cl_rms": float(np.sqrt(np.mean((cl[mask] - np.mean(cl[mask])) ** 2))),
        "Cl_half_peak_to_peak": float(0.5 * (np.max(cl[mask]) - np.min(cl[mask]))),
        "dominant_frequency_Hz": freq,
        "Strouhal": freq,
        "n_force_samples": int(len(force_data)),
        "n_coeff_samples": int(len(coeff_data)),
    }
    (result / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    residuals, cfl = parse_log(case / "log.icoFoam")
    write_residual_csv(result / "residuals.csv", residuals)
    with (result / "cfl.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_s", "mean_Courant", "max_Courant"])
        writer.writerows(cfl)

    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    axes[0].plot(time, cd, lw=0.8, label="Cd")
    axes[0].axvline(window_start, color="0.5", ls="--", lw=0.8)
    axes[0].set_ylabel("Cd")
    axes[0].legend()
    axes[1].plot(time, cl, lw=0.8, label="Cl")
    axes[1].axvline(window_start, color="0.5", ls="--", lw=0.8)
    axes[1].set_xlabel("time [s]")
    axes[1].set_ylabel("Cl")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(result / "force_history.png", dpi=180)
    plt.close(fig)

    frequencies = np.fft.rfftfreq(mask.sum(), np.median(np.diff(time[mask])))
    spectrum = np.abs(np.fft.rfft((cl[mask] - np.mean(cl[mask])) * np.hanning(mask.sum())))
    with (result / "lift_spectrum.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["frequency_Hz", "amplitude"])
        writer.writerows(zip(frequencies.tolist(), spectrum.tolist()))
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(frequencies, spectrum, lw=0.9)
    ax.set_xlim(0, max(0.5, min(1.0, frequencies[-1])))
    ax.set_xlabel("frequency [Hz]")
    ax.set_ylabel("windowed FFT amplitude")
    ax.set_title(f"Lift spectrum, dominant St={freq:.5f}")
    fig.tight_layout()
    fig.savefig(result / "lift_spectrum.png", dpi=180)
    plt.close(fig)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
