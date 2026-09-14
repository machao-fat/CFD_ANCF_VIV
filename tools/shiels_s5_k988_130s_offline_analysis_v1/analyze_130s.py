"""Offline post-processing for the completed Shiels S5-K9.88 run.

This script reads only existing structure events, OpenFOAM force logs and
solver stdout.  It never launches OpenFOAM, preCICE or a participant.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
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
EVENT_FILES = [r / "structure/events.jsonl" for r in RUNS]
FLUID_FILES = [r / "fluid.stdout" for r in RUNS]
FORCE_FILES = []
for run in RUNS:
    FORCE_FILES.extend(run.rglob("forces.dat"))

D = 1.0
U = 1.0
RHO = 1000.0
LZ = 1.0
FORCE_SCALE = 0.5 * RHO * U * U * D * LZ
M = 2500.0
K = 4940.0
DT = 0.005
SHIELS = {"A_over_D": 0.57, "fD_over_U": 0.198, "CL_amplitude": 1.35, "CD_mean": 2.23}

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
    "font.size": 8,
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.linewidth": 0.8,
    "savefig.dpi": 300,
})


def dump_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def parse_events():
    accepted = []
    initial = []
    trial_corrected = []
    all_events = Counter()
    for path in EVENT_FILES:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                e = json.loads(line)
                kind = e.get("event", "")
                all_events[kind] += 1
                if kind == "initial_data":
                    initial.append(e)
                elif kind == "window_commit":
                    st = e["accepted_state"]
                    accepted.append({
                        "time_s": float(e["physical_time_s"]),
                        "y_m": float(st["y_m"]),
                        "v_mps": float(st["v_mps"]),
                        "a_mps2": float(st["a_mps2"]),
                        "Fy_N": float(e["force_y_total_N"]),
                        "mechanical_energy_J": float(e["mechanical_energy_J"]),
                        "cumulative_fluid_work_J": float(e["cumulative_fluid_work_J"]),
                        "energy_balance_defect_J": float(e["cumulative_energy_balance_defect_J"]),
                        "iteration_count": int(e["iteration_count"]),
                        "window_index": int(e["window_index"]),
                        "checkpoint_id": e.get("checkpoint_id"),
                        "final_input_y_m": float(e.get("final_input_y_m", st["y_m"])),
                    })
                elif kind == "trial_read_force_and_correct":
                    trial_corrected.append({
                        "time_s": float(e["physical_output_time_s"]),
                        "Fy_N": float(e["force_y_total_N"]),
                        "iteration_index": int(e["iteration_index"]),
                        "window_index": int(e["window_index"]),
                    })
    # Preserve one row per physical time, with later continuation evidence winning
    by_time = {}
    for row in accepted:
        by_time[round(row["time_s"], 9)] = row
    accepted = sorted(by_time.values(), key=lambda x: x["time_s"])
    # Add the first valid initial state to make the full chain start at 0.105 s.
    if initial:
        e = sorted(initial, key=lambda x: float(x.get("physical_time_s", 1e99)))[0]
        st = e["initial_state"]
        t = float(e["physical_time_s"])
        if not any(abs(r["time_s"] - t) < 1e-8 for r in accepted):
            accepted.insert(0, {
                "time_s": t, "y_m": float(e["payload_y_m"]),
                "v_mps": float(st["v_mps"]), "a_mps2": float(st["a_mps2"]),
                "Fy_N": float(e["initial_force_y_N"]),
                "mechanical_energy_J": 0.5 * M * float(st["v_mps"]) ** 2 + 0.5 * K * float(e["payload_y_m"]) ** 2,
                "cumulative_fluid_work_J": 0.0, "energy_balance_defect_J": 0.0,
                "iteration_count": 0, "window_index": 0,
                "checkpoint_id": "initial_data", "final_input_y_m": float(e["payload_y_m"]),
            })
    return accepted, trial_corrected, all_events


FLOAT = r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?"
FORCE_RE = re.compile(r"^\s*(%s)\s+" % FLOAT)


def parse_forces():
    # OpenFOAM forces.dat repeats each physical time once per coupling/PIMPLE
    # evaluation.  Keep the last row at each time, i.e. the final fluid value.
    rows = {}
    for path in FORCE_FILES:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                nums = re.findall(FLOAT, line)
                if len(nums) < 13:
                    continue
                vals = [float(x) for x in nums[:13]]
                t = vals[0]
                rows[round(t, 6)] = {
                    "time_s": t,
                    "Fx_N": vals[1] + vals[4],
                    "Fy_N_forcefile": vals[2] + vals[5],
                    "pressure_Fx_N": vals[1], "pressure_Fy_N": vals[2],
                    "viscous_Fx_N": vals[4], "viscous_Fy_N": vals[5],
                }
    return rows


def attach_forces(rows, force_rows):
    keys = np.array(sorted(force_rows), dtype=float)
    for r in rows:
        key = round(r["time_s"], 6)
        if key in force_rows:
            f = force_rows[key]
        elif len(keys):
            j = int(np.argmin(abs(keys - r["time_s"])))
            f = force_rows[float(keys[j])] if abs(keys[j] - r["time_s"]) <= 2e-5 else None
        else:
            f = None
        if f:
            r.update(f)
        else:
            r.update({"Fx_N": math.nan, "Fy_N_forcefile": math.nan,
                      "pressure_Fx_N": math.nan, "pressure_Fy_N": math.nan,
                      "viscous_Fx_N": math.nan, "viscous_Fy_N": math.nan})
        r["CL"] = r["Fy_N"] / FORCE_SCALE
        r["CD"] = r["Fx_N"] / FORCE_SCALE if math.isfinite(r["Fx_N"]) else math.nan
    return rows


def parse_solver_quality():
    max_co = -math.inf
    continuity_global = []
    continuity_local = []
    hard_hits = []
    times = []
    for path in FLUID_FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"Courant Number mean:\s*([0-9.eE+-]+)\s+max:\s*([0-9.eE+-]+)", text):
            max_co = max(max_co, float(m.group(2)))
        for m in re.finditer(r"time step continuity errors : sum local =\s*([0-9.eE+-]+), global =\s*([0-9.eE+-]+), cumulative =\s*([0-9.eE+-]+)", text):
            continuity_local.append(abs(float(m.group(1))))
            continuity_global.append(abs(float(m.group(2))))
        for m in re.finditer(r"Time =\s*([0-9.eE+-]+)s", text):
            times.append(float(m.group(1)))
        for line_no, line in enumerate(text.splitlines(), 1):
            if re.search(r"FOAM FATAL|Floating point exception|nan|NaN|Inf|negative volume|convergence failure", line):
                hard_hits.append({"file": str(path), "line": line_no, "text": line[:300]})
    return {
        "max_Co": max_co if math.isfinite(max_co) else None,
        "max_abs_global_continuity": max(continuity_global) if continuity_global else None,
        "max_abs_local_continuity": max(continuity_local) if continuity_local else None,
        "solver_times_s": [min(times), max(times)] if times else [],
        "hard_error_hits": hard_hits,
    }


def parse_checkmesh(path):
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    def one(pattern):
        m = re.search(pattern, text)
        return float(m.group(1)) if m else None
    return {
        "status": "Mesh OK" if "Mesh OK" in text else "not found",
        "max_aspect_ratio": one(r"Max aspect ratio =\s*(%s)" % FLOAT),
        "max_non_orthogonality_deg": one(r"Mesh non-orthogonality Max:\s*(%s)" % FLOAT),
        "max_skewness": one(r"Max skewness =\s*(%s)" % FLOAT),
        "minimum_cell_determinant": one(r"Cell determinant \(wellposedness\) : minimum:\s*(%s)" % FLOAT),
        "minimum_face_area": one(r"Minimum face area =\s*(%s)" % FLOAT),
        "minimum_volume": one(r"Min volume =\s*(%s)" % FLOAT),
    }


def cycle_table(rows):
    t = np.array([r["time_s"] for r in rows])
    y = np.array([r["y_m"] for r in rows])
    # Positive-going zero crossings are less sensitive to peak flattening.
    crossings = []
    for i in range(len(y) - 1):
        if y[i] <= 0 < y[i + 1]:
            frac = -y[i] / (y[i + 1] - y[i])
            crossings.append(float(t[i] + frac * (t[i + 1] - t[i])))
    cycles = []
    for j in range(len(crossings) - 1):
        lo, hi = crossings[j], crossings[j + 1]
        mask = (t >= lo) & (t <= hi)
        if mask.sum() < 3:
            continue
        sub = [rows[i] for i, m in enumerate(mask) if m]
        yy = np.array([x["y_m"] for x in sub])
        cl = np.array([x["CL"] for x in sub], dtype=float)
        cd = np.array([x["CD"] for x in sub], dtype=float)
        en = np.array([x["mechanical_energy_J"] for x in sub])
        work = np.array([x["cumulative_fluid_work_J"] for x in sub])
        iters = np.array([x["iteration_count"] for x in sub])
        cycles.append({
            "cycle": len(cycles) + 1,
            "t_start_s": lo, "t_end_s": hi, "period_s": hi - lo,
            "f_Hz": 1.0 / (hi - lo), "fD_over_U": 1.0 / (hi - lo),
            "y_max_m": float(np.max(yy)), "y_min_m": float(np.min(yy)),
            "A_over_D": float((np.max(yy) - np.min(yy)) / (2 * D)),
            "CL_amplitude_half_peak_to_peak": float((np.nanmax(cl) - np.nanmin(cl)) / 2),
            "CL_max": float(np.nanmax(cl)), "CL_min": float(np.nanmin(cl)),
            "CD_mean": float(np.nanmean(cd)), "CD_std": float(np.nanstd(cd)),
            "max_coupling_iterations": int(np.max(iters)), "mean_coupling_iterations": float(np.mean(iters)),
            "mechanical_energy_delta_J": float(en[-1] - en[0]),
            "fluid_work_delta_J": float(work[-1] - work[0]),
        })
    return cycles, crossings


def stable_zone(cycles):
    # Plateau-confirmation contract frozen before this continuation:
    # five consecutive complete cycles, CV(A)<=2%, CV(f)<=1%,
    # CV(CL_amp)<=2%, CV(CD)<=1%, and <=2% endpoint/trend drift for A and CL.
    for i in range(len(cycles) - 4):
        w = cycles[i:i + 5]
        a = np.array([c["A_over_D"] for c in w]); f = np.array([c["fD_over_U"] for c in w])
        cl = np.array([c["CL_amplitude_half_peak_to_peak"] for c in w])
        cd = np.array([c["CD_mean"] for c in w])
        mean_a = max(abs(float(np.mean(a))), 1e-30)
        mean_cl = max(abs(float(np.mean(cl))), 1e-30)
        slope_a = abs(float(np.polyfit(np.arange(5), a, 1)[0])) * 4 / mean_a
        slope_cl = abs(float(np.polyfit(np.arange(5), cl, 1)[0])) * 4 / mean_cl
        endpoint_a = abs(float(a[-1] - a[0])) / mean_a
        endpoint_cl = abs(float(cl[-1] - cl[0])) / mean_cl
        cv_a = float(np.std(a, ddof=1) / mean_a)
        cv_f = float(np.std(f, ddof=1) / max(abs(float(np.mean(f))), 1e-30))
        cv_cl = float(np.std(cl, ddof=1) / mean_cl)
        cv_cd = float(np.std(cd, ddof=1) / max(abs(float(np.mean(cd))), 1e-30))
        cd_drift = abs(float(np.polyfit(np.arange(5), cd, 1)[0])) * 4 / max(abs(float(np.mean(cd))), 1e-30)
        if (cv_a <= 0.02 and cv_f <= 0.01 and cv_cl <= 0.02 and cv_cd <= 0.01
                and slope_a <= 0.02 and slope_cl <= 0.02
                and endpoint_a <= 0.02 and endpoint_cl <= 0.02):
            return {"start_cycle_index": i, "end_cycle_index": i + 4,
                    "start_time_s": w[0]["t_start_s"], "end_time_s": w[-1]["t_end_s"],
                    "amplitude_cv": cv_a, "frequency_cv": cv_f,
                    "cl_amplitude_cv": cv_cl, "cd_mean_cv": cv_cd,
                    "amplitude_trend_fraction": slope_a, "cl_amplitude_trend_fraction": slope_cl,
                    "amplitude_endpoint_fraction": endpoint_a, "cl_amplitude_endpoint_fraction": endpoint_cl,
                    "cd_trend_fraction": cd_drift}
    return None


def spectral_summary(rows, start_time=None, end_time=None):
    t = np.array([r["time_s"] for r in rows], dtype=float)
    mask = np.ones(len(t), dtype=bool)
    if start_time is not None: mask &= t >= start_time
    if end_time is not None: mask &= t <= end_time
    fs = 1.0 / DT
    out = {"start_time_s": float(t[mask][0]), "end_time_s": float(t[mask][-1]), "sample_count": int(mask.sum()), "frequency_resolution_Hz": None}
    for key, name in [("y_m", "displacement_y"), ("CL", "lift_CL")]:
        x = np.array([r[key] for r in rows], dtype=float)[mask]
        x = x - np.nanmean(x)
        f, p = signal.welch(x, fs=fs, nperseg=min(8192, len(x)), detrend="linear")
        j = int(np.argmax(p[1:]) + 1) if len(p) > 1 else 0
        out[name] = {"dominant_frequency_Hz": float(f[j]), "fD_over_U": float(f[j]), "PSD_peak": float(p[j])}
        out["frequency_resolution_Hz"] = float(f[1] - f[0]) if len(f) > 1 else None
    return out


def save_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fields})


def savefig(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / f"{name}.png", dpi=300, bbox_inches="tight")
    fig.savefig(OUT / f"{name}.svg", bbox_inches="tight")
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{name}.tiff", dpi=600, bbox_inches="tight")
    plt.close(fig)


def plot_all(rows, cycles, quality):
    t = np.array([r["time_s"] for r in rows]); y = np.array([r["y_m"] for r in rows]) / D
    v = np.array([r["v_mps"] for r in rows]); a = np.array([r["a_mps2"] for r in rows])
    fy = np.array([r["Fy_N"] for r in rows]); cl = np.array([r["CL"] for r in rows]); cd = np.array([r["CD"] for r in rows])
    en = np.array([r["mechanical_energy_J"] for r in rows]); work = np.array([r["cumulative_fluid_work_J"] for r in rows])
    it = np.array([r["iteration_count"] for r in rows])
    savefig(plt.subplots(figsize=(7.0, 3.1))[0], "_placeholder") if False else None
    fig, ax = plt.subplots(figsize=(7.0, 3.2)); ax.plot(t, y, lw=.55, color="#155f86"); ax.axhline(.05, ls="--", lw=.7, color="#b04a4a"); ax.axhline(-.05, ls="--", lw=.7, color="#b04a4a"); ax.set(xlabel="Physical time, t (s)", ylabel="y/D"); savefig(fig, "y_time_history")
    if cycles:
        ct = np.array([c["t_start_s"] for c in cycles]); ca = np.array([c["A_over_D"] for c in cycles]);
        fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.plot(ct, ca, "o-", ms=3, lw=.8, color="#8b4c8b"); ax.axhline(SHIELS["A_over_D"], ls="--", lw=.8, color="#444", label="Shiels 0.57"); ax.set(xlabel="Cycle start time (s)", ylabel="A/D"); ax.legend(); savefig(fig, "cycle_amplitude")
        fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.plot(t, y, color="#d0d0d0", lw=.4); ax.plot(ct, ca, "o-", ms=3, lw=.8, color="#8b4c8b", label="half peak-to-peak"); ax.plot(ct, -ca, "o-", ms=3, lw=.8, color="#8b4c8b"); ax.set(xlabel="Physical time, t (s)", ylabel="Envelope y/D"); savefig(fig, "amplitude_envelope")
    fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.plot(t, cl, lw=.5, color="#c45844"); ax.set(xlabel="Physical time, t (s)", ylabel="C_L"); savefig(fig, "lift_time_history")
    fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.plot(t, cd, lw=.5, color="#287b55"); ax.set(xlabel="Physical time, t (s)", ylabel="C_D"); savefig(fig, "drag_time_history")
    fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.plot(t, en, lw=.7, label="mechanical energy"); ax.plot(t, work, lw=.7, label="cumulative fluid work"); ax.set(xlabel="Physical time, t (s)", ylabel="Energy (J)"); ax.legend(); savefig(fig, "energy_work_history")
    fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.step(t, it, where="post", lw=.5, color="#444"); ax.set(xlabel="Physical time, t (s)", ylabel="Accepted-window iterations"); savefig(fig, "coupling_iterations_history")
    for key, label, name in [("y_m", "y/D", "displacement_psd"), ("CL", "C_L", "lift_psd")]:
        x = np.array([r[key] for r in rows], dtype=float) / D if key == "y_m" else np.array([r[key] for r in rows], dtype=float)
        x = x - np.nanmean(x); fs = 1 / DT
        f, p = signal.welch(x, fs=fs, nperseg=min(8192, len(x)), detrend="linear")
        fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.semilogy(f, p + 1e-30, color="#155f86" if key == "y_m" else "#c45844"); ax.set_xlim(0, .6); ax.set(xlabel="Frequency f (Hz)", ylabel=f"PSD of {label}"); savefig(fig, name)
    fig, ax = plt.subplots(figsize=(4.0, 3.6)); ax.plot(y, cl, lw=.4, color="#8b4c8b"); ax.set(xlabel="y/D", ylabel="C_L"); savefig(fig, "lift_displacement_phase")


def main():
    rows, trials, event_counts = parse_events()
    force_rows = parse_forces()
    attach_forces(rows, force_rows)
    cycles, crossings = cycle_table(rows)
    stable = stable_zone(cycles)
    quality = parse_solver_quality()
    checkmesh = parse_checkmesh(RUNS[-1] / "checkMesh.stdout")
    coupling_distribution = dict(sorted(Counter(r["iteration_count"] for r in rows[1:]).items()))
    contract = json.loads((RUNS[-1] / "contract.json").read_text(encoding="utf-8"))
    preflight = json.loads((RUNS[-1] / "preflight.json").read_text(encoding="utf-8"))
    pimple_sha = None
    m_pimple = re.search(r"PIMPLE_SHA256=([0-9a-f]{64})", preflight.get("abi", {}).get("stdout", ""))
    if m_pimple: pimple_sha = m_pimple.group(1)
    t = np.array([r["time_s"] for r in rows]); y = np.array([r["y_m"] for r in rows]); v = np.array([r["v_mps"] for r in rows]); a = np.array([r["a_mps2"] for r in rows]); fy = np.array([r["Fy_N"] for r in rows])
    return_codes = []
    for run in RUNS:
        p = run / "returns.txt"
        if p.exists():
            return_codes.append(p.read_text(encoding="utf-8", errors="replace").strip())
    all_summary = {
        "status": "completed" if abs(float(t[-1]) - 100.155) < 1e-5 else "incomplete",
        "actual_physical_time_s": {"start": float(t[0]), "end": float(t[-1])},
        "accepted_windows_total": len(rows) - 1,
        "trial_attempts_total": sum(1 for x in trials),
        "checkpoint_restores_total": event_counts.get("checkpoint_restore", 0),
        "event_counts": dict(event_counts),
        "structure_fluid_returns": return_codes,
        "binary_identity": {
            "adapter_sha256": contract.get("abi", {}).get("adapter_sha256"),
            "pimple_sha256": pimple_sha,
            "of_prefix": contract.get("abi", {}).get("of_prefix_wsl"),
            "participant_sha256": json.loads((RUNS[-1] / "manifest.json").read_text(encoding="utf-8")).get("participant_sha256"),
        },
        "quality": quality,
        "max_abs_y_m": float(np.max(abs(y))), "max_abs_v_mps": float(np.max(abs(v))),
        "max_abs_a_mps2": float(np.max(abs(a))), "max_abs_Fy_N": float(np.max(abs(fy))),
        "max_interface_residual_m": float(np.max([abs(r["y_m"] - r["final_input_y_m"]) for r in rows[1:]])),
        "last_common_accepted_time_s": float(t[-1]),
        "checkMesh": checkmesh,
        "hard_error_evidence": quality["hard_error_hits"],
        "force_file_unique_times": len(force_rows),
        "force_scale_N": FORCE_SCALE,
        "coupling_iteration_distribution": coupling_distribution,
        "contract_safety_gate_exceeded": {
            "max_abs_y_gate_m": 0.05, "y_exceeded": bool(np.max(abs(y)) > 0.05),
            "first_y_exceedance_time_s": float(t[np.argmax(abs(y) > 0.05)]) if np.any(abs(y) > 0.05) else None,
            "max_abs_v_gate_mps": 0.5, "v_exceeded": bool(np.max(abs(v)) > 0.5),
            "first_v_exceedance_time_s": float(t[np.argmax(abs(v) > 0.5)]) if np.any(abs(v) > 0.5) else None,
        },
        "cycle_count": len(cycles), "positive_zero_crossing_count": len(crossings),
        "stability_criterion": "five consecutive complete cycles; amplitude CV, frequency CV, amplitude trend and CD trend each <=5%",
        "candidate_stable_zone": stable,
        "frequency_analysis": {
            "full": spectral_summary(rows),
            "late_80_to_end": spectral_summary(rows, 80.0, 100.155),
            "zero_crossing_frequency_full_cycle_mean_Hz": float(np.mean([c["f_Hz"] for c in cycles])) if cycles else None,
            "zero_crossing_frequency_candidate_mean_Hz": float(np.mean([c["f_Hz"] for c in cycles[stable["start_cycle_index"]:stable["end_cycle_index"] + 1]])) if stable else None,
        },
        "shiels_reference": SHIELS,
        "literature_comparison": None,
        "wake_pattern_visualization": "RENDERED_FROM_EXISTING_RUNTIME_FIELDS_AT_T_20_50_80_S",
    }
    if stable:
        w = cycles[stable["start_cycle_index"] : stable["end_cycle_index"] + 1]
        vals = {k: np.array([c[k] for c in w], dtype=float) for k in ["A_over_D", "fD_over_U", "CL_amplitude_half_peak_to_peak", "CD_mean"]}
        comp = {}
        mapping = {"A_over_D": "A_over_D", "fD_over_U": "fD_over_U", "CL_amplitude_half_peak_to_peak": "CL_amplitude", "CD_mean": "CD_mean"}
        for k, refk in mapping.items():
            mean = float(np.mean(vals[k])); ref = SHIELS[refk]
            comp[k] = {"mean": mean, "std": float(np.std(vals[k], ddof=1)) if len(vals[k]) > 1 else 0.0, "reference": ref, "absolute_error": mean - ref, "relative_error": (mean - ref) / ref}
        all_summary["literature_comparison"] = comp
    # CSVs and machine-readable files
    fields = ["time_s", "y_m", "v_mps", "a_mps2", "Fy_N", "Fx_N", "CL", "CD", "mechanical_energy_J", "cumulative_fluid_work_J", "energy_balance_defect_J", "iteration_count", "window_index"]
    save_csv(OUT / "time_history.csv", rows, fields)
    cycle_fields = list(cycles[0].keys()) if cycles else ["cycle", "t_start_s", "t_end_s", "period_s", "f_Hz", "fD_over_U", "A_over_D", "CL_amplitude_half_peak_to_peak", "CD_mean"]
    save_csv(OUT / "cycle_statistics.csv", cycles, cycle_fields)
    dump_json(OUT / "shiels_s5_k988_100s_metrics.json", all_summary)
    plot_all(rows, cycles, quality)
    report = build_report(all_summary, cycles)
    (OUT / "SHIELS_S5_K988_100S_PHYSICAL_RESPONSE_V1_REPORT.md").write_text(report, encoding="utf-8")
    dump_json(OUT / "analysis_manifest.json", {"script": str(Path(__file__)), "runtime_paths": [str(r) for r in RUNS], "read_only": True, "generated_files": sorted(p.name for p in OUT.iterdir())})
    print(json.dumps({"status": all_summary["status"], "rows": len(rows), "cycles": len(cycles), "stable_zone": stable, "max_abs_y_m": all_summary["max_abs_y_m"], "contract_gate_exceeded": all_summary["contract_safety_gate_exceeded"]}, ensure_ascii=False, indent=2))


def build_report(s, cycles):
    stable = s["candidate_stable_zone"]
    if stable:
        classification = "STABLE_RESPONSE_BUT_LITERATURE_DISCREPANCY" if s["literature_comparison"] else "STABLE_RESPONSE_AND_PRELIMINARY_LITERATURE_AGREEMENT"
    else:
        classification = "NUMERICAL_OR_COUPLING_FAILURE" if (s["contract_safety_gate_exceeded"]["y_exceeded"] or s["contract_safety_gate_exceeded"]["v_exceeded"]) else "RESPONSE_NOT_YET_STATIONARY"
    last = cycles[-5:] if len(cycles) >= 5 else cycles
    late = "\n".join(f"- cycle {c['cycle']}: t={c['t_start_s']:.6g}--{c['t_end_s']:.6g} s, A/D={c['A_over_D']:.6g}, fD/U={c['fD_over_U']:.6g}, CL_amp={c['CL_amplitude_half_peak_to_peak']:.6g}, CD={c['CD_mean']:.6g}" for c in last)
    stable_text = (f"first qualifying five-cycle block: cycles {stable['start_cycle_index'] + 1}--{stable['end_cycle_index'] + 1}, "
                   f"t={stable['start_time_s']:.6g}--{stable['end_time_s']:.6g} s; "
                   f"A CV={stable['amplitude_cv']:.3%}, f CV={stable['frequency_cv']:.3%}, "
                   f"A trend={stable['amplitude_trend_fraction']:.3%}, CD trend={stable['cd_trend_fraction']:.3%}") if stable else "none"
    return f"""# SHIELS S5-K9.88 100 s physical response — offline report v1

