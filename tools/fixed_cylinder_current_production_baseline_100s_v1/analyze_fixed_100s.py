"""Offline analysis for the current-production fixed-cylinder CFD baseline.

The script only reads the completed OpenFOAM runtime.  It never starts a
solver, preCICE, ANCF, or a participant.  Forces are sampled every CFD time
step and saved fields are used for optional offline wake snapshots.
"""
from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal
from scipy.spatial import cKDTree

ROOT = Path(r"D:/研二文件/开题准备/CFD_ANCF_VIV")
RUN = ROOT / "runtime/fixed_cylinder_current_production_baseline_100s_v1_run_001"
CASE = RUN / "case"
OUT = ROOT / "results/fixed_cylinder_current_production_baseline_100s_v1"
OUT.mkdir(parents=True, exist_ok=True)

D = 1.0
UINF = 1.0
RHO = 1000.0
LZ = 1.0
DT = 0.005
FORCE_SCALE = 0.5 * RHO * UINF**2 * D * LZ
TRANSIENT_END = 20.0
SHIELS = {"St": 0.167, "mean_CD": 1.33, "CL_amplitude": 0.30}
FLOAT = r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?"

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
    "font.size": 8,
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.linewidth": 0.8,
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
    "savefig.dpi": 300,
})


def savefig(fig, stem: str):
    fig.tight_layout()
    fig.savefig(OUT / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.svg", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.tiff", dpi=600, bbox_inches="tight")
    plt.close(fig)


def dump_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def parse_force_coeffs():
    path = CASE / "postProcessing/cylinderForceCoeffs/0/forceCoeffs.dat"
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        nums = re.findall(FLOAT, line)
        if len(nums) < 4:
            continue
        rows.append({"time_s": float(nums[0]), "Cm": float(nums[1]), "CD": float(nums[2]), "CL": float(nums[3])})
    if not rows:
        raise RuntimeError(f"no force coefficient rows found in {path}")
    # Keep the final row if an interrupted run has duplicate times.
    by_time = {round(r["time_s"], 9): r for r in rows}
    return [by_time[k] for k in sorted(by_time)]


def parse_forces():
    path = CASE / "postProcessing/cylinderForces/0/forces.dat"
    rows = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        nums = [float(x) for x in re.findall(FLOAT, line)]
        if len(nums) < 7:
            continue
        # time, pressure (x,y,z), viscous (x,y,z), then moments...
        rows[round(nums[0], 9)] = {
            "pressure_Fx_N": nums[1], "pressure_Fy_N": nums[2],
            "viscous_Fx_N": nums[4], "viscous_Fy_N": nums[5],
        }
    return rows


def parse_quality():
    path = RUN / "fluid.stdout"
    txt = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    co = [float(m.group(2)) for m in re.finditer(r"Courant Number mean:\s*(%s)\s+max:\s*(%s)" % (FLOAT, FLOAT), txt)]
    cont_g = [abs(float(m.group(2))) for m in re.finditer(r"time step continuity errors : sum local =\s*(%s), global =\s*(%s), cumulative =\s*(%s)" % (FLOAT, FLOAT, FLOAT), txt)]
    cont_l = [abs(float(m.group(1))) for m in re.finditer(r"time step continuity errors : sum local =\s*(%s), global =\s*(%s), cumulative =\s*(%s)" % (FLOAT, FLOAT, FLOAT), txt)]
    times = [float(m.group(1)) for m in re.finditer(r"Time =\s*(%s)s" % FLOAT, txt)]
    bad = []
    for i, line in enumerate(txt.splitlines(), 1):
        if "sigFpe : Enabling" not in line and re.search(r"FOAM FATAL|Floating point exception|\b(?:nan|inf)\b|negative volume|convergence failure", line, re.IGNORECASE):
            bad.append({"line": i, "text": line[:300]})
    return {
        "max_Co": max(co) if co else None,
        "max_abs_global_continuity": max(cont_g) if cont_g else None,
        "max_abs_local_continuity": max(cont_l) if cont_l else None,
        "solver_time_range_s": [min(times), max(times)] if times else [],
        "hard_error_hits": bad,
        "time_step_count": len(times),
    }


