"""Build v7 metrics and acceptance documents from measured v7/v6 evidence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
RESULTS = ROOT / "results"
CAMPAIGN = RESULTS / "04_sdof_corrected_campaign"
ASYM = CAMPAIGN / "asymptotic_v7"
FIVE = CAMPAIGN / "five_point_v6"
OUT = RESULTS / "04_continuous_fsi"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def point_summary() -> list[dict]:
    points = []
    asym = {4.0: load(ASYM / "Ur4_asymptotic_v7.json"), 8.0: load(ASYM / "Ur8_asymptotic_v7.json")}
    for path in sorted(FIVE.glob("Ur*_point_metrics_v6.json")):
        item = load(path)
        ur = float(item["ur"])
        if ur in asym:
            payload = asym[ur]
            points.append({
                "ur": ur, "end_s": payload["fit_window_s"][1],
                "classification": payload["classification"]["class"],
                "asymptotic_pass": payload["classification"]["asymptotically_periodic_outside_lockin"],
                "response_frequency_Hz_dft": payload["frequency_components"]["response_frequency_Hz_dft"],
                "f_over_fn": payload["frequency_components"]["response_f_over_fn"],
                "amplitude_m": payload["fits"]["full_tail"]["As_m"],
                "max_cfl": payload["force_and_energy_audit"]["max_cfl"],
                "max_abs_y_m": payload["safety"]["max_abs_y_m"],
                "safety_pass": payload["safety"]["max_abs_y_pass"] and payload["safety"]["max_cfl_pass"] and payload["safety"]["finite_pass"],
            })
        else:
            final = item["final_response_pair"]
            points.append({
                "ur": ur, "end_s": item["time_end_s"],
                "classification": final["physical_lockin_classification"],
                "asymptotic_pass": None,
                "response_frequency_Hz_dft": item["response_frequency_Hz_dft"],
                "f_over_fn": final["f_over_fn_dft"],
                "amplitude_m": final["window_2"]["half_amplitude_y_m"],
                "max_cfl": item["max_cfl"], "max_abs_y_m": item["max_abs_y_m"],
                "safety_pass": float(item["max_cfl"]) < 0.5 and float(item["max_abs_y_m"]) < 1.5,
                "final_steady_window_pass": final["final_steady_window_pass"],
                "response_period_groups": [item["response_period_groups_passed"], item["response_period_groups_tested"]],
            })
    return sorted(points, key=lambda item: item["ur"])


def build() -> dict:
    ur4 = load(ASYM / "Ur4_asymptotic_v7.json")
    ur8 = load(ASYM / "Ur8_asymptotic_v7.json")
    dt = load(ASYM / "dt_dt2_long_window_v7.json")
    py = load(OUT / "stage3_v7_test_results.json")
    matlab_path = OUT / "stage3_v7_matlab_test_results.json"
    matlab_v5 = load(OUT / "stage3_v5_matlab_test_results.json")
    matlab_source = load(matlab_path) if matlab_path.exists() else matlab_v5
    eb = load(RESULTS / "04_eb_ancf_long_time_comparison_v6" / "eb_ancf_response_cycle_comparison_v6.json")
    points = point_summary()
    locked_points_pass = all(p.get("final_steady_window_pass", False) for p in points if p["ur"] not in (4.0, 8.0))
    safety_pass = all(p["safety_pass"] for p in points) and ur4["safety"]["max_abs_y_pass"] and ur8["safety"]["max_abs_y_pass"]
    matlab = {
        "executed_in_v7": bool(matlab_source.get("executed_in_v7", False)),
        "inherited_from_v5": bool(matlab_source.get("inherited_from_v5", not matlab_path.exists())),
        "execution_timestamp": matlab_source.get("execution_timestamp", "not recorded"),
        "matlab_version": matlab_source.get("matlab_version", "not recorded"),
        "passed": matlab_source.get("passed", 0), "total": matlab_source.get("total", 10),
        "tests": [{"name": t["name"], "passed": t["passed"]} for t in matlab_source.get("tests", [])],
        "interpretation": "v7 MATLAB evidence is marked as a current execution when stage3_v7_matlab_test_results.json exists; otherwise v5 evidence remains explicitly inherited.",
    }
    matlab_label = "current v7 execution" if not matlab["inherited_from_v5"] else "inherited from v5"
    dt_formal = bool(dt.get("formal_long_window_gate", False))
    asym_pass = bool(ur4["classification"]["asymptotically_periodic_outside_lockin"] and ur8["classification"]["asymptotically_periodic_outside_lockin"])
    eb_pass = bool(eb.get("acceptance", {}).get("physical_acceptance_ready", False))
    stage3_pass = bool(asym_pass and locked_points_pass and dt_formal and eb_pass and py.get("status") == "pass" and matlab["passed"] == matlab["total"] and safety_pass)
    blockers = []
    if not ur4["classification"]["asymptotically_periodic_outside_lockin"]:
        blockers.append("Ur4 asymptotic outside-lock-in classification failed")
    if not ur8["classification"]["asymptotically_periodic_outside_lockin"]:
        blockers.append("Ur8 asymptotic outside-lock-in classification failed: prediction residual gate remains open")
    if not locked_points_pass:
        blockers.append("one or more lock-in points lack final measured-response-cycle stationarity")
    if not dt_formal:
        blockers.append("dt/dt2 evidence is an existing 0-10 s, 0.9615-cycle scheme-B screening only; long-window scheme-A gate remains open")
    if not eb_pass:
        blockers.append("EB/ANCF common-response-cycle comparison is not physically ready")
    if py.get("status") != "pass":
        blockers.append("Python regression failure")
    metrics = {
        "schema_version": "stage3_final_metrics_v7",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "stage3_fully_passed_v7" if stage3_pass else "stage3_conditionally_passed_v7_not_closed",
        "stage3_fully_passed": stage3_pass,
        "eligible_for_stage4_prototype": stage3_pass,
        "eligible_for_stage4": stage3_pass,
        "multi_slice_started": False,
        "five_point": {"points": points, "Ur4_Ur8_asymptotic_pass": asym_pass, "lockin_points_pass": locked_points_pass, "safety_pass": safety_pass},
        "asymptotic_outside_lockin": {"Ur4": ur4, "Ur8": ur8, "initial_Ur8_200s": load(ASYM / "Ur8_asymptotic_v7_initial200.json")},
        "dt_dt2": dt,
        "eb_ancf": {"source": "results/04_eb_ancf_long_time_comparison_v6/eb_ancf_response_cycle_comparison_v6.json", "physical_acceptance_ready": eb_pass, "common_response_cycle_boundaries": eb.get("comparison", {}).get("common_response_cycle_boundaries_s")},
        "tests": {"python_v7": py, "matlab": matlab},
        "weak_coupling_decision": {"aitken_required_for_current_single_slice_evidence": False, "reason": "coupling defect is approximately 1e-6 J while cycle fluid work is O(1e2) J in the locked cases; no unexplained energy growth or residual divergence was observed", "formal_stage3_gate": "still blocked by long-window dt/dt2 evidence, not by a current Aitken requirement"},
        "blocking_items": blockers,
        "scope_boundary": "single-DOF and single-slice evidence only; no multi-slice or full-riser physical validation is claimed",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stage3_final_metrics_v7.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return metrics


def write_docs(metrics: dict) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    ur4 = metrics["asymptotic_outside_lockin"]["Ur4"]
    ur8 = metrics["asymptotic_outside_lockin"]["Ur8"]
    dt = metrics["dt_dt2"]
    matlab_label = "current v7 execution" if not metrics["tests"]["matlab"]["inherited_from_v5"] else "inherited from v5"
    point_rows = []
    for p in metrics["five_point"]["points"]:
        point_rows.append(f"| {p['ur']:g} | {p['end_s']:.3f} | {p['classification']} | {p['response_frequency_Hz_dft']:.6f} | {p['f_over_fn']:.4f} | {p['max_cfl']:.4f} | {p['safety_pass']} |")
    (DOCS / "04_asymptotic_outside_lockin_method_v7.md").write_text("""# v7 forced/free asymptotic decomposition

