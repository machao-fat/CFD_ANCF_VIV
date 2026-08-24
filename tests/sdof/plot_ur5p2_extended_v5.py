"""Generate the required Ur=5.2 frequency, envelope, energy, spectrum and hysteresis figures."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from analyze_campaign import zero_crossing_frequency
from analyze_long_sdof import merge_rows, metrics, trap, window


plt.rcParams.update({"font.family": "Arial", "font.size": 7, "svg.fonttype": "none", "pdf.fonttype": 42})


def export(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path.with_suffix(".png"), dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".tiff"), dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def style(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, color="#D9DDE3", linewidth=0.45, alpha=0.7)
    ax.tick_params(labelsize=7, width=0.6, length=3)


def spectrum(values: np.ndarray, dt: float) -> tuple[np.ndarray, np.ndarray]:
    x = values - np.polyval(np.polyfit(np.arange(values.size), values, 1), np.arange(values.size))
    amp = np.abs(np.fft.rfft(x))
    freq = np.fft.rfftfreq(values.size, dt)
    return freq, amp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, nargs="+", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    rows = merge_rows(args.audit)
    out = args.output_dir
    w1 = window(rows, 60.0, 86.0)
    w2 = window(rows, 86.0, 112.0)
    dt = float(np.median(np.diff([row["time_s"] for row in w1])))

    frequency_rows = []
    for label, selected in (("60-86 s", w1), ("86-112 s", w2)):
        y = [row["y_m"] for row in selected]
        fy = [row["force_y_N"] for row in selected]
        base = metrics(rows, float(selected[0]["time_s"]), float(selected[-1]["time_s"]), 5.2, include_spectrum=True)
        dft_y = float(base["response_frequency_Hz_dft"])
        dft_f = float(base["lift_frequency_Hz_dft"])
        z_y = zero_crossing_frequency(y, [row["time_s"] for row in selected])
        z_f = zero_crossing_frequency(fy, [row["time_s"] for row in selected])
        frequency_rows.extend([
            {"window": label, "signal": "displacement", "frequency_Hz": dft_y, "method": "DFT_primary"},
            {"window": label, "signal": "lift", "frequency_Hz": dft_f, "method": "DFT_primary"},
            {"window": label, "signal": "displacement", "frequency_Hz": z_y, "method": "corrected_zero_crossing_diagnostic"},
            {"window": label, "signal": "lift", "frequency_Hz": z_f, "method": "corrected_zero_crossing_diagnostic"},
        ])
    table = {
        "fn_Hz": 0.1923076923076923,
        "legacy_v3_absolute_frequency_status": "obsolete doubled zero-crossing result",
        "rows": frequency_rows,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "frequency_comparison_v5.json").write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
    with (out / "frequency_comparison_v5.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["window", "signal", "frequency_Hz", "method"])
        writer.writeheader(); writer.writerows(frequency_rows)

    # Corrected frequency table, with the old doubled value retained only for audit.
    fig, ax = plt.subplots(figsize=(7.2, 3.0), constrained_layout=True)
    labels = ["60-86", "86-112"]
    dft = [next(x["frequency_Hz"] for x in frequency_rows if x["window"].startswith(label) and x["signal"] == "displacement" and x["method"] == "DFT_primary") for label in ("60-86", "86-112")]
    zero = [next(x["frequency_Hz"] for x in frequency_rows if x["window"].startswith(label) and x["signal"] == "displacement" and x["method"].startswith("corrected")) for label in ("60-86", "86-112")]
    ax.plot(labels, dft, "o-", color="#2166AC", label="DFT primary")
    ax.plot(labels, zero, "s--", color="#4D4D4D", label="corrected zero crossing")
    ax.plot(labels, [2.0 * value for value in zero], "x:", color="#B2182B", label="legacy doubled value (obsolete)")
    ax.axhline(table["fn_Hz"], color="#1B7837", ls="--", lw=0.8, label="fn")
    ax.set_ylabel("frequency (Hz)"); ax.set_xlabel("late five-cycle window"); ax.set_title("Ur=5.2 frequency correction audit")
    style(ax); ax.legend(frameon=False, fontsize=6)
    export(fig, out / "ur5p2_frequency_comparison_v5")

    # Per-cycle amplitude and energy audit.
    cycles = []
    start = 60.0
    while start < 112.0 - 1e-9:
        end = start + 5.2
        selected = window(rows, start, end)
        y = [row["y_m"] for row in selected]
        work = trap(selected, "instantaneous_power_W")
        damping = selected[-1]["damping_dissipation_J"] - selected[0]["damping_dissipation_J"]
        mechanical = selected[-1]["mechanical_energy_J"] - selected[0]["mechanical_energy_J"]
        cycles.append({"start_s": start, "end_s": end, "positive_peak_y_m": max(y), "negative_peak_y_m": min(y), "half_amplitude_y_m": 0.5 * (max(y) - min(y)), "fluid_work_J": work, "damping_dissipation_J": damping, "mechanical_energy_change_J": mechanical})
        start = end
    (out / "per_cycle_envelope_energy_v5.json").write_text(json.dumps(cycles, indent=2) + "\n", encoding="utf-8")
    x = np.arange(1, len(cycles) + 1)
    fig, axes = plt.subplots(2, 1, figsize=(6.5, 4.8), sharex=True, constrained_layout=True)
    axes[0].plot(x, [c["positive_peak_y_m"] for c in cycles], "o-", label="positive peak", color="#B2182B")
    axes[0].plot(x, [c["negative_peak_y_m"] for c in cycles], "o-", label="negative peak", color="#2166AC")
    axes[0].plot(x, [c["half_amplitude_y_m"] for c in cycles], "s--", label="half amplitude", color="#4D4D4D")
    axes[0].set_ylabel("displacement (m)"); axes[0].legend(frameon=False, ncol=3, fontsize=6); axes[0].set_title("Ur=5.2 per-cycle amplitude envelope")
    for key, label, color in (("fluid_work_J", "fluid work", "#2166AC"), ("damping_dissipation_J", "damping", "#B2182B"), ("mechanical_energy_change_J", "mechanical delta E", "#4D4D4D")):
        axes[1].plot(x, [c[key] for c in cycles], "o-", label=label, color=color)
    axes[1].set_xlabel("cycle index (60--112 s)"); axes[1].set_ylabel("cycle energy (J)"); axes[1].legend(frameon=False, ncol=3, fontsize=6)
    for ax in axes: style(ax)
    export(fig, out / "ur5p2_amplitude_energy_envelope_v5")

    # Last two five-cycle windows: time histories and DFT spectra.
    fig, axes = plt.subplots(2, 2, figsize=(7.3, 4.5), constrained_layout=True)
    for col, (label, selected) in enumerate((("60--86 s", w1), ("86--112 s", w2))):
        time = np.asarray([row["time_s"] for row in selected])
        y = np.asarray([row["y_m"] for row in selected]); fy = np.asarray([row["force_y_N"] for row in selected])
        axes[0, col].plot(time, y, color="#2166AC", lw=0.7); axes[0, col].set_title(label); axes[0, col].set_ylabel("y (m)")
        fy_f, fy_a = spectrum(fy, dt); y_f, y_a = spectrum(y, dt)
        axes[1, col].plot(y_f, y_a / max(y_a.max(), 1e-30), color="#2166AC", lw=0.8, label="displacement")
        axes[1, col].plot(fy_f, fy_a / max(fy_a.max(), 1e-30), color="#B2182B", lw=0.8, label="lift")
        axes[1, col].set_xlim(0.01, 0.5); axes[1, col].set_xlabel("frequency (Hz)"); axes[1, col].set_ylabel("normalized spectrum")
        axes[1, col].legend(frameon=False, fontsize=6)
    for ax in axes.flat: style(ax)
    fig.suptitle("Ur=5.2 late-window histories and spectra", fontsize=9)
    export(fig, out / "ur5p2_late_window_timeseries_spectra_v5")

    # Displacement--lift hysteresis loop.
    fig, ax = plt.subplots(figsize=(7.2, 3.5), constrained_layout=True)
    ax.plot([row["y_m"] for row in w1], [row["force_y_N"] for row in w1], color="#2166AC", lw=0.65, label="60--86 s")
    ax.plot([row["y_m"] for row in w2], [row["force_y_N"] for row in w2], color="#B2182B", lw=0.65, label="86--112 s")
    ax.set_xlabel("displacement y (m)"); ax.set_ylabel("lift force Fy (N)"); ax.set_title("Ur=5.2 displacement--lift hysteresis")
    style(ax); ax.legend(frameon=False, fontsize=6)
    export(fig, out / "ur5p2_displacement_lift_hysteresis_v5")
    print(json.dumps({"output_dir": str(out), "cycles": len(cycles), "windows": ["60-86 s", "86-112 s"], "formats": ["png", "svg", "pdf", "tiff"]}, indent=2))


if __name__ == "__main__":
    main()
