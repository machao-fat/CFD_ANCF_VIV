"""Publication-style five-point SDOF figures with explicit stationarity states."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams.update({
    "font.family": "Arial", "font.size": 7,
    "svg.fonttype": "none", "pdf.fonttype": 42,
})


def style(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, color="#D9DDE3", linewidth=0.45, alpha=0.7)
    ax.tick_params(labelsize=7, width=0.6, length=3)


def save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path.with_suffix(".png"), dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    fig.savefig(path.with_suffix(".tiff"), dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    points = sorted(summary["points"], key=lambda item: float(item["ur"]))
    ur = np.asarray([float(item["ur"]) for item in points])
    fn = np.asarray([float(item["fn_Hz"]) for item in points])
    w1 = [item["window_1"] for item in points]
    w2 = [item["window_2"] for item in points]
    strict = np.asarray([bool(item["final_steady_window_pass"]) for item in points])
    low = np.asarray([bool(item.get("absolute_low_power_criterion_pass", False)) for item in points])

    def values(key: str) -> np.ndarray:
        return np.asarray([float(item.get(key, float("nan"))) for item in w2])

    def errors(key: str) -> np.ndarray:
        return np.abs(values(key) - np.asarray([float(item.get(key, float("nan"))) for item in w1]))

    f_over_fn = values("response_frequency_Hz_dft") / fn
    panels = [
        ("y_rms_m", "A/D RMS", "#2166AC", lambda: values("y_rms_m")),
        ("half_amplitude_y_m", "A/D half amplitude", "#B2182B", lambda: values("half_amplitude_y_m")),
        ("f_over_fn", "f/fn (DFT primary)", "#1B7837", lambda: f_over_fn),
        ("cl_rms", "Cl RMS", "#762A83", lambda: values("cl_rms")),
        ("cd_mean", "Cd mean", "#E08214", lambda: values("cd_mean")),
        ("mean_power_W", "mean input power (W)", "#0571B0", lambda: values("mean_power_W")),
        ("phase", "force-velocity phase (deg)", "#5E3C99", lambda: values("force_velocity_phase_deg")),
    ]
    fig, axes = plt.subplots(2, 4, figsize=(7.2, 4.5), constrained_layout=True)
    for ax, (_, ylabel, color, getter) in zip(axes.flat, panels):
        y = getter()
        if ylabel.startswith("f/fn"):
            err = np.abs(values("response_frequency_Hz_dft") / fn - np.asarray([float(item["response_frequency_Hz_dft"]) for item in w1]) / fn)
        elif ylabel.startswith("force-velocity"):
            err = np.abs(values("force_velocity_phase_deg") - np.asarray([float(item["force_velocity_phase_deg"]) for item in w1]))
        else:
            err = errors(_[0])
        ax.errorbar(ur, y, yerr=err, fmt="none", ecolor="#777777", elinewidth=0.7, capsize=2, zorder=1)
        # Only strictly accepted points are connected.  Transitional points
        # remain visibly separate from the physical curve.
        accepted = strict | low
        if np.count_nonzero(accepted) >= 2:
            ax.plot(ur[accepted], y[accepted], color="#444444", lw=0.8, zorder=2)
        for i, (x, yi) in enumerate(zip(ur, y)):
            marker = "*" if low[i] else "o"
            ax.scatter([x], [yi], s=28 if strict[i] else 25, marker=marker,
                       facecolors=color if strict[i] or low[i] else "white",
                       edgecolors=color, linewidths=0.9, zorder=3)
        ax.set_xlabel("Ur")
        ax.set_ylabel(ylabel)
        style(ax)
    axes[0, 2].axhspan(0.95, 1.05, color="#67A9CF", alpha=0.16, zorder=0)
    axes[0, 2].axhline(1.0, color="#555555", lw=0.6, ls=":")
    axes[1, 3].axis("off")
    axes[1, 3].text(0.02, 0.92, "State encoding", transform=axes[1, 3].transAxes, weight="bold")
    axes[1, 3].scatter([], [], marker="o", facecolors="#2166AC", edgecolors="#2166AC", label="strict steady")
    axes[1, 3].scatter([], [], marker="o", facecolors="white", edgecolors="#2166AC", label="completed / transitional")
    axes[1, 3].scatter([], [], marker="*", facecolors="#2166AC", edgecolors="#2166AC", label="low-power absolute gate")
    axes[1, 3].legend(frameon=False, fontsize=7, loc="upper left")
    fig.suptitle("Re=100 transverse 1DOF campaign: stationarity-aware classification", fontsize=9)
    fig.text(0.01, 0.005, "Markers use the two adjacent five-period windows; bars show their absolute difference. DFT is primary for response and lift frequency.", fontsize=6)
    save(fig, args.output_dir / "five_point_lockin_v5")

    # Stationarity figure: the diagnostic is the largest required relative change.
    keys = [("y_rms_m", "A/D RMS"), ("half_amplitude_y_m", "half amp."), ("fy_rms_N", "Fy RMS"), ("cl_rms", "Cl RMS"), ("mean_power_W", "power"), ("response_frequency_Hz_dft", "frequency")]
    matrix = np.asarray([[float(item["relative_changes"].get(k, 0.0)) for k, _ in keys] for item in points]) * 100.0
    fig, ax = plt.subplots(figsize=(7.1, 3.4), constrained_layout=True)
    for i, item in enumerate(points):
        color = "#2166AC" if strict[i] else "#BDBDBD"
        ax.plot(np.arange(len(keys)), matrix[i], marker="o" if strict[i] else "o", ms=4, lw=0.8, color=color, label=f"Ur={item['ur']}")
    ax.axhline(5.0, color="#B2182B", ls="--", lw=0.8, label="5% criterion")
    ax.set_xticks(np.arange(len(keys)), [label for _, label in keys])
    ax.set_ylabel("window change (%)")
    ax.set_ylim(bottom=0)
    style(ax)
    ax.legend(frameon=False, ncol=3, fontsize=6)
    ax.set_title("Five-point stationarity audit; blue = strict steady, grey = transitional")
    save(fig, args.output_dir / "five_point_stationarity_v5")

    # Energy figure with separate fluid work, damping and mechanical change.
    fig, ax = plt.subplots(figsize=(7.1, 3.6), constrained_layout=True)
    x = np.arange(len(points))
    width = 0.24
    for offset, key, label, color in ((-width, "fluid_work_J", "fluid work", "#2166AC"), (0.0, "damping_dissipation_J", "damping", "#B2182B"), (width, "mechanical_energy_change_J", "mechanical ΔE", "#4D4D4D")):
        vals = []
        for item in points:
            vals.append(float(item.get("last_three_cycle_energy_summary", {}).get(key, 0.0)))
        ax.bar(x + offset, vals, width=width, label=label, color=color, alpha=0.85)
    ax.set_xticks(x, [str(item["ur"]) for item in points])
    ax.set_xlabel("Ur")
    ax.set_ylabel("last-three-cycle mean (J)")
    style(ax)
    ax.legend(frameon=False, ncol=3, fontsize=7)
    ax.set_title("Energy audit summary; bars are not used alone to infer lock-in")
    save(fig, args.output_dir / "five_point_energy_v5")
    print(json.dumps({"output_dir": str(args.output_dir), "formats": ["png", "svg", "pdf", "tiff"], "strict_points": int(np.count_nonzero(strict))}, indent=2))


if __name__ == "__main__":
    main()