The late response is fitted as

`y(t)=c0+c1*t+As*sin(2*pi*fs*t+phis)+An*exp(-lambda*(t-t0))*sin(2*pi*fn*t+phin)`.

`fs` is measured independently from late pressure/viscous total force and `Cl` with a detrended, zero-padded DFT. `fn` is calculated from the unchanged structural parameters. For each trial `lambda`, all other coefficients are solved by `numpy.linalg.lstsq`; `lambda` is bounded and minimized with `scipy.optimize.minimize_scalar(method='bounded')`. The executed environment records SciPy 1.13.1 and NumPy 2.0.2. No Ur-number branch is present in the classifier.

The diagnostic separates the raw response, forced component, free component, full fit, first-half extrapolation and residual spectrum. A fitted component is never relabelled as an FFT/DFT frequency. Ur=4 is allowed to use the protocol's negligible-free-tail exception: when the fitted free/forced ratio at the end of the accepted tail is below 5%, its decay rate is treated as weakly identifiable, while the independent force/frequency, fit, prediction, energy and safety gates remain mandatory.

The twelve-condition summary and all numerical values are stored in `results/04_sdof_corrected_campaign/asymptotic_v7/Ur4_asymptotic_v7.json` and `Ur8_asymptotic_v7.json`.
""", encoding="utf-8")
    (DOCS / "04_ur4_ur8_transient_decomposition_v7.md").write_text(f"""# Ur=4 and Ur=8 transient decomposition v7