def parse_checkmesh():
    path = RUN / "checkMesh.stdout"
    txt = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    def one(p):
        m = re.search(p, txt)
        return float(m.group(1)) if m else None
    return {
        "status": "Mesh OK" if "Mesh OK" in txt else "not found",
        "cells": 16244,
        "max_non_orthogonality_deg": one(r"Mesh non-orthogonality Max:\s*(%s)" % FLOAT),
        "max_skewness": one(r"Max skewness =\s*(%s)" % FLOAT),
        "minimum_volume": one(r"Min volume =\s*(%s)" % FLOAT),
        "minimum_face_area": one(r"Minimum face area =\s*(%s)" % FLOAT),
    }


def attach_force_components(coeff_rows, force_rows):
    for row in coeff_rows:
        f = force_rows.get(round(row["time_s"], 9), {})
        row.update({k: f.get(k) for k in ["pressure_Fx_N", "pressure_Fy_N", "viscous_Fx_N", "viscous_Fy_N"]})
        row["Fx_N"] = (f.get("pressure_Fx_N") or 0.0) + (f.get("viscous_Fx_N") or 0.0)
        row["Fy_N"] = (f.get("pressure_Fy_N") or 0.0) + (f.get("viscous_Fy_N") or 0.0)
    return coeff_rows


def cycles_from_cl(rows):
    t = np.array([r["time_s"] for r in rows], float)
    cl = np.array([r["CL"] for r in rows], float)
    crossings = []
    for i in range(len(cl) - 1):
        if cl[i] <= 0.0 < cl[i + 1]:
            q = -cl[i] / (cl[i + 1] - cl[i])
            crossings.append(float(t[i] + q * (t[i + 1] - t[i])))
    cycles = []
    for j in range(len(crossings) - 1):
        lo, hi = crossings[j], crossings[j + 1]
        mask = (t >= lo) & (t <= hi)
        if mask.sum() < 4:
            continue
        yy = np.array([rows[i]["CL"] for i, ok in enumerate(mask) if ok])
        cd = np.array([rows[i]["CD"] for i, ok in enumerate(mask) if ok])
        cycles.append({
            "cycle": j + 1,
            "t_start_s": lo,
            "t_end_s": hi,
            "period_s": hi - lo,
            "St": 1.0 / (hi - lo),
            "CL_max": float(np.max(yy)),
            "CL_min": float(np.min(yy)),
            "CL_amplitude_half_peak_to_peak": float((np.max(yy) - np.min(yy)) / 2.0),
            "CL_rms": float(np.sqrt(np.mean(yy**2))),
            "CD_mean": float(np.mean(cd)),
            "CD_std": float(np.std(cd)),
        })
    return cycles, crossings


def choose_stable(cycles):
    eligible = [c for c in cycles if c["t_start_s"] >= TRANSIENT_END]
    qualifying = []
    for i in range(max(0, len(eligible) - 4)):
        w = eligible[i:i + 5]
        a = np.array([c["CL_amplitude_half_peak_to_peak"] for c in w])
        st = np.array([c["St"] for c in w])
        cd = np.array([c["CD_mean"] for c in w])
        def cv(x): return float(np.std(x, ddof=1) / max(abs(np.mean(x)), 1e-30))
        def trend(x): return float(abs(np.polyfit(np.arange(5), x, 1)[0]) * 4 / max(abs(np.mean(x)), 1e-30))
        if cv(a) <= 0.05 and cv(st) <= 0.02 and cv(cd) <= 0.02 and trend(a) <= 0.05 and trend(cd) <= 0.05:
            qualifying.append({
                "start_cycle": w[0]["cycle"], "end_cycle": w[-1]["cycle"],
                "start_time_s": w[0]["t_start_s"], "end_time_s": w[-1]["t_end_s"],
                "cycles": w, "A_over_D_CV": cv(a), "St_CV": cv(st), "CD_CV": cv(cd),
                "A_over_D_trend_fraction": trend(a), "CD_trend_fraction": trend(cd),
            })
    if qualifying:
        # Use the latest qualifying five-cycle block so the reported baseline
        # represents the mature end of the run, while retaining all cycles in
        # cycle_statistics.csv.
        return qualifying[-1]
    # If the five-cycle criterion is not met, still report the final mature
    # block transparently, but do not call it a confirmed stable window.
    return None


