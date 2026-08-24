"""Plot the independent long EB/ANCF single-slice online comparison."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


plt.rcParams.update({"font.family": "Arial", "font.size": 7, "svg.fonttype": "none", "pdf.fonttype": 42})


def read(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = []
        for row in csv.DictReader(stream):
            rows.append({key: float(value) if key not in {"force_representation", "status", "compression_risk", "structure_converged"} else (value if key not in {"compression_risk", "structure_converged"} else float(value.lower() == "true")) for key, value in row.items()})
        return rows


def select(rows: list[dict[str, float]], start: float, end: float) -> list[dict[str, float]]:
    return [row for row in rows if start - 1e-12 <= row["time_s"] <= end + 1e-12]


def style(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    ax.grid(True, color="#D9DDE3", linewidth=0.45, alpha=0.7)
    ax.tick_params(labelsize=7, width=0.6, length=3)


def export(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path.with_suffix(".png"), dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".tiff"), dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eb-audit", type=Path, required=True)
    parser.add_argument("--ancf-audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    eb = read(args.eb_audit); ancf = read(args.ancf_audit)
    w1_eb, w2_eb = select(eb, 5.0, 32.0), select(eb, 32.0, 59.0)
    w1_ancf, w2_ancf = select(ancf, 5.0, 32.0), select(ancf, 32.0, 59.0)

    fig, axes = plt.subplots(2, 1, figsize=(7.0, 4.8), sharex=True, constrained_layout=True)
    for rows, color, label in ((eb, "#2166AC", "EB"), (ancf, "#B2182B", "ANCF")):
        axes[0].plot([row["time_s"] for row in rows], [row["corrected_y_m"] for row in rows], color=color, lw=0.55, label=label)
        axes[1].plot([row["time_s"] for row in rows], [row["force_y_N"] for row in rows], color=color, lw=0.55, label=label)
    axes[0].axvspan(5, 32, color="#67A9CF", alpha=0.10); axes[0].axvspan(32, 59, color="#B2182B", alpha=0.06)
    axes[0].set_ylabel("corrected y (m)"); axes[1].set_ylabel("slice force Fy (N)"); axes[1].set_xlabel("time (s)")
    axes[0].set_title("Independent EB/ANCF online feedback: visible amplitude and force")
    for ax in axes: style(ax); ax.legend(frameon=False, fontsize=6)
    export(fig, args.output_dir / "eb_ancf_long_time_y_force_v5")

    fig, axes = plt.subplots(2, 2, figsize=(7.2, 4.6), constrained_layout=True)
    for col, (label, eb_rows, ancf_rows) in enumerate((("5--32 s", w1_eb, w1_ancf), ("32--59 s", w2_eb, w2_ancf))):
        for rows, color, branch in ((eb_rows, "#2166AC", "EB"), (ancf_rows, "#B2182B", "ANCF")):
            t = np.asarray([r["time_s"] for r in rows]); y = np.asarray([r["corrected_y_m"] for r in rows]); fy = np.asarray([r["force_y_N"] for r in rows])
            axes[0, col].plot(t, y, color=color, lw=0.65, label=branch)
            freq = np.fft.rfftfreq(len(y), np.median(np.diff(t)))
            amp = np.abs(np.fft.rfft(y - np.polyval(np.polyfit(np.arange(len(y)), y, 1), np.arange(len(y)))))
            axes[1, col].plot(freq, amp / max(amp.max(), 1e-30), color=color, lw=0.8, label=branch)
        axes[0, col].set_title(label); axes[0, col].set_ylabel("y (m)"); axes[1, col].set_xlabel("frequency (Hz)"); axes[1, col].set_ylabel("normalized spectrum"); axes[1, col].set_xlim(0.01, 0.6)
        axes[0, col].legend(frameon=False, fontsize=6); axes[1, col].legend(frameon=False, fontsize=6)
    for ax in axes.flat: style(ax)
    fig.suptitle("Late-window EB/ANCF histories and response spectra", fontsize=9)
    export(fig, args.output_dir / "eb_ancf_late_window_spectra_v5")
    print({"output_dir": str(args.output_dir), "formats": ["png", "svg", "pdf", "tiff"], "windows": [[5, 32], [32, 59]]})


if __name__ == "__main__":
    main()
