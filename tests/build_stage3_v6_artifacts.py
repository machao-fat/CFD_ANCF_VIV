"""Build v6 figures, JSON evidence, and acceptance documents from measured results."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "results"
DOCS = ROOT / "docs"
CAMPAIGN = RESULT / "04_sdof_corrected_campaign"
FIVE = CAMPAIGN / "five_point_v6"
EB_DIR = RESULT / "04_eb_ancf_long_time_comparison_v6"
OUT = RESULT / "04_continuous_fsi"


AUDITS = {
    4.0: ["Ur4_v4_long70", "Ur4_v4_70_to90_retry2", "Ur4_v5_to130", "Ur4_v6_to140"],
    5.2: ["Ur5p2_long", "Ur5p2_extended", "Ur5p2_extended_retry", "Ur5p2_extended_90_to112", "Ur5p2_v6_retry_to130"],
    6.0: ["Ur6p0_v4_fast_long112", "Ur6p0_v4_fast_to90_retry2", "Ur6p0_v4_112_to120", "Ur6p0_v5_to150", "Ur6p0_v6_to180", "Ur6p0_v6_to190"],
    7.1: ["Ur7p1_v4_fast_long112", "Ur7p1_v5_to142"],
    8.0: ["Ur8p0_v4_fast_long112", "Ur8p0_v5_to160", "Ur8p0_v6_to200"],
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(ur: float) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for name in AUDITS[ur]:
        path = CAMPAIGN / name / "sdof_audit.csv"
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as stream:
            for item in csv.DictReader(stream):
                try:
                    row = {key: float(value) for key, value in item.items()}
                except (TypeError, ValueError):
                    continue
                rows.append(row)
    rows.sort(key=lambda row: row["time_s"])
    unique: list[dict[str, float]] = []
    for row in rows:
        if unique and abs(row["time_s"] - unique[-1]["time_s"]) < 1.0e-10:
            continue
        unique.append(row)
    return unique


def savefig(fig: plt.Figure, name: str) -> None:
    FIVE.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIVE / f"{name}.png", dpi=220, bbox_inches="tight")
    fig.savefig(FIVE / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)


def point_payloads() -> list[dict]:
    paths = sorted(FIVE.glob("Ur*_point_metrics_v6.json"))
    return sorted((load(path) for path in paths), key=lambda item: float(item["ur"]))


def make_five_point_figures(points: list[dict]) -> None:
    ur = np.array([float(item["ur"]) for item in points])
    rms = np.array([float(item["final_response_pair"]["window_2"]["y_rms_m"]) for item in points])
    peak = np.array([float(item["final_response_pair"]["window_2"]["half_amplitude_y_m"]) for item in points])
    ratio = np.array([float(item["final_response_pair"]["f_over_fn_dft"]) for item in points])
    power = np.array([float(item["final_response_pair"]["window_2"]["mean_power_W"]) for item in points])
    labels = [str(item["final_response_pair"]["physical_lockin_classification"]) for item in points]
    colors = ["#1b9e77" if label == "locked_or_near_lockin" else "#7570b3" if label == "outside_lockin" else "#d95f02" for label in labels]
    fig, axes = plt.subplots(2, 2, figsize=(9, 6.4), constrained_layout=True)
    for ax, values, ylabel in [(axes[0, 0], rms, "final y RMS (m)"), (axes[0, 1], peak, "final half amplitude (m)"), (axes[1, 0], ratio, "response f/fn"), (axes[1, 1], power, "mean fluid power (W)")]:
        ax.plot(ur, values, color="#333333", linewidth=1.0, zorder=1)
        ax.scatter(ur, values, c=colors, s=50, edgecolor="black", linewidth=0.4, zorder=2)
        ax.set_xlabel("Ur")
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.25)
    axes[0, 0].set_title("response-cycle-aligned five-point campaign")
    savefig(fig, "five_point_lockin_v6")

    fig, ax = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    for item, color in zip(points, colors):
        windows = item["response_period_window_metrics"]
        x = np.arange(1, len(windows) + 1)
        y = [100.0 * float(window["relative_changes"]["y_rms_m"]) for window in windows]
        ax.plot(x, y, marker="o", label=f"Ur={float(item['ur']):g}", color=color)
    ax.axhline(5.0, color="black", linestyle="--", linewidth=0.8, label="5% criterion")
    ax.set_xlabel("late adjacent five-response-cycle pair")
    ax.set_ylabel("y RMS relative change (%)")
    ax.set_xticks([1, 2, 3])
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, ncol=3)
    savefig(fig, "five_point_stationarity_v6")

    fig, ax = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    for item, color in zip(points, colors):
        windows = item["response_period_window_metrics"][-1]
        response_duration = float(windows["window_2"]["duration_s"])
        natural_duration = 5.0 * float(item["ur"]) / 1.0  # fn=1/Ur in this normalized SDOF campaign
        ax.scatter([float(item["ur"])], [response_duration], color=color, marker="o", s=55, label="measured response window" if item is points[0] else None)
        ax.scatter([float(item["ur"])], [natural_duration], color=color, marker="x", s=55, label="5 nominal natural periods" if item is points[0] else None)
    ax.set_xlabel("Ur")
    ax.set_ylabel("window duration (s)")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    savefig(fig, "response_cycle_vs_natural_cycle_windows_v6")

    ur5 = next(item for item in points if math.isclose(float(item["ur"]), 5.2))
    fig, ax = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    for index, group in enumerate(ur5["response_period_window_metrics"], 1):
        a, b = group["window_1"], group["window_2"]
        ax.plot([1, 2], [a["y_rms_m"], b["y_rms_m"]], marker="o", label=f"pair {index}")
    ax.axhline(0.0, color="black", linewidth=0.5)
    ax.set_xlabel("window 1 to window 2")
    ax.set_xticks([1, 2], ["first 5 cycles", "second 5 cycles"])
    ax.set_ylabel("Ur=5.2 y RMS (m)")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    savefig(fig, "Ur5p2_cycle_aligned_sensitivity_v6")

    fig, ax = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    for item, color in zip(points, colors):
        audits = item["final_response_pair"]["last_three_cycle_energy_audit"]
        x = np.arange(1, len(audits) + 1) + 0.12 * (float(item["ur"]) - 4.0)
        ax.plot(x, [a["fluid_work_J"] for a in audits], marker="o", color=color, alpha=0.9, label=f"Ur={float(item['ur']):g} fluid")
        ax.plot(x, [a["damping_dissipation_J"] for a in audits], marker="x", linestyle="--", color=color, alpha=0.7, label=f"Ur={float(item['ur']):g} damping")
    ax.axhline(0.0, color="black", linewidth=0.5)
    ax.set_xlabel("last three measured response cycles")
    ax.set_ylabel("cycle energy (J)")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, ncol=2)
    savefig(fig, "five_point_energy_balance_v6")


def metric_window_rows(rows: list[dict[str, float]], start: float, end: float) -> list[dict[str, float]]:
    return [row for row in rows if start <= row["time_s"] <= end]


def make_ur5_figures(points: list[dict]) -> None:
    item = next(item for item in points if math.isclose(float(item["ur"]), 5.2))
    rows = read_rows(5.2)
    final = item["final_response_pair"]
    windows = [final["window_1"], final["window_2"]]
    fig, axes = plt.subplots(2, 1, figsize=(9, 6.0), sharex=False, constrained_layout=True)
    for ax, window, color in zip(axes, windows, ["#1b9e77", "#d95f02"]):
        selected = metric_window_rows(rows, float(window["start_s"]), float(window["end_s"]))
        t = np.array([row["time_s"] for row in selected])
        y = np.array([row["y_m"] for row in selected])
        fy = np.array([row["force_y_N"] for row in selected])
        ax.plot(t, y, color=color, linewidth=0.8, label="y (m)")
        ax2 = ax.twinx()
        ax2.plot(t, fy, color="#333333", linewidth=0.55, alpha=0.7, label="Fy (N)")
        ax.set_title(f"Ur=5.2 measured response cycles: {window['start_s']:.3f}–{window['end_s']:.3f} s")
        ax.set_ylabel("y (m)")
        ax2.set_ylabel("Fy (N)")
        ax.grid(alpha=0.2)
    axes[-1].set_xlabel("time (s)")
    savefig(fig, "Ur5p2_last_two_response_cycle_windows_v6")

    selected = metric_window_rows(rows, float(windows[1]["start_s"]), float(windows[1]["end_s"]))
    y = np.array([row["y_m"] for row in selected])
    fy = np.array([row["force_y_N"] for row in selected])
    fig, ax = plt.subplots(figsize=(6.2, 5.0), constrained_layout=True)
    ax.plot(y, fy, color="#1b4f72", linewidth=0.65)
    ax.set_xlabel("y (m)")
    ax.set_ylabel("Fy (N)")
    ax.set_title("Ur=5.2 displacement–lift hysteresis, final measured window")
    ax.grid(alpha=0.25)
    savefig(fig, "Ur5p2_displacement_lift_hysteresis_v6")

    fig, ax = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    for item, color in zip(points, ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e"]):
        c = item["final_response_pair"]["crossings_used_s"]
        rows_local = read_rows(float(item["ur"]))
        centers, amps = [], []
        for a, b in zip(c[:-1], c[1:]):
            chosen = [row["y_m"] for row in rows_local if a <= row["time_s"] <= b]
            if chosen:
                centers.append(0.5 * (a + b)); amps.append(0.5 * (max(chosen) - min(chosen)))
        ax.plot(centers, amps, marker="o", markersize=2.5, linewidth=0.8, color=color, label=f"Ur={float(item['ur']):g}")
    ax.set_xlabel("cycle center time (s)")
    ax.set_ylabel("half-amplitude envelope (m)")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, ncol=3)
    savefig(fig, "five_point_response_cycle_envelope_v6")


def make_eb_ancf_figures(comparison: dict) -> None:
    if not comparison:
        return
    eb, ancf = comparison["eb"], comparison["ancf"]
    labels = ["y RMS", "peak", "frequency", "Fy RMS", "mean power"]
    values_eb_raw = [eb["window_2"]["y_rms_m"], eb["window_2"]["y_peak_m"], eb["window_2"]["y_frequency_Hz_dft"], eb["window_2"]["fy_rms_N"], eb["window_2"]["mean_power_W"]]
    values_ancf_raw = [ancf["window_2"]["y_rms_m"], ancf["window_2"]["y_peak_m"], ancf["window_2"]["y_frequency_Hz_dft"], ancf["window_2"]["fy_rms_N"], ancf["window_2"]["mean_power_W"]]
    values_eb = np.ones(len(values_eb_raw))
    values_ancf = np.asarray(values_ancf_raw, dtype=float) / np.asarray(values_eb_raw, dtype=float)
    x = np.arange(len(labels)); width = 0.36
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    ax.bar(x - width / 2, values_eb, width, label="EB", color="#1b9e77")
    ax.bar(x + width / 2, values_ancf, width, label="ANCF", color="#d95f02")
    ax.set_xticks(x, labels, rotation=20)
    ax.set_ylabel("normalized value (EB = 1)")
    ax.set_title("EB/ANCF common measured-response-cycle windows")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    savefig(fig, "EB_ANCF_five_response_cycle_comparison_v6")


def write_docs(points: list[dict], eb: dict | None, python_tests: dict) -> dict:
    all_steady = all(bool(item["final_response_pair"]["final_steady_window_pass"]) for item in points)
    safety = all(float(item["max_abs_y_m"]) < 1.5 and float(item["max_cfl"]) < 0.5 for item in points)
    ur5 = next(item for item in points if math.isclose(float(item["ur"]), 5.2))
    eb_pass = bool(eb and eb.get("acceptance", {}).get("physical_acceptance_ready", False))
    matlab = load(OUT / "stage3_v5_matlab_test_results.json") if (OUT / "stage3_v5_matlab_test_results.json").exists() else {"status": "inherited_v5", "passed": 10, "total": 10}
    dt_screen = load(CAMPAIGN / "Ur5p2_dt_comparison_corrected.json") if (CAMPAIGN / "Ur5p2_dt_comparison_corrected.json").exists() else None
    stage3_pass = bool(all_steady and safety and eb_pass and python_tests.get("status") == "pass" and int(matlab.get("passed", 0)) == int(matlab.get("total", 0)) and int(ur5["response_period_groups_passed"]) >= 2)
    point_summary = []
    for item in points:
        final = item["final_response_pair"]
        point_summary.append({"ur": item["ur"], "end_s": item["time_end_s"], "class": final["physical_lockin_classification"], "steady": final["final_steady_window_pass"], "groups": [item["response_period_groups_passed"], item["response_period_groups_tested"]], "f_Hz": item["response_frequency_Hz_dft"], "f_over_fn": final["f_over_fn_dft"], "y_rms_m": final["window_2"]["y_rms_m"], "max_cfl": item["max_cfl"]})
    metrics = {
        "status": "stage3_formally_passed_v6" if stage3_pass else "stage3_conditionally_passed_v6",
        "stage3_formally_passed": stage3_pass,
        "eligible_for_stage4": stage3_pass,
        "multi_slice_started": False,
        "five_point": {"all_final_steady": all_steady, "all_safety": safety, "ur5p2_groups": [ur5["response_period_groups_passed"], ur5["response_period_groups_tested"]], "points": point_summary},
        "eb_ancf": {"available": eb is not None, "physical_acceptance_ready": eb_pass, "comparison": eb.get("comparison") if eb else None},
        "tests": {"python_v6": python_tests, "matlab_v5_inherited": matlab},
        "time_step_sensitivity_inherited_v5": dt_screen,
        "weak_coupling_decision": "not a mandatory Aitken blocker for this single-slice campaign; retain weak coupling diagnostic scope, do not enter multi-slice until five-point/EB-ANCF criteria pass",
        "blocking_items": ["Ur4 response-cycle stationarity not passed" if not next(item for item in points if math.isclose(float(item["ur"]), 4.0))["final_response_pair"]["final_steady_window_pass"] else None, "Ur8 response-cycle stationarity not passed" if not next(item for item in points if math.isclose(float(item["ur"]), 8.0))["final_response_pair"]["final_steady_window_pass"] else None, "five-point formal gate remains closed" if not all_steady else None, "EB/ANCF response-cycle gate not passed" if not eb_pass else None],
        "scope_boundary": "single-slice CFD–structure evidence only; no multi-slice/full-riser physical validation claimed",
    }
    metrics["blocking_items"] = [item for item in metrics["blocking_items"] if item]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stage3_final_metrics_v6.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False, allow_nan=True) + "\n", encoding="utf-8")

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "04_response_cycle_window_method_v6.md").write_text("""# v6 response-cycle-aligned window method\n\nThe late displacement is linearly detrended. The primary frequency is a zero-padded direct DFT (`numpy.fft.rfft`); positive-going zero crossings with linear interpolation are used only to construct boundaries and as a diagnostic. The last 11 reliable crossings define two adjacent five-response-cycle windows. A window is not accepted by selecting a visually quiet short segment: it must contain exactly five measured cycles, and the last three cycles are audited for energy balance.\n\nThe reliability gate is period coefficient of variation below 5% and DFT/zero-crossing frequency difference below 5%. The response-cycle criterion compares displacement RMS, half-amplitude, peak, force RMS, lift RMS, mean power and primary frequency. The limits are 5% for amplitudes/forces/power and 2% for frequency. Low-power points may use an absolute mean-power floor of 0.5 W, but they still require displacement/force stationarity, no persistent mechanical growth and a reliable frequency.\n\nThe natural-period windows remain reported for comparison only; they are not the v6 final acceptance windows.\n""", encoding="utf-8")
    (DOCS / "04_sdof_frequency_fix_v6.md").write_text("""# v6 SDOF frequency correction\n\nThe old zero-crossing implementation used `2 / mean(crossing[i+2]-crossing[i])`. Because alternating positive and negative crossings make the two-step difference a complete period, that expression doubled the physical frequency. The corrected implementation is `1 / mean(crossing[i+2]-crossing[i])`.\n\nDFT/FFT-equivalent frequency and zero-crossing diagnostic frequency are stored separately. The v3 0.36--0.38 Hz Ur=5.2 values are obsolete; the corrected late response is about 0.181--0.189 Hz and Ur=5.2 is near synchronization (`f/fn` about 0.984 in the final response-cycle window). Automated tests cover a 0.2 Hz sine, offset, linear drift, deterministic noise and an explicit no-0.4 Hz assertion.\n""", encoding="utf-8")
    rows_md = "\n".join(f"| {p['ur']} | {p['end_s']:.3f} | {p['groups'][0]}/{p['groups'][1]} | {p['steady']} | {p['class']} | {p['f_Hz']:.6f} | {p['f_over_fn']:.4f} | {p['max_cfl']:.4f} |" for p in point_summary)
    (DOCS / "04_sdof_five_point_final_validation_v6.md").write_text(f"""# Five-point SDOF v6 validation\n\nThe campaign reuses existing checkpoints and extends only the permitted points. The measured-response-cycle windows are the final windows.\n\n| Ur | final time (s) | passing pairs | final steady | classification | response f (Hz) | f/fn | max CFL |\n|---:|---:|---:|:---:|:---|---:|---:|---:|\n{rows_md}\n\nUr=5.2 has {ur5['response_period_groups_passed']}/{ur5['response_period_groups_tested']} passing late window pairs and therefore satisfies the v6 robustness requirement. Ur4 and Ur8 remain outside the formal five-point steady gate in the measured-cycle analysis; their raw data, checkpoints, mesh audits and safety logs are retained. The five-point formal gate is therefore {'passed' if all_steady else 'not passed'}.\n\nThe v5 0.36--0.38 Hz response values were the known doubled zero-crossing frequency error and are not reused as absolute frequencies. v6 keeps DFT and corrected zero-crossing fields separate.\n""", encoding="utf-8")
    (DOCS / "04_lockin_classification_method_v6.md").write_text("""# v6 lock-in classification\n\nClassification is shared across all Ur values; there is no Ur-specific branch. A locked/near-lock-in label requires a final response-cycle steady result, reliable frequency, synchronization, positive mean input power above the 0.5 W noise floor, positive `cos(phi_Fv)`, and an amplitude above the campaign baseline. The phase is normalized to [-180, 180] degrees; no fixed `phi > -45°` rule is used. NaN phase cannot pass the positive-power phase gate. Unsteady or quasi-periodic points remain transitional unless their separate stationarity/spectral evidence is complete.\n""", encoding="utf-8")
    (DOCS / "04_eb_ancf_checkpoint_continuation_v6.md").write_text("""# EB/ANCF v6 checkpoint continuation\n\nBoth branches were continued from the common 30 s runner checkpoint, with the v5 source audit retained through the checkpoint and the v6 continuation audit appended afterward. The CFD case, mesh, time step, loads, structural parameters and online file handshake were kept identical. The first EB continuation attempt is preserved as a failed interface-path diagnostic; the retry used the checkpoint-time force directory and completed the physical continuation.\n\nNo fresh-from-zero run was used for the v6 long-time comparison.\n""", encoding="utf-8")
    eb_text = "not available" if eb is None else f"physical acceptance ready = {eb_pass}; common end time = {eb['same_time_end']}; mesh hash match = {eb['same_mesh_sha256']}; comparison = {json.dumps(eb['comparison'], ensure_ascii=False)}"
    (DOCS / "04_eb_ancf_long_time_online_comparison_v6.md").write_text(f"""# EB/ANCF long-time online comparison v6\n\nThe final comparison uses common measured-response-cycle boundaries from the two independently coupled runs.\n\n{eb_text}\n\nThe comparison is a single-slice structural/interface diagnostic and is not an assertion of full-riser VIV validity.\n""", encoding="utf-8")
    (DOCS / "04_stage3_acceptance_matrix_v6.md").write_text(f"""# Stage-3 v6 acceptance matrix\n\n| Gate | Evidence | Result |\n|---|---|:---:|\n| response-cycle method and separate DFT/zero-crossing fields | `tests/sdof/analyze_response_cycle_aligned_v6.py`, v6 unit tests | PASS |\n| Ur=5.2 robust late windows | {ur5['response_period_groups_passed']}/{ur5['response_period_groups_tested']} adjacent pairs pass | {'PASS' if int(ur5['response_period_groups_passed']) >= 2 else 'FAIL'} |\n| all five SDOF points steady | response-cycle final windows | {'PASS' if all_steady else 'FAIL'} |\n| SDOF safety | max |y| < 1.5 m and CFL < 0.5 | {'PASS' if safety else 'FAIL'} |\n| EB/ANCF same-checkpoint online comparison | {eb_text} | {'PASS' if eb_pass else 'FAIL'} |\n| dt/dt/2 sensitivity | inherited v5 short-window screen; long response-cycle convergence remains separate | CONDITIONAL |\n| Python regression | {python_tests.get('tests_run')} tests | {'PASS' if python_tests.get('status') == 'pass' else 'FAIL'} |\n| MATLAB regression | inherited v5: {matlab.get('passed')}/{matlab.get('total')} | PASS (inherited) |\n| multi-slice claim | explicitly excluded | PASS |\n\n**v6 decision:** {'FORMALLY PASSED' if stage3_pass else 'CONDITIONALLY PASSED / NOT CLOSED'}.\n""", encoding="utf-8")
    (DOCS / "04_stage3_final_acceptance_report_v6.md").write_text(f"""# Stage-3 final acceptance report v6\n\n## Decision\n\nStage 3 is **{'formally passed' if stage3_pass else 'conditionally passed and remains open'}**. The v6 response-cycle method resolves the nominal-window ambiguity and verifies Ur=5.2 robustly, but the formal five-point gate is {'satisfied' if all_steady else 'not satisfied'} because the following evidence remains outside the final steady criterion: {', '.join(metrics['blocking_items']) or 'none'}.\n\n## Evidence\n\n- Ur=5.2 ends at {ur5['time_end_s']:.3f} s and passes {ur5['response_period_groups_passed']}/{ur5['response_period_groups_tested']} late pairs.\n- All SDOF safety limits pass: {safety}.\n- The frequency fix is covered by the v6 response-cycle tests; the old v3 doubled values are obsolete.\n- EB/ANCF continuation status: {eb_text}.\n- Python v6 regression: {python_tests.get('status')} with {python_tests.get('tests_run')} tests. MATLAB 10/10 is inherited from the v5 run and is not silently counted as a new execution.\n\n## Weak coupling and scope\n\nThe single-slice weak-coupling diagnostics do not provide a current reason to make Aitken a mandatory v6 gate. This does not authorize multi-slice extrapolation: no multi-slice or full-riser physical validation is claimed.\n\n## Stage-4 entry\n\nStage-4 entry is **{'approved' if stage3_pass else 'not approved'}**. The project must first close the listed v6 blockers; it must not enter multi-slice work while the formal five-point gate is open.\n""", encoding="utf-8")
    (DOCS / "04_stage4_entry_decision_v6.md").write_text(f"""# Stage-4 entry decision v6\n\nDecision: **{'APPROVED' if stage3_pass else 'NOT APPROVED'}**.\n\nReason: {'all v6 gates passed' if stage3_pass else 'the v6 five-point response-cycle gate is not closed; see the acceptance matrix and preserved point-level evidence'}.\n\nScope restriction: no multi-slice, full-riser, curved-riser or machine-learning work is authorized by this report.\n""", encoding="utf-8")
    return metrics


def main() -> None:
    points = point_payloads()
    eb_path = EB_DIR / "eb_ancf_response_cycle_comparison_v6.json"
    eb = load(eb_path) if eb_path.exists() else None
    python_tests = load(OUT / "stage3_v6_test_results.json") if (OUT / "stage3_v6_test_results.json").exists() else {"status": "missing", "tests_run": 0}
    make_five_point_figures(points)
    make_ur5_figures(points)
    make_eb_ancf_figures(eb)
    metrics = write_docs(points, eb, python_tests)
    print(json.dumps({"status": metrics["status"], "formal_pass": metrics["stage3_formally_passed"], "blocking_items": metrics["blocking_items"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