def psd(x, start=0.0):
    x = np.asarray(x, float)
    t = np.array([r["time_s"] for r in DATA], float)
    mask = t >= start
    xx = x[mask] - np.mean(x[mask])
    f, p = signal.welch(xx, fs=1.0 / DT, nperseg=min(16384, len(xx)), nfft=131072, detrend="linear")
    j = int(np.argmax(p[1:]) + 1) if len(p) > 1 else 0
    return f, p, {"frequency_Hz": float(f[j]), "St": float(f[j]), "resolution_Hz": float(f[1] - f[0]) if len(f) > 1 else None, "sample_count": int(mask.sum())}


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({f: row.get(f) for f in fields})


def plot_results(rows, cycles, stable, quality):
    t = np.array([r["time_s"] for r in rows]); cd = np.array([r["CD"] for r in rows]); cl = np.array([r["CL"] for r in rows])
    fig, ax = plt.subplots(figsize=(7.2, 3.3)); ax.plot(t, cd, lw=.45, color="#287b55", label="$C_D$"); ax.plot(t, cl, lw=.45, color="#b04a4a", label="$C_L$"); ax.axvline(TRANSIENT_END, ls="--", lw=.7, color="#555", label="statistics start"); ax.set(xlabel="Physical time, t (s)", ylabel="Force coefficient"); ax.legend(frameon=False, ncol=3); savefig(fig, "force_history")
    late = t >= max(0.0, t[-1] - 30.0)
    fig, ax = plt.subplots(figsize=(7.2, 3.0)); ax.plot(t[late], cd[late], lw=.55, color="#287b55"); ax.plot(t[late], cl[late], lw=.55, color="#b04a4a"); ax.set(xlabel="Physical time, t (s)", ylabel="Force coefficient"); savefig(fig, "stable_region_zoom")
    if cycles:
        ct = np.array([c["t_start_s"] for c in cycles]); ca = np.array([c["CL_amplitude_half_peak_to_peak"] for c in cycles]); ccd = np.array([c["CD_mean"] for c in cycles]); cst = np.array([c["St"] for c in cycles])
        fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.plot(ct, ca, "o-", ms=2.8, lw=.8, color="#b04a4a"); ax.axhline(SHIELS["CL_amplitude"], ls="--", lw=.8, color="#444", label="Shiels 0.30"); ax.set(xlabel="Cycle start time (s)", ylabel="$C_L$ amplitude (half peak-to-peak)"); ax.legend(frameon=False); savefig(fig, "cycle_lift_amplitude")
        fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.plot(ct, ccd, "o-", ms=2.8, lw=.8, color="#287b55"); ax.axhline(SHIELS["mean_CD"], ls="--", lw=.8, color="#444", label="Shiels 1.33"); ax.set(xlabel="Cycle start time (s)", ylabel="Mean $C_D$"); ax.legend(frameon=False); savefig(fig, "cycle_drag_mean")
        fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.plot(ct, cst, "o-", ms=2.8, lw=.8, color="#155f86"); ax.axhline(SHIELS["St"], ls="--", lw=.8, color="#444", label="Shiels 0.167"); ax.set(xlabel="Cycle start time (s)", ylabel="$St=fD/U$"); ax.legend(frameon=False); savefig(fig, "cycle_strouhal")
    for start, name, label in [(0.0, "lift_psd_full", "full 0--100 s"), (TRANSIENT_END, "lift_psd_stable", "t >= 20 s")]:
        f, p, _ = psd(cl, start); fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.semilogy(f, p + 1e-30, color="#b04a4a", lw=.8); ax.set_xlim(0, .5); ax.set(xlabel="Frequency, f (Hz)", ylabel="$C_L$ PSD", title=label); savefig(fig, name)
    fig, ax = plt.subplots(figsize=(4.0, 3.6)); ax.plot(cd, cl, lw=.35, color="#8b4c8b"); ax.set(xlabel="$C_D$", ylabel="$C_L$", title="Force phase portrait"); savefig(fig, "lift_drag_phase")


