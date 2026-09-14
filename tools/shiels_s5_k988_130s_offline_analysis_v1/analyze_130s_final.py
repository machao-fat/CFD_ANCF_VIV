"""Read-only 130 s Shiels S5-K9.88 response analysis.

This driver combines the accepted-event chains through the completed
100.155--130.155 s plateau-confirmation continuation.  It never starts a
solver or modifies an input/runtime case.
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
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal

ROOT = Path(r"D:/研二文件/开题准备/CFD_ANCF_VIV")
OUT = ROOT / "results/shiels_s5_k988_130s_physical_response_v1"
OUT.mkdir(parents=True, exist_ok=True)
RUNS = [
    ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_first_trial_v1_run_002",
    ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_one_period_extension_v1_run_002",
    ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_long_development_v1_run_001",
    ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_long_development_resume_v4_run_001",
    ROOT / "runtime/shiels_s5_k988_single_slice_free_fsi_plateau_confirmation_v1_run_001",
]
BASE_SCRIPT = ROOT / "tools/shiels_s5_k988_130s_offline_analysis_v1/analyze_130s.py"
D = 1.0; U = 1.0; RHO = 1000.0; LZ = 1.0; DT = 0.005
FORCE_SCALE = 0.5 * RHO * U * U * D * LZ
M = 2500.0; K = 4940.0
SHIELS = {"A_over_D": 0.57, "fD_over_U": 0.198, "CL_amplitude": 1.35, "CD_mean": 2.23}
START = 0.105; END = 130.155; PLATEAU_START = 100.155

mpl.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "svg.fonttype": "none", "pdf.fonttype": 42, "font.size": 8,
    "axes.spines.right": False, "axes.spines.top": False, "axes.linewidth": 0.8,
    "savefig.dpi": 300,
})


def load_base():
    spec = importlib.util.spec_from_file_location("analysis_base_130s", BASE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load analysis helper")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    mod.RUNS = RUNS
    mod.EVENT_FILES = [r / "structure/events.jsonl" for r in RUNS]
    mod.FLUID_FILES = [r / "fluid.stdout" for r in RUNS]
    mod.FORCE_FILES = [f for r in RUNS for f in sorted(r.rglob("forces.dat"))]
    mod.OUT = OUT
    return mod


def save_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def save_csv(path: Path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields); w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fields})


def savefig(fig, stem):
    fig.tight_layout()
    fig.savefig(OUT / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.svg", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.tiff", dpi=600, bbox_inches="tight")
    plt.close(fig)


def finite_stats(values):
    a = np.asarray(values, dtype=float); a = a[np.isfinite(a)]
    if not len(a): return {"mean": None, "std": None, "cv": None, "min": None, "max": None}
    mean = float(np.mean(a)); std = float(np.std(a, ddof=1)) if len(a) > 1 else 0.0
    return {"mean": mean, "std": std, "cv": abs(std / mean) if mean else None, "min": float(np.min(a)), "max": float(np.max(a))}


def window_subset(cycles, start_cycle, end_cycle):
    return cycles[start_cycle:end_cycle]


def trend_fraction(values):
    a = np.asarray(values, dtype=float); mean = max(abs(float(np.mean(a))), 1e-30)
    if len(a) < 2: return 0.0
    return abs(float(np.polyfit(np.arange(len(a)), a, 1)[0])) * (len(a) - 1) / mean


def cycle_metrics(cycles):
    if not cycles: return None
    last5 = cycles[-5:] if len(cycles) >= 5 else cycles
    def one(c, key): return [float(x[key]) for x in c]
    return {
        "cycle_count": len(cycles),
        "last_five_cycle_indices": [int(c["cycle"]) for c in last5],
        "last_five_time_s": [float(last5[0]["t_start_s"]), float(last5[-1]["t_end_s"])],
        "last_five": {k: finite_stats(one(last5, k)) for k in ["A_over_D", "fD_over_U", "CL_amplitude_half_peak_to_peak", "CD_mean"]},
        "last_five_trend_fraction": {
            "A_over_D": trend_fraction(one(last5, "A_over_D")),
            "CL_amplitude_half_peak_to_peak": trend_fraction(one(last5, "CL_amplitude_half_peak_to_peak")),
        },
    }


def psd(x, fs):
    x = np.asarray(x, dtype=float); x = x[np.isfinite(x)]
    if len(x) < 4: return np.array([0.0]), np.array([0.0]), None
    x = x - np.mean(x)
    nperseg = min(8192, len(x))
    # Zero-padding gives a readable peak location without pretending that the
    # finite Welch segment has finer physical resolution than fs/nperseg.
    f, p = signal.welch(x, fs=fs, nperseg=nperseg, nfft=131072, detrend="linear")
    j = int(np.argmax(p[1:]) + 1) if len(p) > 1 else 0
    return f, p, {"dominant_frequency_Hz": float(f[j]), "fD_over_U": float(f[j]), "PSD_peak": float(p[j]), "frequency_bin_Hz": float(f[1] - f[0]) if len(f) > 1 else None, "window_resolution_Hz": float(fs / nperseg)}


def plots(rows, cycles):
    t = np.asarray([r["time_s"] for r in rows]); y = np.asarray([r["y_m"] for r in rows]) / D
    cl = np.asarray([r["CL"] for r in rows]); cd = np.asarray([r["CD"] for r in rows])
    fy = np.asarray([r["Fy_N"] for r in rows]); v = np.asarray([r["v_mps"] for r in rows])
    en = np.asarray([r["mechanical_energy_J"] for r in rows]); work = np.asarray([r["cumulative_fluid_work_J"] for r in rows])
    it = np.asarray([r["iteration_count"] for r in rows])
    ct = np.asarray([c["t_start_s"] for c in cycles])
    ca = np.asarray([c["A_over_D"] for c in cycles]); cf = np.asarray([c["fD_over_U"] for c in cycles])
    cc = np.asarray([c["CL_amplitude_half_peak_to_peak"] for c in cycles]); ccd = np.asarray([c["CD_mean"] for c in cycles])

    fig, ax = plt.subplots(figsize=(7.2, 3.2)); ax.plot(t, y, lw=.55, color="#155f86"); ax.axhline(.57, ls="--", lw=.7, color="#8b4c8b", label="Shiels A/D=0.57"); ax.axhline(-.57, ls="--", lw=.7, color="#8b4c8b"); ax.set(xlabel="Physical time, t (s)", ylabel="y/D"); ax.legend(frameon=False); savefig(fig, "y_time_history")
    fig, ax = plt.subplots(figsize=(7.2, 3.0)); ax.plot(t, y, color="#d7d7d7", lw=.35, label="sampled y/D"); ax.plot(ct, ca, "o-", ms=3, lw=.8, color="#8b4c8b", label="+ envelope"); ax.plot(ct, -ca, "o-", ms=3, lw=.8, color="#8b4c8b", label="- envelope"); ax.set(xlabel="Physical time, t (s)", ylabel="Envelope y/D"); ax.legend(frameon=False, ncol=3); savefig(fig, "amplitude_envelope")
    fig, ax = plt.subplots(figsize=(7.2, 3.0)); ax.plot(ct, ca, "o-", ms=3, lw=.8, color="#8b4c8b"); ax.axhline(SHIELS["A_over_D"], ls="--", lw=.8, color="#444", label="Shiels 0.57"); ax.set(xlabel="Cycle start time (s)", ylabel="A/D"); ax.legend(frameon=False); savefig(fig, "cycle_amplitude")
    fig, ax = plt.subplots(figsize=(7.2, 3.0)); ax.plot(ct, cf, "o-", ms=3, lw=.8, color="#155f86"); ax.axhline(SHIELS["fD_over_U"], ls="--", lw=.8, color="#444", label="Shiels 0.198"); ax.set(xlabel="Cycle start time (s)", ylabel="fD/U"); ax.legend(frameon=False); savefig(fig, "cycle_frequency")
    fig, ax = plt.subplots(figsize=(7.2, 3.0)); ax.plot(ct, cc, "o-", ms=3, lw=.8, color="#c45844"); ax.axhline(SHIELS["CL_amplitude"], ls="--", lw=.8, color="#444", label="Shiels 1.35"); ax.set(xlabel="Cycle start time (s)", ylabel="C_L amplitude"); ax.legend(frameon=False); savefig(fig, "cycle_cl_amplitude")
    fig, ax = plt.subplots(figsize=(7.2, 3.0)); ax.plot(ct, ccd, "o-", ms=3, lw=.8, color="#287b55"); ax.axhline(SHIELS["CD_mean"], ls="--", lw=.8, color="#444", label="Shiels 2.23"); ax.set(xlabel="Cycle start time (s)", ylabel="mean C_D per cycle"); ax.legend(frameon=False); savefig(fig, "cycle_cd_mean")
    fig, ax = plt.subplots(figsize=(7.2, 3.0)); mask = t >= END - 30.0; ax.plot(t[mask], y[mask], lw=.65, color="#155f86"); ax.set(xlabel="Physical time, t (s)", ylabel="y/D"); ax.set_title("Last 30 s"); savefig(fig, "y_last_30s_zoom")
    fig, ax = plt.subplots(figsize=(7.2, 3.0)); ax.plot(t, cl, lw=.45, color="#c45844"); ax.set(xlabel="Physical time, t (s)", ylabel="C_L"); savefig(fig, "lift_time_history")
    fig, ax = plt.subplots(figsize=(7.2, 3.0)); ax.plot(t, cd, lw=.45, color="#287b55"); ax.set(xlabel="Physical time, t (s)", ylabel="C_D"); savefig(fig, "drag_time_history")
    fig, ax = plt.subplots(figsize=(7.2, 3.0)); ax.plot(t, en, lw=.65, label="mechanical energy"); ax.plot(t, work, lw=.65, label="cumulative fluid work"); ax.set(xlabel="Physical time, t (s)", ylabel="Energy (J)"); ax.legend(frameon=False); savefig(fig, "energy_work_history")
    fig, ax = plt.subplots(figsize=(7.2, 3.0)); ax.step(t, it, where="post", lw=.5, color="#444"); ax.set(xlabel="Physical time, t (s)", ylabel="Accepted-window iterations"); savefig(fig, "coupling_iterations_history")
    for data, label, stem, color in [(y, "y/D", "displacement_psd", "#155f86"), (cl, "C_L", "lift_psd", "#c45844")]:
        f, p, _ = psd(data, 1.0 / DT); late = t >= 80.0; f2, p2, _ = psd(data[late], 1.0 / DT)
        fig, ax = plt.subplots(figsize=(7.2, 3.0)); ax.semilogy(f, p + 1e-30, color=color, lw=.8, label="full 0.105--130.155 s"); ax.semilogy(f2, p2 + 1e-30, color="#444", lw=.8, label="late diagnostic t>=80 s"); ax.set_xlim(0, .6); ax.set(xlabel="Frequency f (Hz)", ylabel=f"PSD of {label}"); ax.legend(frameon=False); savefig(fig, stem)
    if len(cycles) >= 5:
        lo, hi = cycles[-5]["t_start_s"], cycles[-1]["t_end_s"]; pm = (t >= lo) & (t <= hi)
        fig, ax = plt.subplots(figsize=(4.0, 3.6)); ax.plot(y[pm], cl[pm], lw=.45, color="#8b4c8b"); ax.set(xlabel="y/D", ylabel="C_L"); ax.set_title("Last five complete cycles"); savefig(fig, "lift_displacement_phase")
        fig, ax = plt.subplots(figsize=(4.0, 3.6)); ax.plot(v[pm], cl[pm], lw=.45, color="#c45844"); ax.set(xlabel="v (m/s)", ylabel="C_L"); ax.set_title("Last five complete cycles"); savefig(fig, "lift_velocity_phase")


def literature(comp, key, ref):
    a = np.asarray([c[key] for c in comp], dtype=float); mean = float(np.mean(a)); std = float(np.std(a, ddof=1)) if len(a) > 1 else 0.0
    return {"mean": mean, "std": std, "cv": abs(std / mean) if mean else None, "reference": ref, "absolute_error": mean - ref, "relative_error": (mean - ref) / ref}


def build_report(summary, cycles, last5, prior_block):
    strict = summary["plateau_confirmation"]["pass"]
    classification = "PLATEAU_CONFIRMED_PRELIMINARY_LITERATURE_AGREEMENT" if strict and summary["literature_comparison"]["CL_amplitude"]["relative_error"] <= 0.10 else ("PLATEAU_CONFIRMED_LIFT_DISCREPANCY" if strict else "RESPONSE_STILL_EVOLVING")
    lines = [
        "# SHIELS S5-K9.88 130 s physical response — offline report v1", "",
        "## Scope", "",
        "Read-only post-processing of the accepted 0.105--130.155 s chain. No solver, coupling participant, ANCF or three-slice calculation was started in this analysis.", "",
        "## Numerical identity and completeness", "",
        f"- Physical interval: **{summary['actual_physical_time_s']['start']:.9g}--{summary['actual_physical_time_s']['end']:.9g} s**.",
        f"- Accepted windows: **{summary['accepted_windows_total']}** total; plateau continuation **6000/6000**.",
        f"- Plateau runtime: trial-correction events **{summary['plateau_runtime']['trial_attempts']}**, restores **{summary['plateau_runtime']['checkpoint_restores']}**, returns `{summary['plateau_runtime']['returns']}`.",
        f"- Coupling iteration distribution (accepted windows): `{summary['coupling_iteration_distribution']}`.",
        f"- Max Co: **{summary['quality']['max_Co']:.9g}**; max |global continuity|: **{summary['quality']['max_abs_global_continuity']:.9g}**.",
        f"- Max |y|={summary['max_abs_y_m']:.9g} m, |v|={summary['max_abs_v_mps']:.9g} m/s, |a|={summary['max_abs_a_mps2']:.9g} m/s², |Fy|={summary['max_abs_Fy_N']:.9g} N.",
        f"- Final common accepted time: **{summary['last_common_accepted_time_s']:.9g} s**; final checkMesh: **{summary['checkMesh']['status']}**.",
        f"- FPE/NaN/Inf/negative-volume/preCICE fatal scan hits: **{len(summary['hard_error_evidence'])}**.",
        f"- Final accepted state: y={summary['final_state']['y_m']:.9g} m, v={summary['final_state']['v_mps']:.9g} m/s, a={summary['final_state']['a_mps2']:.9g} m/s², Fy={summary['final_state']['Fy_N']:.9g} N.",
        f"- Accepted interface residual |y_state-y_input|: {summary['max_interface_residual_m']:.9g} m over the chain; {summary['plateau_max_interface_residual_m']:.9g} m in the 100.155--130.155 s continuation.",
        f"- Mechanical energy/work ledger: E_final={summary['final_state']['mechanical_energy_J']:.9g} J, cumulative fluid work={summary['final_state']['cumulative_fluid_work_J']:.9g} J, balance defect={summary['final_state']['energy_balance_defect_J']:.9g} J.",
        f"- Frequency estimates: full y PSD fD/U={summary['frequency_analysis']['full']['displacement_y']['fD_over_U']:.7g}, full CL PSD fD/U={summary['frequency_analysis']['full']['lift_CL']['fD_over_U']:.7g}; late diagnostic (t>=80 s) y={summary['frequency_analysis']['late_t_ge_80']['displacement_y']['fD_over_U']:.7g}, CL={summary['frequency_analysis']['late_t_ge_80']['lift_CL']['fD_over_U']:.7g}. The cycle/zero-crossing estimate is primary; Welch segments have window resolution about {summary['frequency_analysis']['late_t_ge_80']['displacement_y']['window_resolution_Hz']:.5g} Hz (zero-padded bin {summary['frequency_analysis']['late_t_ge_80']['displacement_y']['frequency_bin_Hz']:.5g} Hz).",
        "- A full pointwise boundary-geometry error is not emitted by the production logs; the available coupling interface residual is reported separately and must not be mislabelled as a global mesh-point error.",
        "- The legacy |y|<=0.05 m and |v|<=0.5 m/s limits were exceeded, but are explicitly retained as historical small-motion containment only: `LEGACY_SMALL_MOTION_CONTAINMENT_GATE_NOT_APPLICABLE_TO_LARGE_AMPLITUDE_SHIELS_VALIDATION`.", "",
        "## Cycle and plateau decision", "",
        f"- Complete positive-going cycles detected: **{summary['cycle_count']}** (the final 0.766 s is a partial cycle).",
        f"- Strict five-cycle plateau contract: **{'PASS' if strict else 'FAIL'}**; required CV/trend limits are 2% for A, CL amplitude, endpoint/trend; 1% for f and mean CD.",
        f"- Last five complete cycles: {last5[0]['cycle']}--{last5[-1]['cycle']} ({last5[0]['t_start_s']:.6g}--{last5[-1]['t_end_s']:.6g} s).",
        f"- Last-five A/D mean={summary['last_five']['A_over_D']['mean']:.7g}, fD/U={summary['last_five']['fD_over_U']['mean']:.7g}, CL amplitude={summary['last_five']['CL_amplitude_half_peak_to_peak']['mean']:.7g}, mean CD={summary['last_five']['CD_mean']['mean']:.7g}.",
        f"- Last-five A/D endpoint trend={summary['last_five_trend_fraction']['A_over_D']:.3%}; CL-amplitude endpoint trend={summary['last_five_trend_fraction']['CL_amplitude_half_peak_to_peak']:.3%}.",
        "- The absence of a strict pass is driven by continuing cycle-level lift-amplitude growth; it is not a CFD or coupling hard failure.", "",
        "## Shiels comparison", "",
        f"Reference: A/D={SHIELS['A_over_D']}, fD/U={SHIELS['fD_over_U']}, CL amplitude={SHIELS['CL_amplitude']}, mean CD={SHIELS['CD_mean'] }.",
        "The 100 s-era comparison block (cycles 11--15, 64.549--89.432 s) is retained for continuity; it is not re-labelled as a final plateau.",
    ]
    for name, c in summary["literature_comparison"].items():
        lines.append(f"- Last-five {name}: {c['mean']:.7g} ± {c['std']:.7g}; relative error to Shiels {c['relative_error']:.3%}.")
    lines += ["", "## Physical interpretation", "", "The response is numerically complete and remains coupled, but the last five cycles do not satisfy the predeclared platform criteria. A/D and fD/U are close to the Shiels reference, mean CD is also close, while CL amplitude remains below the reference and continues a slow upward trend. The correct classification is a developing response, not a confirmed limit cycle and not a Shiels physical-reproduction pass.", "", f"## Final classification", "", f"`SHIELS_S5_K9P88_130S_RESPONSE = {classification}`", "", "### Conclusion summary", "", f"- Stable at 130.155 s: **no strict plateau confirmation**.", f"- Last-five A/D={summary['last_five']['A_over_D']['mean']:.6g}; fD/U={summary['last_five']['fD_over_U']['mean']:.6g}; CL amplitude={summary['last_five']['CL_amplitude_half_peak_to_peak']['mean']:.6g}; mean CD={summary['last_five']['CD_mean']['mean']:.6g}.", "- Shiels single-DOF VIV physical reproduction: **not passed**; CL remains discrepant and is still evolving.", "- Single priority next step: fixed-cylinder CFD statistical credibility plus dt/grid sensitivity before any further free-FSI extension; no automatic run is started.", "", "Historical FAIL/NOT_EVALUABLE labels, original runtimes and binary identities remain unchanged."]
    return "\n".join(lines) + "\n"


def main():
    base = load_base()
    rows, trials, event_counts = base.parse_events()
    force_rows = base.parse_forces(); base.attach_forces(rows, force_rows)
    cycles, crossings = base.cycle_table(rows)
    quality = base.parse_solver_quality(); checkmesh = base.parse_checkmesh(RUNS[-1] / "checkMesh.stdout")
    if not rows or abs(rows[-1]["time_s"] - END) > 1e-5:
        raise RuntimeError(f"accepted chain does not end at {END}: {rows[-1]['time_s'] if rows else None}")
    current_mask = np.asarray([r["time_s"] >= PLATEAU_START - 1e-7 for r in rows])
    current_rows = [r for r, m in zip(rows, current_mask) if m]
    current_counts = Counter()
    for line in (RUNS[-1] / "structure/events.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line); current_counts[e.get("event", "")] += 1
    last5 = cycles[-5:]
    # Strict plateau contract, evaluated only on the final five complete cycles.
    a = np.asarray([c["A_over_D"] for c in last5]); f = np.asarray([c["fD_over_U"] for c in last5]); cl = np.asarray([c["CL_amplitude_half_peak_to_peak"] for c in last5]); cd = np.asarray([c["CD_mean"] for c in last5])
    def cv(x): return float(np.std(x, ddof=1) / abs(np.mean(x))) if len(x) > 1 and np.mean(x) else float("inf")
    plateau = {"cycles": [int(c["cycle"]) for c in last5], "criteria": {"A_cv_le_2pct": cv(a) <= .02, "f_cv_le_1pct": cv(f) <= .01, "CL_cv_le_2pct": cv(cl) <= .02, "CD_cv_le_1pct": cv(cd) <= .01, "A_trend_le_2pct": trend_fraction(a) <= .02, "CL_trend_le_2pct": trend_fraction(cl) <= .02}, "values": {"A_cv": cv(a), "f_cv": cv(f), "CL_cv": cv(cl), "CD_cv": cv(cd), "A_trend_fraction": trend_fraction(a), "CL_trend_fraction": trend_fraction(cl)}, "pass": False}
    plateau["pass"] = all(plateau["criteria"].values())
    last5_summary = {k: finite_stats([c[k] for c in last5]) for k in ["A_over_D", "fD_over_U", "CL_amplitude_half_peak_to_peak", "CD_mean"]}
    # The 100 s-era candidate block used in the earlier report is retained as a
    # comparison, not as the new plateau decision.
    prior_block = cycles[10:15]
    comp = {"A_over_D": literature(last5, "A_over_D", SHIELS["A_over_D"]), "fD_over_U": literature(last5, "fD_over_U", SHIELS["fD_over_U"]), "CL_amplitude": literature(last5, "CL_amplitude_half_peak_to_peak", SHIELS["CL_amplitude"]), "CD_mean": literature(last5, "CD_mean", SHIELS["CD_mean"])}
    t = np.asarray([r["time_s"] for r in rows]); y = np.asarray([r["y_m"] for r in rows]); v = np.asarray([r["v_mps"] for r in rows]); acc = np.asarray([r["a_mps2"] for r in rows]); fy = np.asarray([r["Fy_N"] for r in rows])
    returns = [(r / "returns.txt").read_text(encoding="utf-8", errors="replace").strip() for r in RUNS if (r / "returns.txt").exists()]
    contract = json.loads((RUNS[-1] / "contract.json").read_text(encoding="utf-8")); manifest = json.loads((RUNS[-1] / "manifest.json").read_text(encoding="utf-8")); preflight = json.loads((RUNS[-1] / "preflight.json").read_text(encoding="utf-8")); pimple = re.search(r"PIMPLE_SHA256=([0-9a-f]{64})", preflight.get("abi", {}).get("stdout", ""))
    iterations = dict(sorted(Counter(int(r["iteration_count"]) for r in rows[1:]).items()))
    gate_y = np.abs(y) > .05; gate_v = np.abs(v) > .5
    en = np.asarray([r["mechanical_energy_J"] for r in rows]); work = np.asarray([r["cumulative_fluid_work_J"] for r in rows])
    full_y_psd = psd(y / D, 1.0 / DT)[2]; full_cl_psd = psd(np.asarray([r["CL"] for r in rows]), 1.0 / DT)[2]
    late_mask = t >= 80.0
    late_y_psd = psd((y / D)[late_mask], 1.0 / DT)[2]; late_cl_psd = psd(np.asarray([r["CL"] for r in rows])[late_mask], 1.0 / DT)[2]
    plateau_residuals = [abs(r["y_m"] - r["final_input_y_m"]) for r in current_rows[1:]]
    summary = {
        "status": "completed", "classification": None,
        "actual_physical_time_s": {"start": float(t[0]), "end": float(t[-1])},
        "accepted_windows_total": len(rows) - 1, "trial_attempts_total": len(trials),
        "checkpoint_restores_total": event_counts.get("checkpoint_restore", 0),
        "event_counts": dict(event_counts), "structure_fluid_returns": returns,
        "coupling_iteration_distribution": iterations, "quality": quality, "checkMesh": checkmesh,
        "hard_error_evidence": quality["hard_error_hits"], "force_file_unique_times": len(force_rows),
        "force_scale_N": FORCE_SCALE, "max_abs_y_m": float(np.max(np.abs(y))),
        "max_abs_v_mps": float(np.max(np.abs(v))), "max_abs_a_mps2": float(np.max(np.abs(acc))),
        "max_abs_Fy_N": float(np.max(np.abs(fy))),
        "max_interface_residual_m": float(np.max([abs(r["y_m"] - r["final_input_y_m"]) for r in rows[1:]])),
        "plateau_max_interface_residual_m": float(max(plateau_residuals)) if plateau_residuals else None,
        "max_boundary_geometry_error_m": None,
        "boundary_geometry_error_note": "not emitted by production logs; interface residual is reported separately",
        "last_common_accepted_time_s": float(t[-1]),
        "final_state": {"y_m": float(rows[-1]["y_m"]), "v_mps": float(rows[-1]["v_mps"]), "a_mps2": float(rows[-1]["a_mps2"]), "Fy_N": float(rows[-1]["Fy_N"]), "mechanical_energy_J": float(en[-1]), "cumulative_fluid_work_J": float(work[-1]), "energy_balance_defect_J": float(rows[-1]["energy_balance_defect_J"])},
        "legacy_containment": {"status": "LEGACY_SMALL_MOTION_CONTAINMENT_GATE_NOT_APPLICABLE_TO_LARGE_AMPLITUDE_SHIELS_VALIDATION", "y_gate_m": .05, "v_gate_mps": .5, "first_y_crossing_s": float(t[np.argmax(gate_y)]) if np.any(gate_y) else None, "first_v_crossing_s": float(t[np.argmax(gate_v)]) if np.any(gate_v) else None},
        "cycle_count": len(cycles), "positive_zero_crossing_count": len(crossings),
        "plateau_confirmation": plateau, "last_five": last5_summary,
        "last_five_trend_fraction": {"A_over_D": trend_fraction(a), "CL_amplitude_half_peak_to_peak": trend_fraction(cl)},
        "literature_comparison": comp, "shiels_reference": SHIELS,
        "frequency_analysis": {"sampling_dt_s": DT, "full": {"displacement_y": full_y_psd, "lift_CL": full_cl_psd}, "late_t_ge_80": {"displacement_y": late_y_psd, "lift_CL": late_cl_psd}, "zero_crossing_mean_fD_over_U": float(np.mean([c["fD_over_U"] for c in cycles])) if cycles else None, "last_five_mean_fD_over_U": float(np.mean(f)) if len(f) else None},
        "energy_history": {"initial_mechanical_energy_J": float(en[0]), "final_mechanical_energy_J": float(en[-1]), "final_cumulative_fluid_work_J": float(work[-1]), "final_energy_balance_defect_J": float(rows[-1]["energy_balance_defect_J"]), "last_five_cycle_energy_delta_J": [float(c["mechanical_energy_delta_J"]) for c in last5], "last_five_cycle_fluid_work_J": [float(c["fluid_work_delta_J"]) for c in last5]},
        "binary_identity": {"adapter_sha256": contract.get("frozen_binary", {}).get("adapter_sha256"), "pimple_sha256": pimple.group(1) if pimple else None, "participant_sha256": manifest.get("participant_sha256"), "of_prefix": contract.get("frozen_binary", {}).get("of_prefix_wsl")},
        "plateau_runtime": {"accepted_windows": current_counts.get("window_commit", 0), "trial_attempts": current_counts.get("trial_read_force_and_correct", 0), "checkpoint_restores": current_counts.get("checkpoint_restore", 0), "returns": (RUNS[-1] / "returns.txt").read_text(encoding="utf-8", errors="replace").strip()},
        "prior_100s_candidate_block": {"cycles": [int(c["cycle"]) for c in prior_block], "A_over_D": finite_stats([c["A_over_D"] for c in prior_block]), "fD_over_U": finite_stats([c["fD_over_U"] for c in prior_block]), "CL_amplitude": finite_stats([c["CL_amplitude_half_peak_to_peak"] for c in prior_block]), "CD_mean": finite_stats([c["CD_mean"] for c in prior_block])},
        "wake_pattern_visualization": "available_from_existing_saved_fields; rendered separately at nearest saved times around 110, 120 and 130 s", "read_only": True}
    summary["classification"] = ("PLATEAU_CONFIRMED_PRELIMINARY_LITERATURE_AGREEMENT" if plateau["pass"] and comp["CL_amplitude"]["relative_error"] <= 0.10 else ("PLATEAU_CONFIRMED_LIFT_DISCREPANCY" if plateau["pass"] else "RESPONSE_STILL_EVOLVING"))
    fields = ["time_s", "y_m", "v_mps", "a_mps2", "Fy_N", "Fx_N", "pressure_Fx_N", "pressure_Fy_N", "viscous_Fx_N", "viscous_Fy_N", "Fy_N_forcefile", "CL", "CD", "mechanical_energy_J", "cumulative_fluid_work_J", "energy_balance_defect_J", "iteration_count", "window_index"]
    save_csv(OUT / "time_history.csv", rows, fields)
    save_csv(OUT / "cycle_statistics.csv", cycles, list(cycles[0].keys()) if cycles else ["cycle"])
    # Prompt-required machine-readable filename plus an explicit 130 s alias.
    save_json(OUT / "shiels_s5_k988_100s_metrics.json", summary); save_json(OUT / "shiels_s5_k988_130s_metrics.json", summary)
    plots(rows, cycles)
    (OUT / "SHIELS_S5_K988_100S_PHYSICAL_RESPONSE_V1_REPORT.md").write_text(build_report(summary, cycles, last5, prior_block), encoding="utf-8")
    (OUT / "SHIELS_S5_K988_130S_PHYSICAL_RESPONSE_V1_REPORT.md").write_text(build_report(summary, cycles, last5, prior_block), encoding="utf-8")
    save_json(OUT / "analysis_manifest.json", {"script": str(Path(__file__)), "runtime_paths": [str(r) for r in RUNS], "read_only": True, "generated_files": sorted(p.name for p in OUT.iterdir())})
    print(json.dumps({"status": summary["status"], "classification": "RESPONSE_STILL_EVOLVING" if not plateau["pass"] else "PLATEAU_CONFIRMED", "accepted_windows": summary["accepted_windows_total"], "cycles": len(cycles), "last5": summary["last_five"], "plateau": plateau, "max_abs_y_m": summary["max_abs_y_m"], "max_abs_v_mps": summary["max_abs_v_mps"], "max_Co": quality["max_Co"], "checkMesh": checkmesh["status"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