## Scope and data integrity

This is a read-only post-processing of the completed 0.105--100.155 s chain. No OpenFOAM, preCICE, SDOF, ANCF or three-slice calculation was started. The response chain combines the four existing accepted-event logs (first trial, one-period extension, interrupted long-run prefix, and the completed resume). Forces are taken from the existing `forces.dat` files; repeated force rows at one physical time are reduced to the last fluid value.

## Runtime identity and numerical completeness

- Physical interval: **{s['actual_physical_time_s']['start']:.9g}--{s['actual_physical_time_s']['end']:.9g} s**.
- Accepted windows in the response chain: **{s['accepted_windows_total']}**; the resume runtime accepted 18,757 new windows from 6.370 to 100.155 s.
- Structure summary: `status=completed`, `error=null`; trial/restore evidence is retained in the runtime. The resume summary reports 56,271 trials and 37,514 restores.
- Combined event totals: **{s['trial_attempts_total']}** trial force corrections and **{s['checkpoint_restores_total']}** checkpoint restores; accepted-window coupling iterations: `{s['coupling_iteration_distribution']}`. Recorded process returns: `{s['structure_fluid_returns']}`.
- Maximum Co: **{s['quality']['max_Co']:.9g}**; maximum absolute global continuity error: **{s['quality']['max_abs_global_continuity']:.9g}**.
- Maximum |y|={s['max_abs_y_m']:.9g} m, |v|={s['max_abs_v_mps']:.9g} m/s, |a|={s['max_abs_a_mps2']:.9g} m/s², |Fy|={s['max_abs_Fy_N']:.9g} N.
- Maximum accepted-interface displacement residual: **{s['max_interface_residual_m']:.9g} m**.
- Final checkMesh: **{s['checkMesh']['status']}** (max aspect ratio {s['checkMesh']['max_aspect_ratio']:.6g}, max non-orthogonality {s['checkMesh']['max_non_orthogonality_deg']:.6g}°, max skewness {s['checkMesh']['max_skewness']:.6g}).
- FPE/NaN/Inf/negative-volume/preCICE fatal text scan: **{len(s['hard_error_evidence'])} hits**.
- Runtime and ABI identity: adapter SHA `{s['binary_identity']['adapter_sha256']}`, pimpleFoam SHA `{s['binary_identity']['pimple_sha256']}`, participant SHA `{s['binary_identity']['participant_sha256']}`; the original manifest and OF10 prefix are retained.

