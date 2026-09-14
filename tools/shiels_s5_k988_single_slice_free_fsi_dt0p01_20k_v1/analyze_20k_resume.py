"""Offline post-processing for the completed 20k continuation.

This script reads only accepted Structure window commits, OpenFOAM force
coefficient output, and solver stdout. It never launches or changes a CFD,
preCICE, or structure calculation. Raw runtime files are left untouched.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal


DEFAULT_RUN = Path(r"D:/CFD/CFD_ANCF_VIV/runtime/fixed_cylinder_o_grid/moving_wall_20k")
DEFAULT_OUT = DEFAULT_RUN / "postprocess_20k_resume_v1"
D = 1.0
U = 1.0
RHO = 1000.0
LZ = 1.0
FORCE_SCALE = 0.5 * RHO * U * U * D * LZ
M = 2500.0
K = 4940.0
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
    "legend.frameon": False,
    "savefig.dpi": 300,
})


def savefig(fig: mpl.figure.Figure, out: Path, stem: str) -> None:
    fig.savefig(out / f"{stem}.png", dpi=600, bbox_inches="tight")
    fig.savefig(out / f"{stem}.tiff", dpi=600, bbox_inches="tight")
    fig.savefig(out / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(out / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def parse_accepted(run: Path) -> tuple[list[dict], dict, Counter]:
    accepted: list[dict] = []
    initial: dict | None = None
    counts: Counter = Counter()
    event_path = run / "structure" / "events.jsonl"
    with event_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            event = json.loads(line)
            kind = event.get("event", "")
            counts[kind] += 1
            if kind == "initial_data" and initial is None:
                initial = event
            if kind != "window_commit":
                continue
            state = event["accepted_state"]
            accepted.append({
                "time_s": float(event["physical_time_s"]),
                "y_m": float(state["y_m"]),
                "v_mps": float(state["v_mps"]),
                "a_mps2": float(state["a_mps2"]),
                "Fy_N": float(event["force_y_total_N"]),
                "mechanical_energy_J": float(event["mechanical_energy_J"]),
                "cumulative_fluid_work_J": float(event["cumulative_fluid_work_J"]),
                "energy_balance_defect_J": float(event["cumulative_energy_balance_defect_J"]),
                "iteration_count": int(event["iteration_count"]),
                "window_index": int(event["window_index"]),
                "checkpoint_id": event.get("checkpoint_id"),
                "final_input_y_m": float(event.get("final_input_y_m", state["y_m"])),
            })
    by_time = {round(row["time_s"], 8): row for row in accepted}
    accepted = sorted(by_time.values(), key=lambda row: row["time_s"])
    if initial is None:
        raise RuntimeError("No initial_data event found")
    # Initial data is the valid accepted continuation checkpoint. Keep it as
    # the first sample, even though the first post-restart commit is at t+dt.
    init_state = initial["initial_state"]
    t0 = float(initial["physical_time_s"])
    if not accepted or abs(accepted[0]["time_s"] - t0) > 1e-7:
        y0 = float(initial["payload_y_m"])
        v0 = float(init_state["v_mps"])
        accepted.insert(0, {
            "time_s": t0,
            "y_m": y0,
            "v_mps": v0,
            "a_mps2": float(init_state["a_mps2"]),
            "Fy_N": float(initial["initial_force_y_N"]),
            "mechanical_energy_J": 0.5 * M * v0 * v0 + 0.5 * K * y0 * y0,
            "cumulative_fluid_work_J": float(initial.get("cumulative_fluid_work_J", 0.0)),
            "energy_balance_defect_J": float(initial.get("cumulative_energy_balance_defect_J", 0.0)),
            "iteration_count": 0,
            "window_index": 0,
            "checkpoint_id": "restart_initial",
            "final_input_y_m": y0,
        })
    return accepted, initial, counts


def parse_force_coeffs(run: Path) -> dict[float, tuple[float, float, float]]:
    files = sorted((run / "postProcessing" / "cylinderForceCoeffs").rglob("forceCoeffs.dat"))
    if not files:
        raise RuntimeError("No forceCoeffs.dat found")
    # The function object writes one row per coupling/PIMPLE iteration. The
    # final row at each physical time is the value used for comparison.
    dedup: dict[float, tuple[float, float, float]] = {}
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            fields = line.split()
            if len(fields) < 4:
                continue
            values = [float(item) for item in fields[:4]]
            dedup[round(values[0], 8)] = (values[1], values[2], values[3])
    return dict(sorted(dedup.items()))


def merge_coeffs(rows: list[dict], coeffs: dict[float, tuple[float, float, float]]) -> None:
    keys = np.asarray(list(coeffs), dtype=float)
    vals = list(coeffs.values())
    for row in rows:
        idx = int(np.argmin(np.abs(keys - row["time_s"])))
        if abs(keys[idx] - row["time_s"]) > 2e-4:
            raise RuntimeError(f"No force coefficient sample near {row['time_s']}")
        row["Cm"] = float(vals[idx][0])
        row["Cd"] = float(vals[idx][1])
        row["Cl"] = float(vals[idx][2])
        row["force_time_s"] = float(keys[idx])
        row["force_time_delta_s"] = float(keys[idx] - row["time_s"])


def parse_solver_quality(run: Path) -> dict:
    text = (run / "fluid.stdout").read_text(encoding="utf-8", errors="replace")
    co = [(float(a), float(b)) for a, b in re.findall(
        r"Courant Number mean:\s*([0-9.eE+-]+) max:\s*([0-9.eE+-]+)", text)]
    continuity_pairs = [(float(a), float(b)) for a, b in re.findall(
        r"time step continuity errors\s*:\s*sum local =\s*([0-9.eE+-]+),\s*global =\s*([0-9.eE+-]+)", text)]
    final_checkmesh = "Mesh OK." in text or "Mesh OK" in text
    hard_patterns = {
        # Do not classify normal OpenFOAM startup text such as
        # ``Enabling floating point exception trapping`` or ``endTime ...
        # infinity`` as a numerical failure.
        "FOAM_FATAL": r"FOAM FATAL (?:ERROR|IO ERROR)|Fatal error",
        "FPE": r"Floating point exception signal|received signal SIGFPE|SIGFPE.*stack",
        "NAN_INF": r"(?<![A-Za-z])(?:nan|NaN|inf|Inf)(?![A-Za-z])",
        "NEGATIVE_VOLUME": r"negative volume|negative cell volume",
        "PRECICE_FAILURE": r"(?:ERROR.*preCICE|preCICE.*ERROR|convergence\s+failed)",
    }
    hard_hits = {name: bool(re.search(pattern, text, re.IGNORECASE)) for name, pattern in hard_patterns.items()}
    return {
        "courant_samples": len(co),
        "max_Co_mean": max((item[0] for item in co), default=None),
        "max_Co": max((item[1] for item in co), default=None),
        "continuity_samples": len(continuity_pairs),
        "max_abs_local_continuity": max((abs(item[0]) for item in continuity_pairs), default=None),
        "max_abs_global_continuity": max((abs(item[1]) for item in continuity_pairs), default=None),
        "final_checkMesh_text_found": final_checkmesh,
        "hard_failure_pattern_hits": hard_hits,
        "execution_time_last_s": (float(re.findall(r"ExecutionTime =\s*([0-9.eE+-]+)", text)[-1])
                                   if re.findall(r"ExecutionTime =\s*([0-9.eE+-]+)", text) else None),
        "clock_time_last_s": (float(re.findall(r"ClockTime =\s*([0-9.eE+-]+)", text)[-1])
                               if re.findall(r"ClockTime =\s*([0-9.eE+-]+)", text) else None),
    }


def zero_crossings(t: np.ndarray, y: np.ndarray) -> np.ndarray:
    idx = np.flatnonzero((y[:-1] < 0.0) & (y[1:] >= 0.0))
    crossings = []
    for i in idx:
        denom = y[i + 1] - y[i]
        crossings.append(float(t[i] if denom == 0 else t[i] - y[i] * (t[i + 1] - t[i]) / denom))
    return np.asarray(crossings)


def cycle_stats(rows: list[dict]) -> list[dict]:
    t = np.asarray([row["time_s"] for row in rows])
    y = np.asarray([row["y_m"] for row in rows])
    crossings = zero_crossings(t, y)
    output: list[dict] = []
    for i in range(len(crossings) - 1):
        start, end = crossings[i], crossings[i + 1]
        mask = (t >= start) & (t <= end)
        if int(mask.sum()) < 10:
            continue
        period = float(end - start)
        yseg = y[mask]
        cl = np.asarray([rows[j]["Cl"] for j in np.flatnonzero(mask)])
        cd = np.asarray([rows[j]["Cd"] for j in np.flatnonzero(mask)])
        eseg = np.asarray([rows[j]["mechanical_energy_J"] for j in np.flatnonzero(mask)])
        wseg = np.asarray([rows[j]["cumulative_fluid_work_J"] for j in np.flatnonzero(mask)])
        it = np.asarray([rows[j]["iteration_count"] for j in np.flatnonzero(mask)])
        output.append({
            "cycle_index": i + 1,
            "start_time_s": float(start),
            "end_time_s": float(end),
            "y_max_m": float(yseg.max()),
            "y_min_m": float(yseg.min()),
            "A_over_D": float((yseg.max() - yseg.min()) / (2.0 * D)),
            "period_s": period,
            "fD_over_U": float(D / (U * period)),
            "CL_amplitude_half_peak_to_peak": float((cl.max() - cl.min()) / 2.0),
            "CL_RMS": float(np.sqrt(np.mean(cl * cl))),
            "mean_CD": float(cd.mean()),
            "max_coupling_iterations": int(it.max()),
            "mean_coupling_iterations": float(it.mean()),
            "mechanical_energy_start_J": float(eseg[0]),
            "mechanical_energy_end_J": float(eseg[-1]),
            "mechanical_energy_change_J": float(eseg[-1] - eseg[0]),
            "fluid_work_change_J": float(wseg[-1] - wseg[0]),
        })
    return output


def spectral_peak(t: np.ndarray, x: np.ndarray) -> dict:
    if len(x) < 16:
        return {"frequency_Hz": None, "fD_over_U": None, "resolution_Hz": None}
    dt = float(np.median(np.diff(t)))
    xx = signal.detrend(x)
    freq = np.fft.rfftfreq(len(xx), dt)
    power = np.abs(np.fft.rfft(xx)) ** 2
    if len(power) <= 2:
        return {"frequency_Hz": None, "fD_over_U": None, "resolution_Hz": 1.0 / (len(xx) * dt)}
    peak = int(np.argmax(power[1:]) + 1)
    return {"frequency_Hz": float(freq[peak]), "fD_over_U": float(freq[peak] * D / U),
            "resolution_Hz": float(1.0 / (len(xx) * dt))}


def write_time_csv(out: Path, rows: list[dict]) -> None:
    fields = ["time_s", "y_m", "v_mps", "a_mps2", "Fy_N", "Cm", "Cd", "Cl",
              "mechanical_energy_J", "cumulative_fluid_work_J", "energy_balance_defect_J",
              "iteration_count", "window_index", "force_time_s", "force_time_delta_s"]
    with (out / "time_history_20k_resume.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fields} for row in rows)


def write_cycle_csv(out: Path, cycles: list[dict]) -> None:
    fields = list(cycles[0]) if cycles else ["cycle_index"]
    with (out / "cycle_statistics_20k_resume.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(cycles)


def make_figures(out: Path, rows: list[dict], cycles: list[dict]) -> None:
    t = np.asarray([row["time_s"] for row in rows])
    y = np.asarray([row["y_m"] for row in rows]) / D
    v = np.asarray([row["v_mps"] for row in rows])
    fy = np.asarray([row["Fy_N"] for row in rows])
    cl = np.asarray([row["Cl"] for row in rows])
    cd = np.asarray([row["Cd"] for row in rows])
    energy = np.asarray([row["mechanical_energy_J"] for row in rows])
    work = np.asarray([row["cumulative_fluid_work_J"] for row in rows])
    it = np.asarray([row["iteration_count"] for row in rows])
    color = "#1565a8"
    orange = "#d97904"

    fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.plot(t, y, color=color, lw=0.75)
    ax.set(xlabel="Physical time, t (s)", ylabel="y/D", title="20k continuation: accepted displacement")
    savefig(fig, out, "y_time_history_20k_resume")

    if cycles:
        idx = np.arange(1, len(cycles) + 1)
        amp = np.asarray([c["A_over_D"] for c in cycles])
        freq = np.asarray([c["fD_over_U"] for c in cycles])
        cla = np.asarray([c["CL_amplitude_half_peak_to_peak"] for c in cycles])
        mcd = np.asarray([c["mean_CD"] for c in cycles])
        fig, ax = plt.subplots(figsize=(6.4, 3.0)); ax.plot(idx, amp, "o-", color=color, ms=3)
        ax.axhline(SHIELS["A_over_D"], color="0.35", ls="--", lw=0.8, label="Shiels 0.57")
        ax.set(xlabel="Cycle index", ylabel="A/D", title="Cycle amplitude"); ax.legend(fontsize=7)
        savefig(fig, out, "cycle_amplitude_20k_resume")
        fig, ax = plt.subplots(figsize=(6.4, 3.0)); ax.plot(idx, amp, "o-", color=color, ms=3, label="A/D")
        ax.plot(idx, np.asarray([c["y_max_m"] for c in cycles]), "^-", color=orange, ms=3, label="ymax/D")
        ax.plot(idx, np.asarray([c["y_min_m"] for c in cycles]), "v-", color="#5c3d99", ms=3, label="ymin/D")
        ax.set(xlabel="Cycle index", ylabel="Displacement / D", title="Peak and trough envelope"); ax.legend(fontsize=7)
        savefig(fig, out, "amplitude_envelope_20k_resume")
        fig, ax = plt.subplots(figsize=(6.4, 3.0)); ax.plot(idx, freq, "o-", color=color, ms=3)
        ax.axhline(SHIELS["fD_over_U"], color="0.35", ls="--", lw=0.8)
        ax.set(xlabel="Cycle index", ylabel="fD/U", title="Cycle frequency")
        savefig(fig, out, "cycle_frequency_20k_resume")
        fig, ax = plt.subplots(figsize=(6.4, 3.0)); ax.plot(idx, cla, "o-", color=orange, ms=3)
        ax.axhline(SHIELS["CL_amplitude"], color="0.35", ls="--", lw=0.8)
        ax.set(xlabel="Cycle index", ylabel="CL amplitude", title="Lift amplitude by cycle")
        savefig(fig, out, "cycle_lift_amplitude_20k_resume")
        fig, ax = plt.subplots(figsize=(6.4, 3.0)); ax.plot(idx, mcd, "o-", color="#238b45", ms=3)
        ax.axhline(SHIELS["CD_mean"], color="0.35", ls="--", lw=0.8)
        ax.set(xlabel="Cycle index", ylabel="mean CD", title="Mean drag coefficient by cycle")
        savefig(fig, out, "cycle_mean_cd_20k_resume")

    fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.plot(t, cl, color=orange, lw=0.65)
    ax.set(xlabel="Physical time, t (s)", ylabel="CL", title="Lift coefficient")
    savefig(fig, out, "lift_time_history_20k_resume")

    def psd_plot(x: np.ndarray, label: str, stem: str, title: str) -> None:
        dt = float(np.median(np.diff(t))); freq = np.fft.rfftfreq(len(x), dt)
        power = np.abs(np.fft.rfft(signal.detrend(x))) ** 2; mask = freq > 0
        fig, ax = plt.subplots(figsize=(6.4, 3.0)); ax.plot(freq[mask] * D / U, power[mask], color=color, lw=0.75)
        ax.set(xlabel="fD/U", ylabel="Power (a.u.)", title=title); ax.set_xlim(0, 0.6)
        savefig(fig, out, stem)
    psd_plot(y, "y/D", "displacement_psd_20k_resume", "Displacement spectrum")
    psd_plot(cl, "CL", "lift_psd_20k_resume", "Lift spectrum")

    fig, ax = plt.subplots(figsize=(4.0, 3.4)); ax.plot(y, cl, color=orange, lw=0.7)
    ax.set(xlabel="y/D", ylabel="CL", title="CL–displacement phase portrait")
    savefig(fig, out, "lift_displacement_phase_20k_resume")

    fig, ax = plt.subplots(figsize=(7.0, 3.0)); ax.plot(t, energy, color=color, lw=0.8, label="mechanical energy")
    ax2 = ax.twinx(); ax2.plot(t, work, color=orange, lw=0.8, label="cumulative fluid work")
    ax.set(xlabel="Physical time, t (s)", ylabel="E (J)"); ax2.set_ylabel("Fluid work (J)")
    ax.set_title("Mechanical energy and cumulative fluid work")
    savefig(fig, out, "energy_work_history_20k_resume")

    fig, ax = plt.subplots(figsize=(7.0, 2.6)); ax.step(t, it, where="post", color="#238b45", lw=0.8)
    ax.set(xlabel="Physical time, t (s)", ylabel="Accepted coupling iterations", title="Coupling iterations")
    savefig(fig, out, "coupling_iterations_history_20k_resume")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    run = args.run.resolve()
    out = (args.out.resolve() if args.out else run / "postprocess_20k_resume_v1")
    out.mkdir(parents=True, exist_ok=True)
    rows, initial, event_counts = parse_accepted(run)
    coeffs = parse_force_coeffs(run)
    merge_coeffs(rows, coeffs)
    cycles = cycle_stats(rows)
    quality = parse_solver_quality(run)
    y = np.asarray([row["y_m"] for row in rows])
    v = np.asarray([row["v_mps"] for row in rows])
    a = np.asarray([row["a_mps2"] for row in rows])
    fy = np.asarray([row["Fy_N"] for row in rows])
    stable = cycles[-5:] if len(cycles) >= 5 else cycles
    def mean(key: str) -> float | None:
        return float(np.mean([c[key] for c in stable])) if stable else None
    def std(key: str) -> float | None:
        return float(np.std([c[key] for c in stable], ddof=1)) if len(stable) > 1 else None
    metrics = {
        "schema_version": "shiels-s5-k988-20k-resume-offline-analysis-v1",
        "run": str(run), "output": str(out),
        "data_scope": {"start_time_s": float(rows[0]["time_s"]), "end_time_s": float(rows[-1]["time_s"]),
                        "accepted_samples_including_restart": len(rows), "accepted_continuation_windows": len(rows) - 1,
                        "force_coeff_unique_times": len(coeffs), "force_rows_deduplicated": True},
        "event_counts": dict(event_counts),
        "status": {"returns_txt": (run / "returns.txt").read_text(encoding="utf-8").strip(),
                   "structure_summary": json.loads((run / "structure" / "structure_summary.json").read_text(encoding="utf-8"))},
        "quality": quality,
        "extrema": {"max_abs_y_m": float(np.max(np.abs(y))), "max_abs_v_mps": float(np.max(np.abs(v))),
                     "max_abs_a_mps2": float(np.max(np.abs(a))), "max_abs_Fy_N": float(np.max(np.abs(fy))),
                     "max_abs_CL": float(np.max(np.abs([r["Cl"] for r in rows]))),
                     "max_Cd": float(np.max([r["Cd"] for r in rows])), "min_Cd": float(np.min([r["Cd"] for r in rows]))},
        "cycles": {"count": len(cycles), "stable_window_definition": "last five complete positive-going-zero-crossing cycles if available",
                   "stable_cycle_count": len(stable),
                   "stable_means": {"A_over_D": mean("A_over_D"), "fD_over_U": mean("fD_over_U"),
                                    "CL_amplitude": mean("CL_amplitude_half_peak_to_peak"), "mean_CD": mean("mean_CD")},
                   "stable_sample_std": {"A_over_D": std("A_over_D"), "fD_over_U": std("fD_over_U"),
                                         "CL_amplitude": std("CL_amplitude_half_peak_to_peak"), "mean_CD": std("mean_CD")}},
        "shiels_reference": SHIELS,
        "interpretation": "This is a 224-260 s continuation segment at dt=0.01 s; it is not a replacement for the full historical 150 s or fixed-cylinder V&V records.",
    }
    for key, refkey in [("A_over_D", "A_over_D"), ("fD_over_U", "fD_over_U"), ("CL_amplitude", "CL_amplitude"), ("mean_CD", "CD_mean")]:
        val = metrics["cycles"]["stable_means"][key]
        metrics.setdefault("comparison_to_Shiels", {})[key] = None if val is None else {"value": val, "reference": SHIELS[refkey], "relative_error": float((val - SHIELS[refkey]) / SHIELS[refkey])}
    write_json(out / "metrics_20k_resume.json", metrics)
    write_time_csv(out, rows)
    write_cycle_csv(out, cycles)
    make_figures(out, rows, cycles)
    report = [
        "# 20k 单切片自由FSI续算离线结果",
        "",
        f"- 数据范围：OF {rows[0]['time_s']:.9f}–{rows[-1]['time_s']:.9f} s；续算接受窗口 {len(rows)-1}。",
        f"- 运行返回：`{metrics['status']['returns_txt']}`；原始 `structure_summary.status={metrics['status']['structure_summary']['status']}`。",
        f"- trial/restore：{metrics['status']['structure_summary']['trial_attempts']} / {metrics['status']['structure_summary']['checkpoint_restores']}；每窗口迭代数：{sorted(set(r['iteration_count'] for r in rows[1:]))}。",
        f"- 最大 Co：{quality['max_Co']:.6g}；最大绝对 global continuity：{quality['max_abs_global_continuity']:.6g}。",
        f"- 最大 |y|={metrics['extrema']['max_abs_y_m']:.6g} m，最大 |v|={metrics['extrema']['max_abs_v_mps']:.6g} m/s，最大 |Fy|={metrics['extrema']['max_abs_Fy_N']:.6g} N。",
        "",
        "## 完整周期统计",
        "",
        f"识别到 {len(cycles)} 个完整正向过零周期；末端统计采用最后 {len(stable)} 个完整周期（若不足5个则全部采用）。逐周期数据见 `cycle_statistics_20k_resume.csv`。",
        "",
        "| 指标 | 末端周期均值 | Shiels参考 | 相对误差 |",
        "|---|---:|---:|---:|",
    ]
    for label, key, ref in [("A/D", "A_over_D", "A_over_D"), ("fD/U", "fD_over_U", "fD_over_U"), ("CL半峰峰幅值", "CL_amplitude", "CL_amplitude"), ("mean CD", "mean_CD", "CD_mean")]:
        val = metrics["cycles"]["stable_means"][key]
        rel = (val - SHIELS[ref]) / SHIELS[ref] if val is not None else math.nan
        report.append(f"| {label} | {val:.8f} | {SHIELS[ref]:.8f} | {rel:+.3%} |" if val is not None else f"| {label} | n/a | {SHIELS[ref]:.8f} | n/a |")
    report += [
        "",
        "## 判读",
        "",
        f"末5周期的 A/D、fD/U、CL 幅值、mean CD 样本CV分别为 "
        f"{np.std([c['A_over_D'] for c in stable], ddof=1) / np.mean([c['A_over_D'] for c in stable]):.3%}、"
        f"{np.std([c['fD_over_U'] for c in stable], ddof=1) / np.mean([c['fD_over_U'] for c in stable]):.3%}、"
        f"{np.std([c['CL_amplitude_half_peak_to_peak'] for c in stable], ddof=1) / np.mean([c['CL_amplitude_half_peak_to_peak'] for c in stable]):.3%}、"
        f"{np.std([c['mean_CD'] for c in stable], ddof=1) / np.mean([c['mean_CD'] for c in stable]):.3%}。"
        "尽管这些离散度较小，A/D 和 CL 幅值在该短续算段仍呈缓慢上升，故本报告只把它作为20k、dt=0.01 s续算片段的趋势和数值质量证据，不单独宣布新的稳态文献复现结论。",
        "当前 runtime 的 `fluid.stdout` 未包含一次新的 `checkMesh` 输出；因此本报告不把几何检查标记为本次续算已完成，保留已有网格检查证据。",
        "原始日志、事件和场文件未修改。",
        "",
        "输出：`metrics_20k_resume.json`、`time_history_20k_resume.csv`、`cycle_statistics_20k_resume.csv`及同目录PNG/SVG图。",
    ]
    (out / "REPORT_20K_RESUME_224_TO_260.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"run": str(run), "out": str(out), "cycles": len(cycles), "end_time_s": rows[-1]["time_s"], "stable": metrics["cycles"]["stable_means"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