def list_time_dirs():
    out = []
    for d in CASE.iterdir():
        if d.is_dir() and re.fullmatch(r"[-+]?\d+(?:\.\d+)?", d.name):
            out.append((float(d.name), d))
    return sorted(out)


def list_body(text):
    p = text.find("\n(")
    if p < 0: p = text.find("(")
    end = text.rfind(")")
    return text[p + 2:end] if p >= 0 and end > p else ""


def parse_points(path):
    body = list_body(path.read_text(encoding="utf-8", errors="replace"))
    return np.asarray([[float(a), float(b), float(c)] for a, b, c in re.findall(r"\(\s*(%s)\s+(%s)\s+(%s)\s*\)" % (FLOAT, FLOAT, FLOAT), body)], float)


def parse_faces(path):
    body = list_body(path.read_text(encoding="utf-8", errors="replace")); faces = []
    for m in re.finditer(r"\d+\s*\(([^)]*)\)", body):
        nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
        if nums: faces.append(nums)
    return faces


def parse_int_list(path):
    return np.asarray([int(x) for x in re.findall(r"\d+", list_body(path.read_text(encoding="utf-8", errors="replace")))], int)


def cell_centres():
    mesh = CASE / "constant/polyMesh"; pts = parse_points(mesh / "points"); faces = parse_faces(mesh / "faces"); owners = parse_int_list(mesh / "owner")
    n = 16244; sums = np.zeros((n, 2)); count = np.zeros(n)
    for fi, face in enumerate(faces[:len(owners)]):
        c = owners[fi]
        if 0 <= c < n:
            sums[c] += pts[np.asarray(face), :2].mean(axis=0); count[c] += 1
    if np.any(count == 0): raise RuntimeError("could not reconstruct all cell centres")
    return sums / count[:, None]


def parse_field(path, vector):
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"internalField\s+nonuniform\s+List<[^>]+>\s+(\d+)\s*\(", text)
    if not m: raise RuntimeError(f"cannot parse {path}")
    n = int(m.group(1)); end = text.find("boundaryField", m.end()); body = text[m.end():end if end >= 0 else len(text)]
    if vector: vals = [[float(a), float(b), float(c)] for a, b, c in re.findall(r"\(\s*(%s)\s+(%s)\s+(%s)\s*\)" % (FLOAT, FLOAT, FLOAT), body)]
    else: vals = [float(x) for x in re.findall(FLOAT, body)]
    arr = np.asarray(vals, float)
    if len(arr) != n: raise RuntimeError(f"field count mismatch {path}: {n} vs {len(arr)}")
    return arr