| point | fit interval (s) | response f (Hz) | f/fn | force f windows (Hz) | lambda fit/theory (1/s) | free/forced at tail end | fit residual | prediction residual | class |
|---:|---:|---:|---:|---|---:|---:|---:|---:|---|
| 4 | {ur4['fit_window_s'][0]:.2f}--{ur4['fit_window_s'][1]:.2f} | {ur4['frequency_components']['response_frequency_Hz_dft']:.6f} | {ur4['frequency_components']['response_f_over_fn']:.4f} | {ur4['frequency_components']['shedding_force']['force_window_1_Hz_dft']:.6f}/{ur4['frequency_components']['shedding_force']['force_window_2_Hz_dft']:.6f} | {ur4['fits']['first_half']['lambda_fit']:.6g}/{ur4['lambda_theory_1_per_s']:.6g} | {ur4['parameter_stability']['free_tail_over_forced_at_end']:.4%} | {ur4['fits']['full_tail']['normalized_residual_rms']:.2%} | {ur4['prediction']['normalized_residual_rms']:.2%} | {ur4['classification']['class']} |
| 8 | {ur8['fit_window_s'][0]:.2f}--{ur8['fit_window_s'][1]:.2f} | {ur8['frequency_components']['response_frequency_Hz_dft']:.6f} | {ur8['frequency_components']['response_f_over_fn']:.4f} | {ur8['frequency_components']['shedding_force']['force_window_1_Hz_dft']:.6f}/{ur8['frequency_components']['shedding_force']['force_window_2_Hz_dft']:.6f} | {ur8['fits']['first_half']['lambda_fit']:.6g}/{ur8['lambda_theory_1_per_s']:.6g} | {ur8['parameter_stability']['free_tail_over_forced_at_end']:.4%} | {ur8['fits']['full_tail']['normalized_residual_rms']:.2%} | {ur8['prediction']['normalized_residual_rms']:.2%} | {ur8['classification']['class']} |

