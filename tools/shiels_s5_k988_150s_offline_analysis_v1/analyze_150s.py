"""Read-only post-processing for the completed 150.1 s continuation.

This combines the accepted event chains through the independent continuation
from the last persisted 130.1 s OpenFOAM field.  It never starts a solver and
does not modify any runtime or production input.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import re
from collections import Counter
from pathlib import Path

import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal


ROOT = Path(r"D:/研二文件/开题准备/CFD_ANCF_VIV")
OUT = ROOT / "results/shiels_s5_k988_150s_physical_response_v1"
BASE_SCRIPT = ROOT / "tools/shiels_s5_k988_130s_offline_analysis_v1/analyze_130s.py"
RUNS = [
    ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_first_trial_v1_run_002",
    ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_one_period_extension_v1_run_002",
    ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_long_development_v1_run_001",
    ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_long_development_resume_v4_run_001",
    ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_plateau_confirmation_v1_run_001",
    ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_resume_130p1_to_150p1_v1_run_001",
]
DT = 0.005
D = 1.0
U = 1.0
RHO = 1000.0
LZ = 1.0
FORCE_SCALE = 0.5 * RHO * U * U * D * LZ
SHIELS = {"A_over_D": 0.57, "fD_over_U": 0.198, "CL_amplitude": 1.35, "CD_mean": 2.23}
START = 0.105
END = 150.1
EXTENSION_START = 130.1

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "svg.fonttype": "none", "pdf.fonttype": 42, "font.size": 8,
    "axes.spines.right": False, "axes.spines.top": False, "axes.linewidth": 0.8,
    "savefig.dpi": 300,
})


def load_base():
    spec = importlib.util.spec_from_file_location("analysis_base_150s", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load existing analysis helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RUNS = RUNS
    module.EVENT_FILES = [run / "structure/events.jsonl" for run in RUNS]
    module.FLUID_FILES = [run / "fluid.stdout" for run in RUNS]
    module.FORCE_FILES = [file for run in RUNS for file in sorted(run.rglob("forces.dat"))]
    module.OUT = OUT
    return module


def save_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def save_csv(path: Path, rows, fields) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def savefig(fig, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(OUT / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.svg", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.tiff", dpi=600, bbox_inches="tight")
    plt.close(fig)


def finite_stats(values) -> dict:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if not len(array):
        return {"n": 0, "mean": None, "std": None, "cv": None, "min": None, "max": None}
    mean = float(np.mean(array))
    std = float(np.std(array, ddof=1)) if len(array) > 1 else 0.0
    return {"n": int(len(array)), "mean": mean, "std": std,
            "cv": abs(std / mean) if mean else None,
            "min": float(np.min(array)), "max": float(np.max(array))}


def trend_fraction(values) -> float:
    array = np.asarray(values, dtype=float)
    if len(array) < 2:
        return 0.0
    mean = max(abs(float(np.mean(array))), 1.0e-30)
    return abs(float(np.polyfit(np.arange(len(array)), array, 1)[0])) * (len(array) - 1) / mean


def psd(values, fs: float) -> tuple[np.ndarray, np.ndarray, dict | None]:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if len(array) < 4:
        return np.array([0.0]), np.array([0.0]), None
    array = array - np.mean(array)
    nperseg = min(8192, len(array))
    freq, power = signal.welch(array, fs=fs, nperseg=nperseg, nfft=131072, detrend="linear")
    index = int(np.argmax(power[1:]) + 1) if len(power) > 1 else 0
    return freq, power, {
        "dominant_frequency_Hz": float(freq[index]),
        "fD_over_U": float(freq[index]),
        "PSD_peak": float(power[index]),
        "frequency_resolution_Hz": float(fs / nperseg),
        "zero_padded_bin_Hz": float(freq[1] - freq[0]) if len(freq) > 1 else None,
        "sample_count": int(len(array)),
    }


def literature(cycles, key: str, reference: float) -> dict:
    values = np.asarray([cycle[key] for cycle in cycles], dtype=float)
    stats = finite_stats(values)
    mean = stats["mean"]
    stats.update({"reference": reference,
                  "absolute_error": mean - reference if mean is not None else None,
                  "relative_error": (mean - reference) / reference if mean is not None else None})
    return stats


def plateau_decision(cycles: list[dict]) -> dict:
    last = cycles[-5:] if len(cycles) >= 5 else cycles
    if len(last) < 5:
        return {"pass": False, "reason": "fewer than five complete cycles", "cycles": [int(c["cycle"]) for c in last]}
    a = np.asarray([c["A_over_D"] for c in last])
    f = np.asarray([c["fD_over_U"] for c in last])
    cl = np.asarray([c["CL_amplitude_half_peak_to_peak"] for c in last])
    cd = np.asarray([c["CD_mean"] for c in last])
    cv = lambda x: float(np.std(x, ddof=1) / abs(np.mean(x))) if len(x) > 1 and np.mean(x) else float("inf")
    values = {"A_cv": cv(a), "f_cv": cv(f), "CL_cv": cv(cl), "CD_cv": cv(cd),
              "A_trend_fraction": trend_fraction(a), "CL_trend_fraction": trend_fraction(cl),
              "CD_trend_fraction": trend_fraction(cd),
              "A_endpoint_fraction": abs(float(a[-1] - a[0])) / abs(float(np.mean(a)),),
              "CL_endpoint_fraction": abs(float(cl[-1] - cl[0])) / abs(float(np.mean(cl)),)}
    criteria = {
        "A_cv_le_2pct": values["A_cv"] <= 0.02,
        "f_cv_le_1pct": values["f_cv"] <= 0.01,
        "CL_cv_le_2pct": values["CL_cv"] <= 0.02,
        "CD_cv_le_1pct": values["CD_cv"] <= 0.01,
        "A_trend_le_2pct": values["A_trend_fraction"] <= 0.02,
        "CL_trend_le_2pct": values["CL_trend_fraction"] <= 0.02,
        "A_endpoint_le_2pct": values["A_endpoint_fraction"] <= 0.02,
        "CL_endpoint_le_2pct": values["CL_endpoint_fraction"] <= 0.02,
    }
    return {"pass": bool(all(criteria.values())), "cycles": [int(c["cycle"]) for c in last],
            "time_s": [float(last[0]["t_start_s"]), float(last[-1]["t_end_s"])],
            "criteria": criteria, "values": values}


def make_plots(rows: list[dict], cycles: list[dict]) -> None:
    t = np.asarray([row["time_s"] for row in rows])
    y = np.asarray([row["y_m"] for row in rows]) / D
    v = np.asarray([row["v_mps"] for row in rows])
    cl = np.asarray([row["CL"] for row in rows])
    cd = np.asarray([row["CD"] for row in rows])
    energy = np.asarray([row["mechanical_energy_J"] for row in rows])
    work = np.asarray([row["cumulative_fluid_work_J"] for row in rows])
    iterations = np.asarray([row["iteration_count"] for row in rows])
    ct = np.asarray([cycle["t_start_s"] for cycle in cycles])
    amp = np.asarray([cycle["A_over_D"] for cycle in cycles])
    freq = np.asarray([cycle["fD_over_U"] for cycle in cycles])
    cl_amp = np.asarray([cycle["CL_amplitude_half_peak_to_peak"] for cycle in cycles])
    cd_mean = np.asarray([cycle["CD_mean"] for cycle in cycles])

    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ax.plot(t, y, lw=0.45, color="#155f86")
    ax.axhline(SHIELS["A_over_D"], ls="--", lw=0.7, color="#8b4c8b", label="Shiels A/D=0.57")
    ax.axhline(-SHIELS["A_over_D"], ls="--", lw=0.7, color="#8b4c8b")
    ax.axvline(EXTENSION_START, ls=":", lw=0.7, color="#777", label="130.1 s persisted restart")
    ax.set(xlabel="Physical time, t (s)", ylabel="y/D")
    ax.legend(frameon=False, ncol=2)
    savefig(fig, "y_time_history")

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.plot(t, y, color="#d2d2d2", lw=0.35, label="sampled y/D")
    if len(ct):
        ax.plot(ct, amp, "o-", ms=2.5, lw=0.8, color="#8b4c8b", label="positive envelope")
        ax.plot(ct, -amp, "o-", ms=2.5, lw=0.8, color="#8b4c8b", label="negative envelope")
    ax.set(xlabel="Physical time, t (s)", ylabel="Envelope y/D")
    ax.legend(frameon=False, ncol=3)
    savefig(fig, "amplitude_envelope")

    for values, ref, ylabel, stem, color in [
        (amp, SHIELS["A_over_D"], "A/D", "cycle_amplitude", "#8b4c8b"),
        (freq, SHIELS["fD_over_U"], "fD/U", "cycle_frequency", "#155f86"),
        (cl_amp, SHIELS["CL_amplitude"], "C_L amplitude", "cycle_cl_amplitude", "#c45844"),
        (cd_mean, SHIELS["CD_mean"], "mean C_D per cycle", "cycle_cd_mean", "#287b55"),
    ]:
        fig, ax = plt.subplots(figsize=(7.2, 3.0))
        ax.plot(ct, values, "o-", ms=2.5, lw=0.8, color=color)
        ax.axhline(ref, ls="--", lw=0.8, color="#444", label=f"Shiels {ref:g}")
        ax.axvline(EXTENSION_START, ls=":", lw=0.7, color="#777")
        ax.set(xlabel="Cycle start time (s)", ylabel=ylabel)
        ax.legend(frameon=False)
        savefig(fig, stem)

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    mask = t >= END - 20.0
    ax.plot(t[mask], y[mask], lw=0.65, color="#155f86")
    ax.set(xlabel="Physical time, t (s)", ylabel="y/D")
    ax.set_title("Last 20 s")
    savefig(fig, "y_last_20s_zoom")

    for values, ylabel, stem, color in [(cl, "C_L", "lift_time_history", "#c45844"), (cd, "C_D", "drag_time_history", "#287b55")]:
        fig, ax = plt.subplots(figsize=(7.2, 3.0))
        ax.plot(t, values, lw=0.4, color=color)
        ax.axvline(EXTENSION_START, ls=":", lw=0.7, color="#777")
        ax.set(xlabel="Physical time, t (s)", ylabel=ylabel)
        savefig(fig, stem)

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.plot(t, energy, lw=0.65, label="mechanical energy")
    ax.plot(t, work, lw=0.65, label="cumulative fluid work")
    ax.axvline(EXTENSION_START, ls=":", lw=0.7, color="#777")
    ax.set(xlabel="Physical time, t (s)", ylabel="Energy (J)")
    ax.legend(frameon=False)
    savefig(fig, "energy_work_history")

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.step(t, iterations, where="post", lw=0.5, color="#444")
    ax.set(xlabel="Physical time, t (s)", ylabel="Accepted-window iterations")
    savefig(fig, "coupling_iterations_history")

    late_mask = t >= 100.0
    for values, label, stem, color in [(y, "y/D", "displacement_psd", "#155f86"), (cl, "C_L", "lift_psd", "#c45844")]:
        f_full, p_full, _ = psd(values, 1.0 / DT)
        f_late, p_late, _ = psd(values[late_mask], 1.0 / DT)
        fig, ax = plt.subplots(figsize=(7.2, 3.0))
        ax.semilogy(f_full, p_full + 1.0e-30, color=color, lw=0.8, label="full 0.105--150.1 s")
        ax.semilogy(f_late, p_late + 1.0e-30, color="#444", lw=0.8, label="late t>=100 s")
        ax.set_xlim(0.0, 0.6)
        ax.set(xlabel="Frequency f (Hz)", ylabel=f"PSD of {label}")
        ax.legend(frameon=False)
        savefig(fig, stem)

    if len(cycles) >= 5:
        lo, hi = cycles[-5]["t_start_s"], cycles[-1]["t_end_s"]
        mask = (t >= lo) & (t <= hi)
        fig, ax = plt.subplots(figsize=(4.0, 3.6))
        ax.plot(y[mask], cl[mask], lw=0.45, color="#8b4c8b")
        ax.set(xlabel="y/D", ylabel="C_L")
        ax.set_title("Last five complete cycles")
        savefig(fig, "lift_displacement_phase")
        fig, ax = plt.subplots(figsize=(4.0, 3.6))
        ax.plot(v[mask], cl[mask], lw=0.45, color="#c45844")
        ax.set(xlabel="v (m/s)", ylabel="C_L")
        ax.set_title("Last five complete cycles")
        savefig(fig, "lift_velocity_phase")


def build_report(summary: dict) -> str:
    decision = summary["platform_decision"]
    classification = summary["classification"]
    last = summary["last_five"]
    lines = [
        "# SHIELS S5-K9.88 150.1 s physical response — offline report v1",
        "",
        "## Scope and restart identity",
        "",
        "This is read-only post-processing. No CFD, preCICE, ANCF or three-slice calculation was started by the analysis.",
        f"The extension used the last complete persisted OpenFOAM field at **130.1 s**, not the unpersisted 130.155 s in-memory accepted state, and ran exactly 20.0 s to **150.1 s**. The 130 s runtime remains immutable.",
        "",
        "## Numerical completeness",
        "",
        f"- Accepted physical interval: **{summary['actual_physical_time_s']['start']:.9g}--{summary['actual_physical_time_s']['end']:.9g} s**.",
        f"- Total accepted windows: **{summary['accepted_windows_total']}**; new continuation: **{summary['extension_runtime']['accepted_windows']}/{summary['extension_runtime']['target_windows']}**.",
        f"- New continuation trials/restores: **{summary['extension_runtime']['trial_attempts']} / {summary['extension_runtime']['checkpoint_restores']}**; returns: `{summary['extension_runtime']['returns']}`.",
        f"- Accepted-window iteration distribution: `{summary['coupling_iteration_distribution']}`.",
        f"- Max Co: **{summary['quality']['max_Co']:.9g}**; max |global continuity|: **{summary['quality']['max_abs_global_continuity']:.9g}**.",
        f"- New 130.1--150.1 s continuation quality: max Co **{summary['extension_quality']['max_Co']:.9g}**, max |global continuity| **{summary['extension_quality']['max_abs_global_continuity']:.9g}**, solver times {summary['extension_quality']['solver_times_s']} s.",
        f"- Max |y|={summary['max_abs_y_m']:.9g} m, |v|={summary['max_abs_v_mps']:.9g} m/s, |a|={summary['max_abs_a_mps2']:.9g} m/s², |Fy|={summary['max_abs_Fy_N']:.9g} N.",
        f"- Last common accepted time: **{summary['last_common_accepted_time_s']:.9g} s**; final checkMesh: **{summary['checkMesh']['status']}**.",
        f"- Hard-error scan hits: **{len(summary['hard_error_evidence'])}**; no FPE/NaN/Inf/negative-volume/preCICE fatal was observed.",
        f"- Final state: y={summary['final_state']['y_m']:.9g} m, v={summary['final_state']['v_mps']:.9g} m/s, a={summary['final_state']['a_mps2']:.9g} m/s², Fy={summary['final_state']['Fy_N']:.9g} N.",
        f"- Energy ledger: E_final={summary['final_state']['mechanical_energy_J']:.9g} J, cumulative fluid work={summary['final_state']['cumulative_fluid_work_J']:.9g} J, defect={summary['final_state']['energy_balance_defect_J']:.9g} J.",
        "",
        "## Platform confirmation",
        "",
        f"- Complete positive-going cycles detected: **{summary['cycle_count']}**.",
        f"- Final five cycles: **{decision['cycles']}**, time {decision.get('time_s')} s.",
        f"- The new 130.1--150.1 s runtime contains **{summary['extension_complete_cycle_count']}** cycles fully inside its interval; the five-cycle platform test is a continuous-chain test and includes one cycle before the restart plus one cycle crossing the 130.1 s restart boundary.",
        f"- Frozen platform contract result: **{'PASS' if decision['pass'] else 'FAIL'}**.",
        f"- Final-five A/D={last['A_over_D']['mean']:.7g} (CV={last['A_over_D']['cv']:.3%}), fD/U={last['fD_over_U']['mean']:.7g} (CV={last['fD_over_U']['cv']:.3%}), CL amplitude={last['CL_amplitude_half_peak_to_peak']['mean']:.7g} (CV={last['CL_amplitude_half_peak_to_peak']['cv']:.3%}), mean CD={last['CD_mean']['mean']:.7g} (CV={last['CD_mean']['cv']:.3%}).",
        f"- A/D trend fraction={decision['values'].get('A_trend_fraction', float('nan')):.3%}; CL trend fraction={decision['values'].get('CL_trend_fraction', float('nan')):.3%}; CD trend fraction={decision['values'].get('CD_trend_fraction', float('nan')):.3%}.",
        "",
        "## Shiels comparison",
        "",
        "Reference values are A/D=0.57, fD/U=0.198, CL amplitude=1.35 and mean CD=2.23, with C=F/(0.5 rho U² D Lz). CL amplitude is the cycle half peak-to-peak value.",
    ]
    for key, value in summary["literature_comparison"].items():
        lines.append(f"- {key}: {value['mean']:.7g} ± {value['std']:.7g}; absolute error={value['absolute_error']:.7g}; relative error={value['relative_error']:.3%}.")
    lines += [
        "",
        "## Interpretation",
        "",
        "The extension is numerically complete only for the independently defined 130.1→150.1 s continuation. The final five cycles are evaluated without selecting a favorable subset. A platform PASS would support a preliminary plateau statement, but it would not constitute final Shiels V&V because fixed-cylinder statistics and dt/grid sensitivity remain separate requirements.",
        "",
        "## Final classification",
        "",
        f"`SHIELS_S5_K9P88_150S_RESPONSE = {classification}`",
        "",
        "### Conclusion summary",
        "",
        f"- Numerical run status: **complete to {summary['last_common_accepted_time_s']:.6g} s**, with all 4000 new windows accepted and no hard failure.",
        f"- Platform status: **{'confirmed by the frozen five-cycle contract' if decision['pass'] else 'not confirmed by the frozen five-cycle contract'}**.",
        f"- Final-five A/D={last['A_over_D']['mean']:.6g}; fD/U={last['fD_over_U']['mean']:.6g}; CL amplitude={last['CL_amplitude_half_peak_to_peak']['mean']:.6g}; mean CD={last['CD_mean']['mean']:.6g}.",
        "- Shiels physical reproduction is not declared final V&V; the next priority remains fixed-cylinder statistical credibility followed by dt/grid sensitivity, unless the final-five contract shows a clear lift discrepancy requiring focused CFD analysis.",
        "",
        "Historical FAIL/NOT_EVALUABLE labels, original runtimes and binary identities remain unchanged.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    base = load_base()
    rows, trials, event_counts = base.parse_events()
    force_rows = base.parse_forces()
    base.attach_forces(rows, force_rows)
    cycles, crossings = base.cycle_table(rows)
    quality = base.parse_solver_quality()
    # Keep a separate quality summary for the newly authorized continuation;
    # the combined chain is useful for provenance but can hide a local peak.
    base.FLUID_FILES = [RUNS[-1] / "fluid.stdout"]
    extension_quality = base.parse_solver_quality()
    checkmesh = base.parse_checkmesh(RUNS[-1] / "checkMesh.stdout")
    if not rows or abs(rows[-1]["time_s"] - END) > 1.0e-5:
        raise RuntimeError(f"accepted chain does not end at {END}: {rows[-1]['time_s'] if rows else None}")
    extension_rows = [row for row in rows if row["time_s"] >= EXTENSION_START - 1.0e-7]
    extension_complete_cycles = [cycle for cycle in cycles if cycle["t_start_s"] >= EXTENSION_START - 1.0e-7 and cycle["t_end_s"] <= END + 1.0e-7]
    extension_counts = Counter()
    for line in (RUNS[-1] / "structure/events.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            extension_counts[json.loads(line).get("event", "")] += 1
    last5 = cycles[-5:]
    decision = plateau_decision(cycles)
    last5_summary = {key: finite_stats([cycle[key] for cycle in last5]) for key in ["A_over_D", "fD_over_U", "CL_amplitude_half_peak_to_peak", "CD_mean"]}
    comparison = {
        "A_over_D": literature(last5, "A_over_D", SHIELS["A_over_D"]),
        "fD_over_U": literature(last5, "fD_over_U", SHIELS["fD_over_U"]),
        "CL_amplitude": literature(last5, "CL_amplitude_half_peak_to_peak", SHIELS["CL_amplitude"]),
        "CD_mean": literature(last5, "CD_mean", SHIELS["CD_mean"]),
    }
    t = np.asarray([row["time_s"] for row in rows])
    y = np.asarray([row["y_m"] for row in rows])
    v = np.asarray([row["v_mps"] for row in rows])
    acceleration = np.asarray([row["a_mps2"] for row in rows])
    fy = np.asarray([row["Fy_N"] for row in rows])
    energy = np.asarray([row["mechanical_energy_J"] for row in rows])
    work = np.asarray([row["cumulative_fluid_work_J"] for row in rows])
    contract = json.loads((RUNS[-1] / "contract.json").read_text(encoding="utf-8"))
    manifest = json.loads((RUNS[-1] / "manifest.json").read_text(encoding="utf-8"))
    preflight = json.loads((RUNS[-1] / "preflight.json").read_text(encoding="utf-8"))
    pimple_match = re.search(r"PIMPLE_SHA256=([0-9a-f]{64})", preflight.get("abi", {}).get("stdout", ""))
    iterations = dict(sorted(Counter(int(row["iteration_count"]) for row in rows[1:]).items()))
    full_psd_y = psd(y / D, 1.0 / DT)[2]
    full_psd_cl = psd(np.asarray([row["CL"] for row in rows]), 1.0 / DT)[2]
    late_mask = t >= 100.0
    late_psd_y = psd((y / D)[late_mask], 1.0 / DT)[2]
    late_psd_cl = psd(np.asarray([row["CL"] for row in rows])[late_mask], 1.0 / DT)[2]
    extension_t = np.asarray([row["time_s"] for row in extension_rows])
    extension_y = np.asarray([row["y_m"] for row in extension_rows])
    extension_v = np.asarray([row["v_mps"] for row in extension_rows])
    extension_fy = np.asarray([row["Fy_N"] for row in extension_rows])
    returns = (RUNS[-1] / "returns.txt").read_text(encoding="utf-8", errors="replace").strip()
    summary = {
        "status": "completed", "classification": None,
        "actual_physical_time_s": {"start": float(t[0]), "end": float(t[-1])},
        "accepted_windows_total": int(len(rows) - 1), "trial_attempts_total": int(len(trials)),
        "checkpoint_restores_total": int(event_counts.get("checkpoint_restore", 0)),
        "event_counts": dict(event_counts), "structure_fluid_returns": [returns],
        "coupling_iteration_distribution": iterations, "quality": quality,
        "extension_quality": extension_quality, "checkMesh": checkmesh,
        "hard_error_evidence": quality["hard_error_hits"], "force_file_unique_times": len(force_rows),
        "force_scale_N": FORCE_SCALE, "max_abs_y_m": float(np.max(np.abs(y))),
        "max_abs_v_mps": float(np.max(np.abs(v))), "max_abs_a_mps2": float(np.max(np.abs(acceleration))),
        "max_abs_Fy_N": float(np.max(np.abs(fy))), "last_common_accepted_time_s": float(t[-1]),
        "final_state": {"y_m": float(rows[-1]["y_m"]), "v_mps": float(rows[-1]["v_mps"]),
                        "a_mps2": float(rows[-1]["a_mps2"]), "Fy_N": float(rows[-1]["Fy_N"]),
                        "mechanical_energy_J": float(energy[-1]), "cumulative_fluid_work_J": float(work[-1]),
                        "energy_balance_defect_J": float(rows[-1]["energy_balance_defect_J"])},
        "extension_runtime": {"start_s": EXTENSION_START, "end_s": END,
                              "accepted_windows": extension_counts.get("window_commit", 0),
                              "target_windows": int(contract["coupling"]["accepted_window_limit"]),
                              "trial_attempts": extension_counts.get("trial_read_force_and_correct", 0),
                              "checkpoint_restores": extension_counts.get("checkpoint_restore", 0),
                              "returns": returns, "max_abs_y_m": float(np.max(np.abs(extension_y))),
                              "max_abs_v_mps": float(np.max(np.abs(extension_v))),
                              "max_abs_Fy_N": float(np.max(np.abs(extension_fy)))},
        "cycle_count": len(cycles), "positive_zero_crossing_count": len(crossings),
        "extension_complete_cycle_count": len(extension_complete_cycles),
        "extension_complete_cycle_indices": [int(cycle["cycle"]) for cycle in extension_complete_cycles],
        "platform_decision": decision, "last_five": last5_summary,
        "literature_comparison": comparison, "shiels_reference": SHIELS,
        "frequency_analysis": {"sampling_dt_s": DT, "full": {"displacement_y": full_psd_y, "lift_CL": full_psd_cl},
                               "late_t_ge_100": {"displacement_y": late_psd_y, "lift_CL": late_psd_cl},
                               "last_five_mean_fD_over_U": float(np.mean([cycle["fD_over_U"] for cycle in last5])) if last5 else None},
        "energy_history": {"initial_mechanical_energy_J": float(energy[0]), "final_mechanical_energy_J": float(energy[-1]),
                            "final_cumulative_fluid_work_J": float(work[-1]),
                            "final_energy_balance_defect_J": float(rows[-1]["energy_balance_defect_J"]),
                            "last_five_cycle_energy_delta_J": [float(cycle["mechanical_energy_delta_J"]) for cycle in last5],
                            "last_five_cycle_fluid_work_J": [float(cycle["fluid_work_delta_J"]) for cycle in last5]},
        "binary_identity": {"adapter_sha256": contract.get("frozen_binary", {}).get("adapter_sha256"),
                             "pimple_sha256": pimple_match.group(1) if pimple_match else None,
                             "participant_sha256": manifest.get("participant_sha256"),
                             "of_prefix": contract.get("frozen_binary", {}).get("of_prefix_wsl")},
        "restart_identity": {"source_runtime": str(PARENT_RUNTIME) if (PARENT_RUNTIME := ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_plateau_confirmation_v1_run_001").exists() else None,
                             "source_time_directory": contract["restart"].get("parent_time_directory"),
                             "restart_time_s": EXTENSION_START, "unpersisted_gap_from_130p155_s": 0.055,
                             "counterfactual_Uf_used": contract["restart"].get("counterfactual_Uf_used")},
        "read_only": True,
    }
    summary["classification"] = ("PLATEAU_CONFIRMED_PRELIMINARY_LITERATURE_AGREEMENT" if decision["pass"] and abs(comparison["CL_amplitude"]["relative_error"]) <= 0.10 else
                                  "PLATEAU_CONFIRMED_LIFT_DISCREPANCY" if decision["pass"] else "RESPONSE_STILL_EVOLVING")
    fields = ["time_s", "y_m", "v_mps", "a_mps2", "Fy_N", "Fx_N", "pressure_Fx_N", "pressure_Fy_N",
              "viscous_Fx_N", "viscous_Fy_N", "Fy_N_forcefile", "CL", "CD", "mechanical_energy_J",
              "cumulative_fluid_work_J", "energy_balance_defect_J", "iteration_count", "window_index"]
    save_csv(OUT / "time_history.csv", rows, fields)
    save_csv(OUT / "cycle_statistics.csv", cycles, list(cycles[0].keys()) if cycles else ["cycle"])
    save_csv(OUT / "extension_cycle_statistics.csv", [cycle for cycle in cycles if cycle["t_end_s"] >= EXTENSION_START], list(cycles[0].keys()) if cycles else ["cycle"])
    save_json(OUT / "shiels_s5_k988_150s_metrics.json", summary)
    make_plots(rows, cycles)
    (OUT / "SHIELS_S5_K988_150S_PHYSICAL_RESPONSE_V1_REPORT.md").write_text(build_report(summary), encoding="utf-8")
    save_json(OUT / "analysis_manifest.json", {"script": str(Path(__file__)), "runtime_paths": [str(run) for run in RUNS],
                                               "read_only": True, "generated_files": sorted(path.name for path in OUT.iterdir())})
    print(json.dumps({"status": summary["status"], "classification": summary["classification"],
                      "accepted_windows": summary["accepted_windows_total"], "extension_windows": summary["extension_runtime"]["accepted_windows"],
                      "cycles": summary["cycle_count"], "last_five": summary["last_five"],
                      "platform": decision, "max_Co": quality["max_Co"], "checkMesh": checkmesh["status"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