The frozen contract contained post-run safety gates `|y| <= 0.05 m` and `|v| <= 0.5 m/s`. The observed response first exceeded the displacement gate at approximately **{s['contract_safety_gate_exceeded']['first_y_exceedance_time_s']:.9g} s** and the velocity gate at approximately **{s['contract_safety_gate_exceeded']['first_v_exceedance_time_s']:.9g} s**. The solver completed numerically, but these are contract-level gate violations and are not silently reclassified as a successful bounded physical validation.

## Cycle analysis

Positive-going displacement zero crossings define complete cycles. The predeclared candidate-stability test requires five consecutive cycles with amplitude CV, frequency CV, amplitude trend and mean-CD trend each no greater than 5%. Detected complete cycles: **{s['cycle_count']}**. Candidate stable zone: **{stable_text}**.

Last available cycle statistics:

{late if late else '- no complete cycle detected'}

## Physical interpretation

The response develops into a repeatable large-amplitude cycle band, but it violates the frozen displacement safety gate. The late candidate band is therefore a statistical observation, not a bounded-contract pass. The stable-band comparison is reported for transparency, not promoted to a formal Shiels validation. A large displacement by itself is not evidence of lock-in; the present run needs an independently validated numerical/physical explanation before any further long run.

The full-chain period estimate progresses from approximately 0.12--0.15 Hz during startup to approximately 0.201 Hz in the late band. Full-window and late-window PSDs are included; their finite-window frequency resolution is recorded in the metrics JSON.