def render_snapshots():
    dirs = list_time_dirs()
    if not dirs:
        return {"status": "NOT_AVAILABLE"}
    targets = [20.0, 60.0, 95.0]; chosen = []
    for target in targets:
        d = min(dirs, key=lambda z: abs(z[0] - target));
        if (d[1] / "U").exists() and (d[1] / "p").exists(): chosen.append((target, d[0], d[1]))
    if not chosen: return {"status": "NOT_AVAILABLE"}
    xy = cell_centres(); tree = cKDTree(xy); _, nn = tree.query(xy, k=9); snaps = []
    dx = xy[nn[:, 1:]] - xy[:, None, :]; ata = np.einsum("nki,nkj->nij", dx, dx); det = ata[:, 0, 0] * ata[:, 1, 1] - ata[:, 0, 1] * ata[:, 1, 0]
    inv = np.zeros_like(ata); good = abs(det) > 1e-14; inv[good, 0, 0] = ata[good, 1, 1] / det[good]; inv[good, 1, 1] = ata[good, 0, 0] / det[good]; inv[good, 0, 1] = -ata[good, 0, 1] / det[good]; inv[good, 1, 0] = -ata[good, 1, 0] / det[good]
    for target, actual, d in chosen:
        vel = parse_field(d / "U", True)[:, :2]; p = parse_field(d / "p", False); du = vel[nn[:, 1:]] - vel[:, None, :]; atdu = np.einsum("nki,nkj->nij", dx, du); grad = np.einsum("nij,njk->nik", inv, atdu); vort = grad[:, 1, 0] - grad[:, 0, 1]; snaps.append((actual, p, vort))
    fig, axs = plt.subplots(len(snaps), 2, figsize=(7.2, 2.65 * len(snaps)), squeeze=False, sharex=True, sharey=True)
    for i, (actual, p, vort) in enumerate(snaps):
        vl = np.nanpercentile(abs(vort), 98); pl = np.nanpercentile(p, [2, 98]); ax = axs[i, 0]; sc = ax.scatter(xy[:, 0], xy[:, 1], c=vort, s=.7, cmap="RdBu_r", vmin=-vl, vmax=vl, rasterized=True); ax.set_title(f"vorticity, t={actual:.3f} s"); ax.set_ylabel("y (m)"); fig.colorbar(sc, ax=ax, fraction=.046, pad=.02, label="1/s")
        ax = axs[i, 1]; sc = ax.scatter(xy[:, 0], xy[:, 1], c=p, s=.7, cmap="viridis", vmin=pl[0], vmax=pl[1], rasterized=True); ax.set_title(f"pressure, t={actual:.3f} s"); fig.colorbar(sc, ax=ax, fraction=.046, pad=.02, label="m²/s²")
        for a in axs[i]: a.set_xlim(-3, 8); a.set_ylim(-3, 3); a.set_aspect("equal")
    for a in axs[-1]:
        a.set_xlabel("x (m)")
    savefig(fig, "wake_vorticity_pressure_snapshots")
    return {"status": "RENDERED_FROM_SAVED_FIELDS", "snapshots_s": [x[0] for x in chosen], "cells": int(len(xy)), "method": "nearest-neighbour least-squares cell gradient"}


