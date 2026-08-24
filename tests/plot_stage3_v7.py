"""Generate editable v7 scientific figures from measured campaign evidence."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans', 'Liberation Sans']
plt.rcParams['svg.fonttype'] = 'none'
plt.rcParams['pdf.fonttype'] = 42
plt.rcParams['ps.fonttype'] = 42
matplotlib.rcParams.update({'svg.fonttype': 'none', 'pdf.fonttype': 42})

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "results" / "04_sdof_corrected_campaign"
OUT = CAMPAIGN / "asymptotic_v7"
FIVE = CAMPAIGN / "five_point_v6"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(paths: list[Path]) -> list[dict[str, float]]:
    result = []
    for path in paths:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            result.extend({key: float(value) for key, value in row.items()} for row in csv.DictReader(stream))
    result.sort(key=lambda row: row["time_s"])
    unique = []
    for row in result:
        if unique and abs(row["time_s"] - unique[-1]["time_s"]) < 1.0e-10:
            continue
        unique.append(row)
    return unique


def save(fig: plt.Figure, stem: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{stem}.png", dpi=320, bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.tiff", dpi=600, bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.svg", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def model_components(times: np.ndarray, fit: dict, fs: float, fn: float, t0: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    coef = np.asarray(fit["coefficients"], dtype=float)
    tau = times - t0
    base = coef[0] + coef[1] * tau
    forced = coef[2] * np.sin(2.0 * math.pi * fs * times) + coef[3] * np.cos(2.0 * math.pi * fs * times)
    free = np.exp(-float(fit["lambda_fit"]) * tau) * (coef[4] * np.sin(2.0 * math.pi * fn * times) + coef[5] * np.cos(2.0 * math.pi * fn * times))
    return base, forced, free, base + forced + free


def decomposition(stem: str, payload: dict, rows: list[dict[str, float]]) -> None:
    start, end = payload["fit_window_s"]
    selected = [r for r in rows if start <= r["time_s"] <= end]
    t = np.asarray([r["time_s"] for r in selected])
    y = np.asarray([r["y_m"] for r in selected])
    fit = payload["fits"]["full_tail"]
    fs = float(payload["frequency_components"]["shedding_force"]["force_frequency_Hz_dft"])
    fn = float(payload["fn_Hz_from_structure_parameters"])
    base, forced, free, total = model_components(t, fit, fs, fn, start)
    residual = y - total
    midpoint = 0.5 * (start + end)
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 6.2), sharex=True, constrained_layout=True)
    axes[0].plot(t, y, color="#222222", linewidth=0.45, label="measured y")
    axes[0].plot(t, total, color="#d95f02", linewidth=0.85, label="full fit")
    axes[0].plot(t, base + forced, color="#1b9e77", linewidth=0.8, label="base + forced")
    axes[0].plot(t, base + free, color="#7570b3", linewidth=0.65, alpha=0.75, label="base + free")
    axes[0].axvline(midpoint, color="black", linestyle="--", linewidth=0.7, label="fit/prediction boundary")
    axes[0].set_ylabel("y (m)")
    axes[0].set_title(f"{stem.replace('_', ' ')}: forced + free transient decomposition")
    axes[0].legend(ncol=4, fontsize=7, loc="upper right")
    axes[0].grid(alpha=0.2)
    axes[1].plot(t, residual, color="#1b4f72", linewidth=0.45)
    axes[1].axhline(0.0, color="black", linewidth=0.5)
    axes[1].axvline(midpoint, color="black", linestyle="--", linewidth=0.7)
    axes[1].set_xlabel("time (s)")
    axes[1].set_ylabel("fit residual (m)")
    axes[1].grid(alpha=0.2)
    save(fig, stem)


def envelope(ur4: dict, ur8: dict) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.7), constrained_layout=True)
    for payload, color, label in ((ur4, "#1b9e77", "Ur=4"), (ur8, "#d95f02", "Ur=8")):
        start, end = payload["fit_window_s"]
        fit = payload["fits"]["first_half"]
        fs = float(payload["frequency_components"]["shedding_force"]["force_frequency_Hz_dft"])
        fn = float(payload["fn_Hz_from_structure_parameters"])
        ts = np.linspace(start, end, 500)
        base, forced, free, _ = model_components(ts, fit, fs, fn, start)
        ax.plot(ts, np.full_like(ts, float(fit["As_m"])), color=color, linewidth=1.2, label=f"{label} forced amplitude")
        ax.plot(ts, np.abs(free), color=color, linestyle="--", linewidth=1.1, label=f"{label} free envelope")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("amplitude (m)")
    ax.set_title("Stable forced response and independently decaying free component")
    ax.grid(alpha=0.22)
    ax.legend(ncol=2, fontsize=8)
    save(fig, "Ur4_Ur8_envelope_decay_v7")


def forced_stability(ur4: dict, ur8: dict) -> None:
    labels, first, second, full = [], [], [], []
    for payload, label in ((ur4, "Ur=4"), (ur8, "Ur=8")):
        labels.append(label)
        first.append(float(payload["fits"]["first_half"]["As_m"]))
        second.append(float(payload["fits"]["second_half"]["As_m"]))
        full.append(float(payload["fits"]["full_tail"]["As_m"]))
    x = np.arange(len(labels))
    width = 0.24
    fig, ax = plt.subplots(figsize=(7.2, 4.7), constrained_layout=True)
    ax.bar(x - width, first, width, label="first half", color="#1b9e77")
    ax.bar(x, second, width, label="second half", color="#d95f02")
    ax.bar(x + width, full, width, label="full tail", color="#7570b3")
    ax.set_xticks(x, labels)
    ax.set_ylabel("fitted forced amplitude (m)")
    ax.set_title("Forced-amplitude stability across fit regions")
    ax.grid(axis="y", alpha=0.22)
    ax.legend()
    save(fig, "forced_amplitude_stability_v7")


def five_point() -> None:
    paths = sorted(FIVE.glob("Ur*_point_metrics_v6.json"))
    points = [load(p) for p in paths]
    asym = {4.0: load(OUT / "Ur4_asymptotic_v7.json"), 8.0: load(OUT / "Ur8_asymptotic_v7.json")}
    ur = np.array([float(p["ur"]) for p in points])
    f_ratio = []
    amp = []
    labels = []
    for p in points:
        u = float(p["ur"])
        if u in asym:
            f_ratio.append(float(asym[u]["frequency_components"]["response_f_over_fn"]))
            amp.append(float(asym[u]["fits"]["full_tail"]["As_m"]))
            labels.append(asym[u]["classification"]["class"])
        else:
            final = p["final_response_pair"]
            f_ratio.append(float(final["f_over_fn_dft"]))
            amp.append(float(final["window_2"]["half_amplitude_y_m"]))
            labels.append(final["physical_lockin_classification"])
    colors = ["#d95f02" if "outside" in label or "asymptotic" in label else "#1b9e77" for label in labels]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 4.4), constrained_layout=True)
    axes[0].plot(ur, f_ratio, color="#333333", linewidth=0.8)
    axes[0].scatter(ur, f_ratio, c=colors, edgecolor="black", linewidth=0.4, s=55)
    axes[0].axhspan(0.95, 1.05, color="#1b9e77", alpha=0.12, label="lock-in band")
    axes[0].set_xlabel("Ur")
    axes[0].set_ylabel("response f/fn")
    axes[0].grid(alpha=0.22)
    axes[0].legend(fontsize=8)
    axes[1].plot(ur, amp, color="#333333", linewidth=0.8)
    axes[1].scatter(ur, amp, c=colors, edgecolor="black", linewidth=0.4, s=55)
    axes[1].set_xlabel("Ur")
    axes[1].set_ylabel("final/forced amplitude (m)")
    axes[1].grid(alpha=0.22)
    axes[1].set_title("five-point final classification")
    save(fig, "five_point_final_lockin_v7")


def dt_plot(dt: dict) -> None:
    keys = [("y_rms_m", "y RMS"), ("half_amplitude_m", "half amplitude"), ("fy_rms_N", "Fy RMS"), ("Cl_rms", "Cl RMS"), ("mean_power_W", "mean power")]
    coarse = [float(dt["coarse"][key]) for key, _ in keys]
    refined = [float(dt["refined"][key]) for key, _ in keys]
    x = np.arange(len(keys))
    fig, ax = plt.subplots(figsize=(7.2, 4.7), constrained_layout=True)
    ax.plot(x, np.ones(len(keys)), marker="o", label="dt=0.0025 s", color="#1b9e77")
    ax.plot(x, np.asarray(refined) / np.asarray(coarse), marker="s", label="dt/2=0.00125 s", color="#d95f02")
    ax.axhspan(0.95, 1.05, color="#1b9e77", alpha=0.10, label="5% response/force band")
    ax.set_xticks(x, [label for _, label in keys], rotation=20)
    ax.set_ylabel("normalized refined/coarse metric")
    ax.set_title("Existing dt/dt/2 screening; window length is reported separately")
    ax.grid(axis="y", alpha=0.22)
    ax.legend(fontsize=8)
    save(fig, "dt_dt2_long_window_v7")


def main() -> None:
    ur4 = load(OUT / "Ur4_asymptotic_v7.json")
    ur8 = load(OUT / "Ur8_asymptotic_v7.json")
    rows4 = read_rows([CAMPAIGN / "Ur4_v4_70_to90_retry2" / "sdof_audit.csv", CAMPAIGN / "Ur4_v5_to130" / "sdof_audit.csv", CAMPAIGN / "Ur4_v6_to140" / "sdof_audit.csv"])
    rows8 = read_rows([CAMPAIGN / "Ur8p0_v5_to160" / "sdof_audit.csv", CAMPAIGN / "Ur8p0_v6_to200" / "sdof_audit.csv", CAMPAIGN / "Ur8p0_v7_to260" / "sdof_audit_interrupted_after_221p25.csv", CAMPAIGN / "Ur8p0_v7_to260" / "sdof_audit.csv"])
    decomposition("Ur4_forced_free_decomposition_v7", ur4, rows4)
    decomposition("Ur8_forced_free_decomposition_v7", ur8, rows8)
    envelope(ur4, ur8)
    forced_stability(ur4, ur8)
    five_point()
    dt_plot(load(OUT / "dt_dt2_long_window_v7.json"))
    print(json.dumps({"status": "figures_written", "output": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