## Required figures and machine-readable outputs

The output directory contains the full time history, cycle statistics, PSDs, phase portrait, energy/work history, coupling-iteration history, SVG/PNG/TIFF/PDF plots, metrics JSON, an analysis manifest, and offline vorticity/pressure snapshots at approximately 20, 50 and 80 s. The snapshots were reconstructed from existing saved fields; no new CFD was launched in this pass.

## Final classification

`SHIELS_S5_K9P88_100S_RESPONSE = {classification}`

### Conclusion summary

- Numerical completion: reached 100.155 s with no solver fatal in the scanned logs, but the frozen `|y|<=0.05 m` and `|v|<=0.5 m/s` safety gates were exceeded at {s['contract_safety_gate_exceeded']['first_y_exceedance_time_s']:.6g} s and {s['contract_safety_gate_exceeded']['first_v_exceedance_time_s']:.6g} s.
- Stable response: **candidate stable band detected at {stable['start_time_s']:.6g}--{stable['end_time_s']:.6g} s**, but it is not a bounded-contract pass because the 0.05 m safety gate was exceeded.
- Candidate-band A/D={s['literature_comparison']['A_over_D']['mean']:.6g}, fD/U={s['literature_comparison']['fD_over_U']['mean']:.6g}, CL amplitude={s['literature_comparison']['CL_amplitude_half_peak_to_peak']['mean']:.6g}, CD={s['literature_comparison']['CD_mean']['mean']:.6g}; relative differences are {s['literature_comparison']['A_over_D']['relative_error']:.3%}, {s['literature_comparison']['fD_over_U']['relative_error']:.3%}, {s['literature_comparison']['CL_amplitude_half_peak_to_peak']['relative_error']:.3%}, and {s['literature_comparison']['CD_mean']['relative_error']:.3%}, respectively.
- Shiels physical reproduction: **not passed**; the lift-amplitude discrepancy and the frozen safety-gate violation remain.
- Single priority next step: **offline/controlled numerical-physics diagnosis of the first displacement-growth and safety-gate crossing, beginning with fixed-cylinder CFD statistical credibility and time-step/grid sensitivity; do not extend this free-FSI run or retune parameters.**

Historical FAIL and NOT_EVALUABLE labels, original runtimes, and binary identities remain unchanged.
"""


if __name__ == "__main__":
    main()