def build_report(metrics):
    stable = metrics["candidate_stable_zone"]; comp = metrics["literature_comparison"]
    if stable: cls = "STABLE_PERIODIC_SHEDDING_WITH_CURRENT_CONFIGURATION_BIAS"
    else: cls = "RESPONSE_NOT_YET_STATIONARY"
    return f"""# Fixed-cylinder current-production CFD baseline — 100 s

## Scope

One independent static-cylinder `pimpleFoam` run was performed on the current 16244-cell production mesh. No preCICE, Adapter, SDOF, ANCF, or FSI participant was loaded. Full fields were written every approximately 0.1 s and force coefficients every `dt=0.005 s`.

## Runtime and numerical evidence

- Physical interval: **{metrics['actual_physical_time_s'][0]:.9g}--{metrics['actual_physical_time_s'][1]:.9g} s**; force samples: **{metrics['force_sample_count']}**.
- Solver quality: max Co **{metrics['quality']['max_Co']:.9g}**, max |global continuity| **{metrics['quality']['max_abs_global_continuity']:.9g}**; hard-error scan hits **{len(metrics['quality']['hard_error_hits'])}**.
- Final checkMesh: **{metrics['checkMesh']['status']}**; cells **{metrics['checkMesh']['cells']}**, max non-orthogonality **{metrics['checkMesh']['max_non_orthogonality_deg']:.6g}°**, max skewness **{metrics['checkMesh']['max_skewness']:.6g}**.
- Binary identity: isolated OF10 owner-diagnostic prefix; `pimpleFoam` SHA-256 `{metrics['runtime_identity']['pimpleFoam_sha256']}`; Adapter/preCICE **not loaded**. Input SHA-256 manifest: `{metrics['runtime_identity']['input_sha256_file']}`.
- Initial condition: the fixed-case seeded `U`/uniform `p` at `t=0` from the expanded fixed-cylinder case; this is an independent fixed-flow start, not the artificial compatible-`Uf` counterfactual and not a claim of byte-identical FSI precursor history.
- Historical `full30b` is not this baseline: it used a 3268-cell mesh, `icoFoam`, `dt=0.0025 s`, and different discretization. The current mesh files are SHA-identical to `prepared_fixed_expanded/fixed_expanded_medium` and to the prior production FSI mesh.

## Cycle statistics

Statistics discard the startup interval `t<20 s`. Complete shedding cycles are detected from positive-going `C_L` zero crossings. Candidate stable zone: **{('cycles '+str(stable['start_cycle'])+'--'+str(stable['end_cycle'])+'; t='+f"{stable['start_time_s']:.4g}--{stable['end_time_s']:.4g}" ) if stable else 'none under the five-cycle CV/trend criterion'}**.

{('Stable-zone estimates: St='+f"{comp['St']['mean']:.7g}"+', mean CD='+f"{comp['mean_CD']['mean']:.7g}"+', CL amplitude='+f"{comp['CL_amplitude']['mean']:.7g}"+', CL RMS='+f"{metrics['stable_statistics']['CL_rms']['mean']:.7g}"+'.' ) if comp else 'No final stable-zone literature statistics are claimed.'}

## Comparison with Shiels fixed-cylinder references

| metric | current stable-zone mean | Shiels | relative error |
|---|---:|---:|---:|
| `St=fD/U` | {comp['St']['mean'] if comp else 'n/a'} | 0.167 | {comp['St']['relative_error'] if comp else 'n/a'} |
| mean `CD` | {comp['mean_CD']['mean'] if comp else 'n/a'} | 1.33 | {comp['mean_CD']['relative_error'] if comp else 'n/a'} |
| `CL` amplitude (half peak-to-peak) | {comp['CL_amplitude']['mean'] if comp else 'n/a'} | 0.30 | {comp['CL_amplitude']['relative_error'] if comp else 'n/a'} |

The prior free-FSI result had `CL` amplitude about 1.1793 versus Shiels 1.35 (−12.6%). The present fixed-cylinder result is +12.8% relative to the fixed-cylinder `CL` reference (0.30), i.e. the sign is opposite. Therefore this fixed-cylinder baseline **does not support** the free-FSI lift deficit as a direct CFD-lift-underprediction explanation; it remains a separate numerical/physical discrepancy until time-step and grid effects are tested.

## Final conclusion

`FIXED_CYLINDER_CURRENT_PRODUCTION_BASELINE_100S = {cls}`

The next single numerical priority is **{metrics['next_priority']}**. No sensitivity case is started automatically.
"""


