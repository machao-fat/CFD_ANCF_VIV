"""Publication-oriented v8 figures; Python/matplotlib only, no TIFF export."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "DejaVu Sans", "Liberation Sans", "sans-serif"],
    "font.size": 7,
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.linewidth": 0.8,
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
})

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/04_sdof_corrected_campaign/asymptotic_v8"


def save(fig: plt.Figure, name: str) -> None:
    fig.set_size_inches(7.2, 4.2)
    fig.savefig(OUT / f"{name}.png", dpi=320, bbox_inches="tight")
    fig.savefig(OUT / f"{name}.svg", bbox_inches="tight")
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


def read_prediction() -> dict[str, np.ndarray]:
    with (OUT / "Ur8_model_predictions_v8.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return {key: np.asarray([float(row[key]) for row in rows], dtype=float) for key in ("time_s", "y_m", "prediction_m", "residual_m")}


def model_comparison() -> None:
    data = read_prediction()
    metrics = json.loads((OUT / "Ur8_asymptotic_v8.json").read_text(encoding="utf-8"))
    fig, axes = plt.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [2.0, 1.0]})
    axes[0].plot(data["time_s"], data["y_m"], color="#30343b", lw=0.55, label="measured y")
    # M0/M1 full-window predictions are reconstructed from reported parameters.
    t = data["time_s"]
    for label, key, color in (("M0", "M0", "#4477aa"), ("M1", "M1", "#cc6677")):
        model = metrics["models"][key]
        p = model["parameters"]
        coeff = np.asarray(model.get("coefficients", []), dtype=float)
        # Coefficients are intentionally not used if they are not in the audit
        # JSON; M2 is the selected predictive model shown explicitly below.
        if coeff.size == 6:
            tau = t - t[0]
            design = np.column_stack((np.ones_like(t), tau, np.sin(2*np.pi*p["fs_Hz"]*t), np.cos(2*np.pi*p["fs_Hz"]*t), np.exp(-p["lambda_fit_1_per_s"]*tau)*np.sin(2*np.pi*0.125*t), np.exp(-p["lambda_fit_1_per_s"]*tau)*np.cos(2*np.pi*0.125*t)))
            axes[0].plot(t, design @ coeff, color=color, lw=0.8, label=label)
    axes[0].plot(t, data["prediction_m"], color="#228833", lw=0.9, label="M2 selected")
    axes[0].axvline(metrics["split"]["validation_window_s"][0], color="#888888", ls="--", lw=0.7)
    axes[0].axvline(metrics["split"]["test_window_s"][0], color="#888888", ls="--", lw=0.7)
    axes[0].set_ylabel("y (m)")
    axes[0].legend(ncol=4, loc="upper right")
    axes[1].plot(t, data["residual_m"], color="#228833", lw=0.6)
    axes[1].axhline(0.0, color="#777777", lw=0.5)
    axes[1].set_xlabel("time (s)")
    axes[1].set_ylabel("M2 residual (m)")
    fig.suptitle("Ur=8 model comparison and force-driven prediction")
    save(fig, "Ur8_model_comparison_v8")


def train_validation_test() -> None:
    data = json.loads((OUT / "Ur8_asymptotic_v8.json").read_text(encoding="utf-8"))
    names = ["M0", "M1", "M2"]
    labels = ["train", "validation", "test"]
    x = np.arange(len(names))
    width = 0.24
    fig, ax = plt.subplots()
    for index, split in enumerate(labels):
        vals = [data["models"][name]["split_metrics"][split]["normalized_residual_rms"] for name in names]
        ax.bar(x + (index - 1) * width, vals, width, label=split)
    ax.axhline(0.15, color="#cc6677", ls="--", lw=0.9, label="15% gate")
    ax.set_xticks(x, names)
    ax.set_ylabel("normalized residual RMS")
    ax.set_title("Independent train/validation/test residuals")
    ax.legend(frameon=False)
    save(fig, "Ur8_train_validation_test_v8")


def phase_drift() -> None:
    data = json.loads((OUT / "Ur8_asymptotic_v8.json").read_text(encoding="utf-8"))
    names = ["M0", "M1", "M2"]
    slopes = [data["models"][name]["phase_drift_relative_to_force"]["slope_rad_per_s"] for name in names]
    totals = [data["models"][name]["phase_drift_relative_to_force"]["total_drift_rad"] for name in names]
    fig, axes = plt.subplots(1, 2)
    axes[0].bar(names, slopes, color=["#4477aa", "#cc6677", "#228833"])
    axes[0].axhline(0.0, color="#777777", lw=0.5)
    axes[0].set_ylabel("phase drift slope (rad s$^{-1}$)")
    axes[1].bar(names, totals, color=["#4477aa", "#cc6677", "#228833"])
    axes[1].axhline(0.0, color="#777777", lw=0.5)
    axes[1].set_ylabel("total phase drift (rad)")
    fig.suptitle("Ur=8 phase-drift diagnostic relative to measured Fy")
    save(fig, "Ur8_phase_drift_v8")


def force_driven_prediction() -> None:
    data = read_prediction()
    mask = data["time_s"] >= data["time_s"][-1] - 25.0
    fig, axes = plt.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [2.0, 1.0]})
    axes[0].plot(data["time_s"][mask], data["y_m"][mask], color="#30343b", lw=0.7, label="measured")
    axes[0].plot(data["time_s"][mask], data["prediction_m"][mask], color="#228833", lw=0.9, label="M2 prediction")
    axes[0].set_ylabel("y (m)")
    axes[0].legend(frameon=False)
    axes[1].plot(data["time_s"][mask], data["residual_m"][mask], color="#228833", lw=0.7)
    axes[1].axhline(0.0, color="#777777", lw=0.5)
    axes[1].set_xlabel("time (s)")
    axes[1].set_ylabel("residual (m)")
    fig.suptitle("Ur=8 measured-force-driven independent-tail prediction")
    save(fig, "Ur8_force_driven_prediction_v8")


def dt_comparison() -> None:
    path = ROOT / "results/04_sdof_corrected_campaign/dt_convergence_v8/long_window_dt_convergence_v8.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    c, f = data["coarse"]["window"], data["refined"]["window"]
    keys = ["y_rms_m", "half_amplitude_m", "fy_rms_N", "Cl_rms", "mean_power_W", "response_frequency_Hz_dft"]
    labels = ["y RMS", "half amp", "Fy RMS", "Cl RMS", "power", "y frequency"]
    coarse = np.asarray([c[key] for key in keys], dtype=float)
    fine = np.asarray([f[key] for key in keys], dtype=float)
    coarse /= np.maximum(np.abs(coarse), 1.0e-30)
    fine /= np.maximum(np.abs(coarse), 1.0e-30)
    x = np.arange(len(keys))
    fig, ax = plt.subplots()
    ax.plot(x, coarse, "o-", label="dt=0.0025 s")
    ax.plot(x, fine, "s-", label="dt=0.00125 s")
    ax.set_xticks(x, labels, rotation=25, ha="right")
    ax.set_ylabel("normalized metric")
    ax.set_title("Ur=5.2 common-checkpoint dt/dt2 response-cycle comparison")
    ax.legend(frameon=False)
    save(fig, "dt_dt2_late_window_comparison_v8")


def five_point() -> None:
    v7 = json.loads((ROOT / "results/04_continuous_fsi/stage3_final_metrics_v7.json").read_text(encoding="utf-8-sig"))
    ur8 = json.loads((OUT / "Ur8_asymptotic_v8.json").read_text(encoding="utf-8"))
    rows = []
    for item in v7["five_point"]["points"]:
        if item["ur"] == 8.0:
            rows.append((8.0, ur8["classification"]["class"], ur8["shared_physics_audit"]["response_frequency_f_over_fn"]))
        else:
            rows.append((item["ur"], item["classification"], item["f_over_fn"]))
    fig, ax = plt.subplots()
    x = np.arange(len(rows))
    vals = [row[2] for row in rows]
    colors = ["#228833" if "pass" in str(row[1]) or "lockin" in str(row[1]) and row[0] != 8.0 else "#cc6677" for row in rows]
    ax.bar(x, vals, color=colors)
    ax.axhspan(0.95, 1.05, color="#dddddd", alpha=0.6, label="lock-in band")
    ax.set_xticks(x, [f"Ur={row[0]:g}" for row in rows])
    ax.set_ylabel("f/fn")
    ax.set_title("Five-point response classification retained with v8 Ur=8 model")
    ax.legend(frameon=False)
    save(fig, "five_point_final_lockin_v8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    model_comparison()
    train_validation_test()
    phase_drift()
    force_driven_prediction()
    dt_comparison()
    five_point()
    print(json.dumps({"status": "figures_written", "output": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
