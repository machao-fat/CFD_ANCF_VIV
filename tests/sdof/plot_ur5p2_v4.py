from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams.update({
    "font.family": "Arial",
    "font.size": 7,
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
    "figure.dpi": 150,
})


def read_rows(path: Path) -> dict[str, np.ndarray]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    keys = ("time_s", "y_m", "force_y_N", "instantaneous_power_W", "damping_dissipation_J", "mechanical_energy_J")
    return {key: np.asarray([float(row[key]) for row in rows], dtype=float) for key in keys}


def style(ax: plt.Axes, *, xlabel: str | None = None, ylabel: str | None = None) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, color="#D9DDE3", linewidth=0.45, alpha=0.7)
    ax.tick_params(labelsize=7, width=0.6, length=3)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=8)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=8)


def save(fig: plt.Figure, out: Path, stem: str) -> None:
    fig.savefig(out / f"{stem}.svg", format="svg", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(out / f"{stem}.pdf", format="pdf", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(out / f"{stem}.png", format="png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(out / f"{stem}.tiff", format="tiff", dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def spectrum(t: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    dt = float(np.mean(np.diff(t)))
    x = x - np.polyval(np.polyfit(t, x, 1), t)
    f = np.fft.rfftfreq(x.size, dt)
    a = np.abs(np.fft.rfft(x)) / x.size * 2.0
    keep = (f >= 0.01) & (f <= 0.6)
    return f[keep], a[keep]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segments", type=Path, nargs="+", required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # The segments are non-overlapping except for synchronized restart rows.
    arrays = [read_rows(path) for path in args.segments]
    data = {key: np.concatenate([item[key] for item in arrays]) for key in arrays[0]}
    order = np.argsort(data["time_s"])
    data = {key: data[key][order] for key in data}
    keep = np.r_[True, np.diff(data["time_s"]) > 1.0e-12]
    data = {key: data[key][keep] for key in data}
    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    blocks = metrics["blocks_5p2s"]

    # Evidence chain: the envelope approaches a plateau, while the last
    # cycles satisfy the work/damping balance used by the report.
    fig, axes = plt.subplots(2, 1, figsize=(7.1, 5.2), sharex=True, constrained_layout=True)
    ends = np.asarray([item["end_s"] for item in blocks])
    rms = np.asarray([item["y_rms_m"] for item in blocks])
    half = np.asarray([item["half_amplitude_y_m"] for item in blocks])
    axes[0].plot(ends, rms, "o-", ms=2.7, lw=1.1, color="#2166AC", label="displacement RMS")
    axes[0].plot(ends, half, "o-", ms=2.7, lw=1.1, color="#B2182B", label="half amplitude")
    axes[0].axvspan(2, 60, color="#BDBDBD", alpha=0.13, label="startup / approach")
    axes[0].axvspan(60, 112, color="#67A9CF", alpha=0.08, label="late windows")
    axes[0].set_ylabel("Displacement (m)")
    axes[0].legend(frameon=False, fontsize=7, ncol=3, loc="upper left")
    style(axes[0])
    work = np.asarray([item["structure_work_J"] for item in blocks])
    damping = np.asarray([item["damping_dissipation_J"] for item in blocks])
    dmech = np.asarray([item["mechanical_energy_change_J"] for item in blocks])
    axes[1].plot(ends, work, "o-", ms=2.7, lw=1.1, color="#1B7837", label="fluid work")
    axes[1].plot(ends, damping, "o-", ms=2.7, lw=1.1, color="#762A83", label="damping dissipation")
    axes[1].plot(ends, dmech, "o-", ms=2.7, lw=1.1, color="#E08214", label="mechanical energy change")
    axes[1].axhline(0.0, color="#555555", lw=0.6)
    axes[1].set_ylabel("Per-block energy (J)")
    axes[1].set_xlabel("Time (s)")
    axes[1].legend(frameon=False, fontsize=7, ncol=3, loc="upper right")
    style(axes[1])
    fig.suptitle("Ur=5.2: amplitude envelope and energy audit", fontsize=9)
    save(fig, args.output, "ur5p2_v4_envelope_energy")

    fig, axes = plt.subplots(2, 2, figsize=(7.1, 5.4), constrained_layout=True)
    for start, end, color, label in ((60.0, 86.0, "#2166AC", "60-86 s"), (86.0, 112.0, "#B2182B", "86-112 s")):
        idx = (data["time_s"] >= start - 1.0e-12) & (data["time_s"] <= end + 1.0e-12)
        t = data["time_s"][idx]
        y = data["y_m"][idx]
        fy = data["force_y_N"][idx]
        f_y, a_y = spectrum(t, y)
        f_f, a_f = spectrum(t, fy)
        axes[0, 0].plot(t, y, color=color, lw=0.65, label=label)
        axes[0, 1].plot(f_y, a_y, color=color, lw=1.0, label=f"y {label}")
        axes[0, 1].plot(f_f, a_f, color=color, lw=0.8, ls="--", label=f"Fy {label}")
        axes[1, 0].plot(y, fy, color=color, lw=0.6, alpha=0.9, label=label)
    axes[0, 0].set_ylabel("y (m)")
    axes[0, 0].set_xlabel("Time (s)")
    axes[0, 0].legend(frameon=False, fontsize=7)
    axes[0, 1].axvline(metrics["fn_Hz"], color="#555555", lw=0.7, ls=":", label="fn")
    axes[0, 1].set_xlim(0.05, 0.4)
    axes[0, 1].set_xlabel("Frequency (Hz)")
    axes[0, 1].set_ylabel("Amplitude (a.u.)")
    axes[0, 1].legend(frameon=False, fontsize=6, ncol=2)
    axes[1, 0].axhline(0.0, color="#555555", lw=0.6)
    axes[1, 0].axvline(0.0, color="#555555", lw=0.6)
    axes[1, 0].set_xlabel("y (m)")
    axes[1, 0].set_ylabel("Fy (N)")
    axes[1, 0].legend(frameon=False, fontsize=7)
    comp = metrics["final_window_comparison"]["relative_changes"]
    labels = ["y RMS", "y peak", "Fy RMS", "Cl RMS", "power", "frequency"]
    values = [100 * comp["y_rms_m"], 100 * comp["y_peak_m"], 100 * comp["fy_rms_N"], 100 * comp["cl_rms"], 100 * comp["mean_power_W"], 100 * comp["response_frequency_Hz_zero_crossing"]]
    axes[1, 1].barh(labels, values, color="#4393C3")
    axes[1, 1].axvline(5.0, color="#B2182B", ls="--", lw=0.8, label="5% limit")
    axes[1, 1].axvline(2.0, color="#762A83", ls=":", lw=0.8, label="2% frequency limit")
    axes[1, 1].set_xlabel("Relative change (%)")
    axes[1, 1].legend(frameon=False, fontsize=6)
    for ax in axes.flat:
        style(ax)
    fig.suptitle("Ur=5.2: late-window dynamics and acceptance evidence", fontsize=9)
    save(fig, args.output, "ur5p2_v4_late_windows")
    print(json.dumps({"output": str(args.output), "figures": 2, "formats": ["png", "svg", "pdf", "tiff"]}))


if __name__ == "__main__":
    main()