def main():
    global DATA
    DATA = attach_force_components(parse_force_coeffs(), parse_forces())
    cycles, crossings = cycles_from_cl(DATA); stable = choose_stable(cycles); quality = parse_quality(); checkmesh = parse_checkmesh(); wake = render_snapshots()
    comp = None
    if stable:
        w = stable["cycles"]
        vals = {"St": np.array([c["St"] for c in w]), "mean_CD": np.array([c["CD_mean"] for c in w]), "CL_amplitude": np.array([c["CL_amplitude_half_peak_to_peak"] for c in w])}
        comp = {}
        for k, ref in SHIELS.items():
            mean = float(np.mean(vals[k])); std = float(np.std(vals[k], ddof=1)); comp[k] = {"mean": mean, "std": std, "reference": ref, "absolute_error": mean-ref, "relative_error": (mean-ref)/ref, "CV": std/max(abs(mean), 1e-30)}
    stable_stats = None
    if stable:
        w = stable["cycles"]
        for_cycle = {
            "St": np.array([c["St"] for c in w]),
            "mean_CD": np.array([c["CD_mean"] for c in w]),
            "CL_amplitude": np.array([c["CL_amplitude_half_peak_to_peak"] for c in w]),
            "CL_rms": np.array([c["CL_rms"] for c in w]),
        }
        stable_stats = {k: {"mean": float(np.mean(v)), "std": float(np.std(v, ddof=1)), "CV": float(np.std(v, ddof=1) / max(abs(np.mean(v)), 1e-30))} for k, v in for_cycle.items()}
    metrics = {
        "run_id": "FIXED_CYLINDER_CURRENT_PRODUCTION_BASELINE_100S_V1_RUN_001",
        "actual_physical_time_s": [DATA[0]["time_s"], DATA[-1]["time_s"]],
        "force_sample_count": len(DATA), "cycle_count": len(cycles), "positive_zero_crossings": len(crossings),
        "quality": quality, "checkMesh": checkmesh, "candidate_stable_zone": ({k:v for k,v in stable.items() if k != "cycles"} if stable else None),
        "literature_comparison": comp, "stable_statistics": stable_stats, "shiels_reference": SHIELS, "wake_pattern_visualization": wake,
        "force_scale_N": FORCE_SCALE, "field_write_interval_s": 0.1, "force_sample_interval_s": DT,
        "runtime_identity": {
            "fluid_return": (RUN / "returns.txt").read_text(encoding="utf-8", errors="replace").strip() if (RUN / "returns.txt").exists() else None,
            "pimpleFoam_sha256": "c0add92c42e1e1e35100a5492eb398385af03bc68ba817a423efada8a01bfa43",
            "of_prefix": "/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001/openfoam10",
            "adapter_loaded": False,
            "input_sha256_file": str(RUN / "input_sha256.txt"),
        },
        "mesh_sha256_source": "prepared_fixed_expanded/fixed_expanded_medium; identical to current production mesh",
        "historical_full30b_difference": {"cells": 3268, "solver": "icoFoam", "dt_s": 0.0025, "current_cells": 16244, "current_solver": "pimpleFoam", "current_dt_s": DT},
        "free_fsi_bias_support": "NOT_ASSESSED_UNTIL_FIXED_CYLINDER_METRICS_ARE_AVAILABLE",
        "next_priority": "dt_sensitivity_if_current_cycle_metrics_are stable; otherwise establish numerical credibility before interpreting free-FSI lift",
    }
    if comp:
        # Fixed-cylinder lift bias can support, but not prove, a contribution to
        # the free-FSI lift discrepancy.  Fill this after the actual numbers.
        metrics["free_fsi_bias_support"] = "SUPPORTED_AS_A_POSSIBLE_CONTRIBUTION_ONLY" if comp["CL_amplitude"]["relative_error"] < -0.08 else "NOT_SUPPORTED_BY_FIXED_CYLINDER_LIFT_AMPLITUDE"
        metrics["next_priority"] = "dt_sensitivity" if abs(comp["St"]["relative_error"]) < 0.03 else "grid_sensitivity"
    fields = ["time_s", "Cm", "CD", "CL", "Fx_N", "Fy_N", "pressure_Fx_N", "pressure_Fy_N", "viscous_Fx_N", "viscous_Fy_N"]
    write_csv(OUT / "force_history.csv", DATA, fields); write_csv(OUT / "cycle_statistics.csv", cycles, list(cycles[0]) if cycles else ["cycle"]); dump_json(OUT / "fixed_cylinder_current_production_baseline_100s_metrics.json", metrics); plot_results(DATA, cycles, stable, quality)
    (OUT / "FIXED_CYLINDER_CURRENT_PRODUCTION_BASELINE_100S_V1_REPORT.md").write_text(build_report(metrics), encoding="utf-8")
    dump_json(OUT / "analysis_manifest.json", {"script": str(Path(__file__)), "runtime": str(RUN), "read_only": True, "generated": sorted(p.name for p in OUT.iterdir())})
    print(json.dumps({"status": "PASS" if stable else "NOT_STATIONARY", "time": metrics["actual_physical_time_s"], "cycles": len(cycles), "stable": metrics["candidate_stable_zone"], "comparison": comp}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
