from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams.update({
    "font.family": "Arial", "font.size": 7, "svg.fonttype": "none", "pdf.fonttype": 42,
})


def style(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, color="#D9DDE3", linewidth=0.45, alpha=0.7)
    ax.tick_params(labelsize=7, width=0.6, length=3)


def save(fig: plt.Figure, out: Path) -> None:
    fig.savefig(out.with_suffix(".svg"), format="svg", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(out.with_suffix(".pdf"), format="pdf", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(out.with_suffix(".png"), format="png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(out.with_suffix(".tiff"), format="tiff", dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    items = [json.loads(path.read_text(encoding="utf-8")) for path in args.metrics]
    items.sort(key=lambda item: float(item["ur"]))
    ur = np.asarray([item["ur"] for item in items], dtype=float)
    def value(key: str, window_key: str = "window_2") -> np.ndarray:
        return np.asarray([item[window_key][key] for item in items], dtype=float)
    fn = np.asarray([item["fn_Hz"] for item in items], dtype=float)
    response = value("response_frequency_Hz_zero_crossing")
    f_over_fn = response / fn
    rms = value("y_rms_m")
    half = np.asarray([item["window_2"]["half_amplitude_y_m"] for item in items], dtype=float)
    cl = value("cl_rms")
    cd = value("cd_mean")
    power = value("mean_power_W")

    fig, axes = plt.subplots(2, 3, figsize=(7.1, 4.8), constrained_layout=True)
    series = [
        (axes[0, 0], rms, "A/D RMS", "#2166AC"),
        (axes[0, 1], half, "A/D half amplitude", "#B2182B"),
        (axes[0, 2], f_over_fn, "f/fn", "#1B7837"),
        (axes[1, 0], cl, "Cl RMS", "#762A83"),
        (axes[1, 1], cd, "Cd mean", "#E08214"),
        (axes[1, 2], power, "mean input power (W)", "#0571B0"),
    ]
    for ax, y, ylabel, color in series:
        ax.plot(ur, y, "o-", color=color, lw=1.2, ms=3.2)
        ax.set_xlabel("Ur")
        ax.set_ylabel(ylabel)
        style(ax)
    axes[0, 2].axhspan(0.95, 1.05, color="#67A9CF", alpha=0.16)
    axes[0, 2].axhline(1.0, color="#555555", lw=0.6, ls=":")
    fig.suptitle("Re=100 transverse 1DOF five-point reduced-velocity campaign", fontsize=9)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save(fig, args.output)
    print(json.dumps({"output": str(args.output), "points": len(items), "formats": ["png", "svg", "pdf", "tiff"]}))


if __name__ == "__main__":
    main()