At 200 s the Ur=8 first-half prediction residual was 18.03%, so the run was extended from the existing 200 s checkpoint to 240 s under the unchanged safety limits. The final JSON records both the 200 s failed attempt and the extended result. The extended 240 s fit still fails the prediction residual gate ({ur8['prediction']['normalized_residual_rms']:.2%} > 15%), so Ur=8 remains an explicit `outside_lockin_model_failed` result; no threshold was relaxed and no blind extension to 400 s was started.

The two points are reported as outside-lock-in only when the shared classifier passes all conditions; the label does not mean a strict raw single-frequency limit cycle.
""", encoding="utf-8")
    (DOCS / "04_long_window_dt_convergence_v7.md").write_text(f"""# v7 dt/dt/2 convergence evidence

The existing same-parameter runs use dt=0.0025 s and dt/2=0.00125 s over the common 5--10 s interval. The screening changes are y RMS {dt['relative_changes']['y_rms_m']:.3%}, half amplitude {dt['relative_changes']['half_amplitude_m']:.3%}, Fy RMS {dt['relative_changes']['fy_rms_N']:.3%}, Cl RMS {dt['relative_changes']['Cl_rms']:.3%}, primary DFT frequency {dt['relative_changes']['primary_frequency_Hz_dft']:.3%}, and mean power {dt['relative_changes']['mean_power_W']:.3%}. These are below the screening limits.

This is **not** the requested long-window scheme-A evidence: both runs start at 0 s, end at 10 s, and the common window contains only {dt['coarse']['cycles_at_fn']:.4f} natural-frequency cycles. The formal v7 long-window gate therefore remains false. A valid closure requires the same late CFD/structure state, identical physical response-cycle boundaries, and at least 3 (preferably 5) full response cycles at both time steps. This report deliberately does not relabel the short-window screen as long-window convergence.
""", encoding="utf-8")
    (DOCS / "04_stage3_acceptance_matrix_v7.md").write_text(f"""# Stage-3 v7 acceptance matrix

| gate | evidence | result |
|---|---|:---:|
| Ur=4 forced/free classification | v7 bounded fit, force/Cl stability, energy, safety | {'PASS' if ur4['classification']['asymptotically_periodic_outside_lockin'] else 'FAIL'} |
| Ur=8 forced/free classification | v7 bounded fit, extension from 200 s checkpoint | {'PASS' if ur8['classification']['asymptotically_periodic_outside_lockin'] else 'FAIL'} |
| Ur=5.2/6/7.1 lock-in response-cycle evidence | v6 point metrics retained and reclassified only by shared results | {'PASS' if metrics['five_point']['lockin_points_pass'] else 'FAIL'} |
| SDOF safety | |y|<1.5D, CFL<0.5, finite | {'PASS' if metrics['five_point']['safety_pass'] else 'FAIL'} |
| dt/dt/2 screening | 0--10 s, 0.9615-cycle scheme-B screen | {'PASS' if dt['screening_pass'] else 'FAIL'} |
| formal long-window dt/dt/2 | same late state, 3--5 response cycles | {'PASS' if dt['formal_long_window_gate'] else 'OPEN'} |
| EB/ANCF common-window online comparison | v6 common measured-cycle boundaries | {'PASS' if metrics['eb_ancf']['physical_acceptance_ready'] else 'FAIL'} |
| Python regression | v7 suite | {'PASS' if metrics['tests']['python_v7']['status'] == 'pass' else 'FAIL'} |
| MATLAB regression | {metrics['tests']['matlab']['passed']}/{metrics['tests']['matlab']['total']}, {matlab_label} | {'PASS' if metrics['tests']['matlab']['passed'] == metrics['tests']['matlab']['total'] else 'FAIL'} |
| multi-slice/full-riser claim | explicitly excluded | PASS |

## Decision

`stage3_fully_passed = {metrics['stage3_fully_passed']}` and `eligible_for_stage4_prototype = {metrics['eligible_for_stage4_prototype']}`. Blocking items: {'; '.join(metrics['blocking_items']) if metrics['blocking_items'] else 'none'}.
""", encoding="utf-8")
    (DOCS / "04_stage3_final_acceptance_report_v7.md").write_text(f"""# Stage-3 final acceptance report v7

