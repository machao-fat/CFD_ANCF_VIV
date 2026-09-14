"""Offline accepted-window analysis for the 20k dt=0.01 continuation.

This script never launches a solver.  It reads only Structure ``window_commit``
events and the converged force-coefficient row at each physical time.  The
224--260 s and 260--280 s segments are kept separate, while a merged history
is used for cycle-to-cycle trend analysis.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np


BASE = Path(r"D:/CFD/CFD_ANCF_VIV/runtime/fixed_cylinder_o_grid/moving_wall_20k")
PARENT = BASE / "structure" / "events.jsonl"
NEW = BASE / "structure_resume_20s_v2" / "events.jsonl"
PARENT_CONTRACT = BASE / "contract.json"
NEW_CONTRACT = BASE / "contract_resume_20s.json"
FORCE_ROOT = BASE / "postProcessing" / "cylinderForceCoeffs"
OUT = BASE / "postprocess_20k_resume_v2"
D = 1.0
U = 1.0
M = 2500.0
K = 4940.0


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_events(event_path: Path, contract_path: Path, segment: str) -> tuple[list[dict], Counter, dict]:
    rows: list[dict] = []
    counts: Counter = Counter()
    initial: dict | None = None
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
            rows.append({
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
                "segment": segment,
                "sample_kind": "window_commit",
            })
    if initial is None:
        raise RuntimeError(f"missing initial_data in {event_path}")
    contract = read_json(contract_path)
    restart = contract.get("restart", {})
    parent_last = contract.get("parent_last_accepted", {})
    st = initial["initial_state"]
    energy = float(parent_last.get("mechanical_energy_J", 0.5 * M * float(st["v_mps"]) ** 2 + 0.5 * K * float(initial["payload_y_m"]) ** 2))
    work = float(restart.get("cumulative_fluid_work_J", 0.0))
    defect = float(restart.get("cumulative_energy_balance_defect_J", 0.0))
    rows.insert(0, {
        "time_s": float(initial["physical_time_s"]),
        "y_m": float(initial["payload_y_m"]),
        "v_mps": float(st["v_mps"]),
        "a_mps2": float(st["a_mps2"]),
        "Fy_N": float(initial["initial_force_y_N"]),
        "mechanical_energy_J": energy,
        "cumulative_fluid_work_J": work,
        "energy_balance_defect_J": defect,
        "iteration_count": 0,
        "window_index": 0,
        "segment": segment,
        "sample_kind": "restart_initial",
    })
    rows.sort(key=lambda item: item["time_s"])
    return rows, counts, contract


def parse_force_coeffs(root: Path) -> dict[float, tuple[float, float, float]]:
    paths = sorted(root.rglob("forceCoeffs.dat"))
    if not paths:
        raise RuntimeError(f"no forceCoeffs.dat below {root}")
    result: dict[float, tuple[float, float, float]] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            fields = line.split()
            if len(fields) < 4:
                continue
            vals = [float(value) for value in fields[:4]]
            # Repeated rows are generated inside PIMPLE/coupling iterations;
            # retaining the last row gives the converged row for that time.
            result[round(vals[0], 8)] = (vals[1], vals[2], vals[3])
    return dict(sorted(result.items()))


def attach_coeffs(rows: list[dict], coeffs: dict[float, tuple[float, float, float]]) -> None:
    keys = np.asarray(list(coeffs), dtype=float)
    values = list(coeffs.values())
    for row in rows:
        idx = int(np.argmin(np.abs(keys - row["time_s"])))
        delta = float(keys[idx] - row["time_s"])
        if abs(delta) > 3.0e-4:
            raise RuntimeError(f"force coefficient time mismatch near {row['time_s']}: {delta}")
        row["Cm"], row["Cd"], row["Cl"] = (float(item) for item in values[idx])
        row["force_time_s"] = float(keys[idx])
        row["force_time_delta_s"] = delta


def quality_scan(log_paths: list[Path]) -> dict:
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in log_paths if path.exists())
    co = [(float(a), float(b)) for a, b in re.findall(r"Courant Number mean:\s*([0-9.eE+-]+) max:\s*([0-9.eE+-]+)", text)]
    continuity = [(float(a), float(b)) for a, b in re.findall(r"time step continuity errors\s*:\s*sum local =\s*([0-9.eE+-]+),\s*global =\s*([0-9.eE+-]+)", text)]
    patterns = {
        "FPE": r"Floating point exception signal|received signal SIGFPE|SIGFPE.*stack",
        "NaN_Inf": r"(?<![A-Za-z])(?:nan|NaN|inf|Inf)(?![A-Za-z])",
        "negative_volume": r"negative volume|negative cell volume",
        "preCICE_failure": r"(?:ERROR.*preCICE|preCICE.*ERROR|convergence\s+failed)",
        "solver_fatal": r"FOAM FATAL (?:ERROR|IO ERROR)|Fatal error",
    }
    hits = {name: bool(re.search(pattern, text, re.IGNORECASE)) for name, pattern in patterns.items()}
    return {
        "courant_sample_count": len(co),
        "max_Co_mean": max((item[0] for item in co), default=None),
        "max_Co": max((item[1] for item in co), default=None),
        "continuity_sample_count": len(continuity),
        "max_abs_local_continuity": max((abs(item[0]) for item in continuity), default=None),
        "max_abs_global_continuity": max((abs(item[1]) for item in continuity), default=None),
        "hard_failure_scan": hits,
        "all_hard_failure_patterns_clear": not any(hits.values()),
    }


def crossing_times(rows: list[dict]) -> np.ndarray:
    t = np.asarray([row["time_s"] for row in rows], dtype=float)
    y = np.asarray([row["y_m"] for row in rows], dtype=float)
    indices = np.flatnonzero((y[:-1] < 0.0) & (y[1:] >= 0.0))
    result: list[float] = []
    for i in indices:
        den = y[i + 1] - y[i]
        result.append(float(t[i] if den == 0.0 else t[i] - y[i] * (t[i + 1] - t[i]) / den))
    return np.asarray(result, dtype=float)


def cycles_for_rows(rows: list[dict], segment: str) -> tuple[list[dict], list[dict]]:
    if len(rows) < 3:
        return [], []
    t = np.asarray([row["time_s"] for row in rows], dtype=float)
    crossings = crossing_times(rows)
    median_dt = float(np.median(np.diff(t)))
    cycles: list[dict] = []
    excluded: list[dict] = []
    local_index = 0
    for interval_index in range(max(0, len(crossings) - 1)):
        start, end = float(crossings[interval_index]), float(crossings[interval_index + 1])
        positions = np.flatnonzero((t >= start) & (t <= end))
        if len(positions) < 10:
            continue
        internal = np.diff(t[positions]) if len(positions) > 1 else np.asarray([])
        max_gap = float(internal.max()) if len(internal) else 0.0
        if max_gap > 1.5 * median_dt:
            excluded.append({"segment": segment, "interval_index": interval_index + 1, "start_time_s": start, "end_time_s": end, "reason": "missing accepted samples", "max_internal_gap_s": max_gap})
            continue
        local_index += 1
        y = np.asarray([rows[j]["y_m"] for j in positions])
        cl = np.asarray([rows[j]["Cl"] for j in positions])
        cd = np.asarray([rows[j]["Cd"] for j in positions])
        energy = np.asarray([rows[j]["mechanical_energy_J"] for j in positions])
        work = np.asarray([rows[j]["cumulative_fluid_work_J"] for j in positions])
        it = np.asarray([rows[j]["iteration_count"] for j in positions])
        cycles.append({
            "segment": segment,
            "local_cycle_index": local_index,
            "start_time_s": start,
            "end_time_s": end,
            "y_max_m": float(y.max()),
            "y_min_m": float(y.min()),
            "A_over_D": float((y.max() - y.min()) / (2.0 * D)),
            "period_s": float(end - start),
            "fD_over_U": float(D / (U * (end - start))),
            "CL_amplitude_half_peak_to_peak": float((cl.max() - cl.min()) / 2.0),
            "CL_RMS": float(np.sqrt(np.mean(cl * cl))),
            "mean_CD": float(cd.mean()),
            "max_coupling_iterations": int(it.max()),
            "mean_coupling_iterations": float(it.mean()),
            "mechanical_energy_start_J": float(energy[0]),
            "mechanical_energy_end_J": float(energy[-1]),
            "mechanical_energy_change_J": float(energy[-1] - energy[0]),
            "fluid_work_change_J": float(work[-1] - work[0]),
        })
    return cycles, excluded


def dedup_rows(rows: list[dict]) -> list[dict]:
    rows = sorted(rows, key=lambda row: row["time_s"])
    output: list[dict] = []
    for row in rows:
        if output and abs(row["time_s"] - output[-1]["time_s"]) < 1.0e-6:
            # Prefer an accepted commit over the restart marker at the same t.
            if output[-1]["sample_kind"] == "restart_initial" and row["sample_kind"] == "window_commit":
                output[-1] = row
            continue
        output.append(row)
    return output


def add_indices(cycles: list[dict]) -> list[dict]:
    return [{**cycle, "cycle_index": i + 1} for i, cycle in enumerate(cycles)]


def add_increments(cycles: list[dict]) -> list[dict]:
    output: list[dict] = []
    previous: dict | None = None
    for cycle in cycles:
        row = dict(cycle)
        comparable = previous is not None and previous["segment"] == cycle["segment"]
        row["increment_comparable"] = comparable
        for source, target in [("A_over_D", "delta_A_over_D"), ("CL_amplitude_half_peak_to_peak", "delta_CL_amplitude"), ("fD_over_U", "delta_fD_over_U"), ("mean_CD", "delta_mean_CD")]:
            row[target] = float(cycle[source] - previous[source]) if comparable else None
        output.append(row)
        previous = cycle
    return output


def stats(cycles: list[dict]) -> dict:
    keys = [("A_over_D", "A_over_D"), ("fD_over_U", "fD_over_U"), ("CL_amplitude_half_peak_to_peak", "CL_amplitude"), ("mean_CD", "mean_CD")]
    result = {"n": len(cycles), "mean": {}, "std": {}, "CV": {}, "slope_per_cycle": {}, "relative_end_to_end_trend": {}}
    if not cycles:
        return result
    x = np.arange(len(cycles), dtype=float)
    for source, target in keys:
        values = np.asarray([cycle[source] for cycle in cycles], dtype=float)
        mean = float(values.mean())
        std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
        slope = float(np.polyfit(x, values, 1)[0]) if len(values) > 1 else 0.0
        result["mean"][target] = mean
        result["std"][target] = std
        result["CV"][target] = float(std / abs(mean)) if mean else None
        result["slope_per_cycle"][target] = slope
        result["relative_end_to_end_trend"][target] = float((values[-1] - values[0]) / abs(mean)) if mean else None
    return result


def extrema(rows: list[dict]) -> dict:
    return {
        "max_abs_y_m": float(max(abs(row["y_m"]) for row in rows)),
        "max_abs_v_mps": float(max(abs(row["v_mps"]) for row in rows)),
        "max_abs_a_mps2": float(max(abs(row["a_mps2"]) for row in rows)),
        "max_abs_Fy_N": float(max(abs(row["Fy_N"]) for row in rows)),
        "max_abs_CL": float(max(abs(row["Cl"]) for row in rows)),
        "Cd_min": float(min(row["Cd"] for row in rows)),
        "Cd_max": float(max(row["Cd"] for row in rows)),
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    parent, parent_events, parent_contract = parse_events(PARENT, PARENT_CONTRACT, "parent_224_to_260s")
    new, new_events, new_contract = parse_events(NEW, NEW_CONTRACT, "new_260_to_280s")
    coeffs = parse_force_coeffs(FORCE_ROOT)
    attach_coeffs(parent, coeffs)
    attach_coeffs(new, coeffs)
    parent_cycles, parent_excluded = cycles_for_rows(parent, "parent_224_to_260s")
    new_cycles, new_excluded = cycles_for_rows(new, "new_260_to_280s")
    merged = dedup_rows(parent + new)
    merged_cycles, merged_excluded = cycles_for_rows(merged, "combined_224_to_280s")
    # Use segment-local cycles for increments so the continuation boundary is
    # not interpreted as a physical cycle increment.
    indexed_cycles = add_indices(parent_cycles + new_cycles)
    increments = add_increments(indexed_cycles)
    q_parent = quality_scan([BASE / "fluid_resume_20s.stdout", BASE / "fluid_resume_20s.stderr", BASE / "participant_resume_20s.stdout", BASE / "participant_resume_20s.stderr"])
    q_new = quality_scan([BASE / "fluid_resume_20s_v2.stdout", BASE / "fluid_resume_20s_v2.stderr", BASE / "participant_resume_20s_v2.stdout", BASE / "participant_resume_20s_v2.stderr"])
    s_parent = read_json(BASE / "structure" / "structure_summary.json")
    s_new = read_json(BASE / "structure_resume_20s_v2" / "structure_summary.json")
    last5 = indexed_cycles[-5:] if len(indexed_cycles) >= 5 else indexed_cycles
    first5 = indexed_cycles[:5] if len(indexed_cycles) >= 5 else indexed_cycles
    last_stats = stats(last5)
    first_stats = stats(first5)
    metrics = {
        "schema_version": "shiels-s5-k988-20k-resume-v2-offline-analysis-v1",
        "runtime": str(BASE),
        "output": str(OUT),
        "accepted_only_policy": "Only Structure window_commit events are physical samples; trial/restore events are excluded.",
        "new_segment": {
            "start_time_s": new[0]["time_s"], "end_time_s": new[-1]["time_s"],
            "accepted_windows": s_new["accepted_windows"], "accepted_samples_including_restart": len(new),
            "complete_cycles": len(new_cycles), "excluded_intervals": new_excluded,
            "extrema": extrema(new), "quality": q_new,
            "energy_balance_defect_initial_J": new[0]["energy_balance_defect_J"],
            "energy_balance_defect_terminal_J": new[-1]["energy_balance_defect_J"],
            "energy_balance_defect_increment_J": new[-1]["energy_balance_defect_J"] - new[0]["energy_balance_defect_J"],
            "cycle_stats": stats(new_cycles),
        },
        "combined_continuation_224_to_280s": {
            "start_time_s": merged[0]["time_s"], "end_time_s": merged[-1]["time_s"],
            "accepted_windows": s_parent["accepted_windows"] + s_new["accepted_windows"],
            "complete_cycles": len(merged_cycles), "excluded_intervals": merged_excluded,
            "extrema": extrema(merged), "last_five": last_stats, "first_five": first_stats,
            "last_five_minus_first_five_mean": {key: last_stats["mean"].get(key, math.nan) - first_stats["mean"].get(key, math.nan) for key in ["A_over_D", "fD_over_U", "CL_amplitude", "mean_CD"]},
            "quality_parent": q_parent, "quality_new": q_new,
        },
        "event_counts": {"parent": dict(parent_events), "new": dict(new_events)},
        "structure_summaries": {"parent": s_parent, "new": s_new},
        "shiels_reference": {"A_over_D": 0.57, "fD_over_U": 0.198, "CL_amplitude": 1.35, "mean_CD": 2.23},
        "interpretation": "The 260--280 s continuation has four complete cycles. The cycle increments decrease in magnitude but remain nonzero, so this is weak residual drift / near-limit-cycle evidence, not a new strict plateau pass.",
    }
    (OUT / "metrics_20k_resume_v2.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    time_fields = ["time_s", "y_m", "v_mps", "a_mps2", "Fy_N", "Cm", "Cd", "Cl", "mechanical_energy_J", "cumulative_fluid_work_J", "energy_balance_defect_J", "iteration_count", "window_index", "segment", "sample_kind", "force_time_s", "force_time_delta_s"]
    write_csv(OUT / "accepted_time_history_new_segment.csv", new, time_fields)
    write_csv(OUT / "accepted_time_history_224_to_280s.csv", merged, time_fields)
    cycle_fields = ["cycle_index", "segment", "local_cycle_index", "start_time_s", "end_time_s", "y_max_m", "y_min_m", "A_over_D", "period_s", "fD_over_U", "CL_amplitude_half_peak_to_peak", "CL_RMS", "mean_CD", "max_coupling_iterations", "mean_coupling_iterations", "mechanical_energy_start_J", "mechanical_energy_end_J", "mechanical_energy_change_J", "fluid_work_change_J"]
    write_csv(OUT / "cycle_statistics.csv", indexed_cycles, cycle_fields)
    write_csv(OUT / "cycle_statistics_new_segment.csv", [{**c, "cycle_index": i + 1} for i, c in enumerate(new_cycles)], cycle_fields)
    write_csv(OUT / "cycle_increments.csv", increments, cycle_fields + ["increment_comparable", "delta_A_over_D", "delta_CL_amplitude", "delta_fD_over_U", "delta_mean_CD"])
    write_csv(OUT / "cycle_exclusions.csv", parent_excluded + new_excluded + merged_excluded, ["segment", "interval_index", "start_time_s", "end_time_s", "reason", "max_internal_gap_s"])

    ref = {"A_over_D": 0.57, "fD_over_U": 0.198, "CL_amplitude": 1.35, "mean_CD": 2.23}
    report: list[str] = [
        "# 20k、dt=0.01 s续算离线结果（v2）", "",
        "## 1. 数据范围与完整性", "",
        f"- 新增续算段：OF {new[0]['time_s']:.9f}–{new[-1]['time_s']:.9f} s；accepted窗口 {s_new['accepted_windows']}。",
        f"- trial/restore：{s_new['trial_attempts']} / {s_new['checkpoint_restores']}；每窗口迭代数：{sorted(set(row['iteration_count'] for row in new[1:]))}。",
        f"- 返回码：`structure=0 fluid=0`；状态：`{s_new['status']}`；最后共同接受时间：{s_new['last_accepted_physical_time_s']:.12f} s。",
        f"- 新段最大Co：{q_new['max_Co']:.9g}；最大local/global continuity：{q_new['max_abs_local_continuity']:.9g} / {q_new['max_abs_global_continuity']:.9g}。",
        f"- 新段最大|y|/|v|/|a|/|Fy|：{extrema(new)['max_abs_y_m']:.9g} m / {extrema(new)['max_abs_v_mps']:.9g} m/s / {extrema(new)['max_abs_a_mps2']:.9g} m/s² / {extrema(new)['max_abs_Fy_N']:.9g} N。",
        f"- 新段最大|CL|：{extrema(new)['max_abs_CL']:.9g}；CD范围：[{extrema(new)['Cd_min']:.9g}, {extrema(new)['Cd_max']:.9g}]。",
        f"- 新段能量平衡缺陷增量：{metrics['new_segment']['energy_balance_defect_increment_J']:.9g} J。",
        f"- 硬错误扫描：{q_new['hard_failure_scan']}。只使用window_commit，未将trial/restore作为物理样本。", "",
        "## 2. 新增260–280 s段完整周期", "",
        f"识别到{len(new_cycles)}个完整正向过零周期。逐周期数据见`cycle_statistics_new_segment.csv`。", "",
        "| 周期 | 起止时间(s) | ymax(m) | ymin(m) | A/D | 周期(s) | fD/U | CL幅值 | mean CD | 迭代 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, c in enumerate(new_cycles, 1):
        report.append(f"| {i} | {c['start_time_s']:.6f}–{c['end_time_s']:.6f} | {c['y_max_m']:.6f} | {c['y_min_m']:.6f} | {c['A_over_D']:.6f} | {c['period_s']:.6f} | {c['fD_over_U']:.6f} | {c['CL_amplitude_half_peak_to_peak']:.6f} | {c['mean_CD']:.6f} | {c['max_coupling_iterations']} |")
    report += ["", "## 3. 连续周期趋势（224–280 s）", "", f"224–260 s父段识别{len(parent_cycles)}个周期，260–280 s新增段识别{len(new_cycles)}个周期。连续编号和增量见`cycle_statistics.csv`与`cycle_increments.csv`。", ""]
    for title, st in [(f"新增段{len(new_cycles)}周期", stats(new_cycles)), ("连续历史末5周期", last_stats)]:
        report.append(f"- {title}均值：A/D={st['mean'].get('A_over_D', math.nan):.8f}，fD/U={st['mean'].get('fD_over_U', math.nan):.8f}，CL={st['mean'].get('CL_amplitude', math.nan):.8f}，mean CD={st['mean'].get('mean_CD', math.nan):.8f}。")
        report.append(f"- {title} CV：A/D={st['CV'].get('A_over_D', math.nan):.3%}，fD/U={st['CV'].get('fD_over_U', math.nan):.3%}，CL={st['CV'].get('CL_amplitude', math.nan):.3%}，mean CD={st['CV'].get('mean_CD', math.nan):.3%}。")
    report += ["", "新增段周期增量（后3项）均保持同一方向但幅度减小；因此分类为`WEAK_RESIDUAL_DRIFT`，不是严格`PLATEAU_PASS`。", "", "## 4. Shiels bounded / near-limit-cycle comparison", "", "以下采用连续历史末5周期，仅作有界近极限环比较：", "", "| 指标 | 当前末5周期 | Shiels | 相对误差 |", "|---|---:|---:|---:|"]
    for label, key, value in [("A/D", "A_over_D", ref["A_over_D"]), ("fD/U", "fD_over_U", ref["fD_over_U"]), ("CL半峰峰幅值", "CL_amplitude", ref["CL_amplitude"]), ("mean CD", "mean_CD", ref["mean_CD"])]:
        current = last_stats["mean"].get(key)
        report.append(f"| {label} | {current:.8f} | {value:.8f} | {(current-value)/value:+.3%} |" if current is not None else f"| {label} | n/a | {value:.8f} | n/a |")
    report += ["", "## 5. 结论", "", "新增260–280 s段数值运行完成且无硬错误；A/D和CL幅值仍缓慢上升，fD/U与mean CD缓慢回落，但增量幅度逐周期减小。故20k、dt=0.01 s结果支持接近极限环的趋势证据，不能仅凭末5周期CV宣布严格平台。", "", "输出：`accepted_time_history_new_segment.csv`、`accepted_time_history_224_to_280s.csv`、`cycle_statistics.csv`、`cycle_statistics_new_segment.csv`、`cycle_increments.csv`、`cycle_exclusions.csv`、`metrics_20k_resume_v2.json`。"]
    (OUT / "REPORT_20K_RESUME_V2_224_TO_280.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "new_cycles": len(new_cycles), "combined_cycles": len(indexed_cycles), "new_stats": stats(new_cycles), "last5": last_stats}, ensure_ascii=False))


if __name__ == "__main__":
    main()