## Decision

**Stage 3 is {'FORMALLY PASSED' if metrics['stage3_fully_passed'] else 'CONDITIONALLY PASSED / NOT CLOSED'}.** The v7 science repair closes the Ur=4 interpretation. The Ur=8 extension to 240 s was completed without safety failure but still fails the shared prediction-residual gate, so it remains explicitly unresolved. The project also cannot be declared formally complete while the long-window dt/dt/2 gate is open.

## Quantitative evidence

- Ur=4: class `{ur4['classification']['class']}`, response {ur4['frequency_components']['response_frequency_Hz_dft']:.6f} Hz, f/fn {ur4['frequency_components']['response_f_over_fn']:.4f}, tail free/forced ratio {ur4['parameter_stability']['free_tail_over_forced_at_end']:.3%}, fit residual {ur4['fits']['full_tail']['normalized_residual_rms']:.2%}, prediction residual {ur4['prediction']['normalized_residual_rms']:.2%}.
- Ur=8: class `{ur8['classification']['class']}`, response {ur8['frequency_components']['response_frequency_Hz_dft']:.6f} Hz, f/fn {ur8['frequency_components']['response_f_over_fn']:.4f}, tail free/forced ratio {ur8['parameter_stability']['free_tail_over_forced_at_end']:.3%}, fit residual {ur8['fits']['full_tail']['normalized_residual_rms']:.2%}, prediction residual {ur8['prediction']['normalized_residual_rms']:.2%}.
- Existing dt/dt/2 screen passes its short-window criteria, but it covers only {dt['coarse']['cycles_at_fn']:.4f} cycles; formal long-window convergence is not claimed.
- Python v7 regression: {metrics['tests']['python_v7']['passed']}/{metrics['tests']['python_v7']['tests_run']}; MATLAB: {metrics['tests']['matlab']['passed']}/{metrics['tests']['matlab']['total']} ({matlab_label}).

## Physics and scope

The Ur=4 and Ur=8 results are classified as asymptotically periodic outside lock-in only when the shared force-frequency, RMS, fit, prediction, decay, energy, CFL and finite-value gates pass. They are not used to claim a strict raw single-frequency limit cycle. Ur=5.2/6/7.1 retain the v6 measured-response-cycle lock-in evidence. No physical parameters, damping, safety limits or acceptance thresholds were changed.

The weak-coupling energy defect remains around 1e-6 J while locked-case cycle fluid work is O(1e2) J. There is no evidence in the current evidence set that Aitken is required as a mandatory single-slice gate; the unresolved item is dt/dt/2 long-window evidence. No multi-slice or full-riser validation was started.

## Blocking items

{chr(10).join('- ' + item for item in metrics['blocking_items']) if metrics['blocking_items'] else '- none'}
""", encoding="utf-8")
    (DOCS / "04_stage4_entry_decision_v7.md").write_text(f"""# Stage-4 entry decision v7

Decision: **{'APPROVED' if metrics['eligible_for_stage4_prototype'] else 'NOT APPROVED'}**.

The necessary condition for entry is `stage3_fully_passed=true`; the v7 metric is `{metrics['stage3_fully_passed']}`. The decisive open item is the formal long-window dt/dt/2 comparison from a common late state. Existing short-window screening is retained as useful evidence but is not promoted to formal convergence. Multi-slice, full-riser, curved-riser and machine-learning work remain out of scope until this decision changes.
""", encoding="utf-8")


def main() -> None:
    metrics = build()
    write_docs(metrics)
    print(json.dumps({"status": metrics["status"], "stage3_fully_passed": metrics["stage3_fully_passed"], "eligible_for_stage4_prototype": metrics["eligible_for_stage4_prototype"], "blocking_items": metrics["blocking_items"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
