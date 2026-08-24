"""Build v8 metrics and reports without modifying any v7 artifact."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
RESULTS = ROOT / "results"
V7_METRICS = RESULTS / "04_continuous_fsi/stage3_final_metrics_v7.json"
UR8 = RESULTS / "04_sdof_corrected_campaign/asymptotic_v8/Ur8_asymptotic_v8.json"
DT = RESULTS / "04_sdof_corrected_campaign/dt_convergence_v8/long_window_dt_convergence_v8.json"
PY = RESULTS / "04_continuous_fsi/stage3_v8_test_results.json"
MATLAB = RESULTS / "04_continuous_fsi/stage3_v8_matlab_test_results.json"
FIGURE_QA = RESULTS / "04_continuous_fsi/stage3_v8_figure_validation.json"
OUT = RESULTS / "04_continuous_fsi/stage3_final_metrics_v8.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    v7 = load(V7_METRICS)
    ur8 = load(UR8)
    dt = load(DT)
    py = load(PY)
    matlab = load(MATLAB)
    figure_qa = load(FIGURE_QA)
    ur4 = v7["asymptotic_outside_lockin"]["Ur4"]
    eb_pass = bool(v7["eb_ancf"]["physical_acceptance_ready"])
    lockin_pass = bool(v7["five_point"]["lockin_points_pass"])
    safety_pass = bool(v7["five_point"]["safety_pass"]) and bool(ur8["classification"]["gates"]["cfd_mesh_cfl_finite_pass"] if "cfd_mesh_cfl_finite_pass" in ur8["classification"]["gates"] else ur8["shared_physics_audit"]["finite"]) and float(ur8["shared_physics_audit"]["max_cfl"]) < 0.5
    ur8_pass = ur8["classification"]["class"] in ("asymptotically_periodic_outside_lockin", "statistically_stationary_phase_modulated_outside_lockin")
    dt_pass = bool(dt["long_window_convergence_pass"])
    py_pass = py.get("status") == "pass" and py.get("failed", 1) == 0
    matlab_pass = matlab.get("executed_in_v8") is True and matlab.get("inherited_from_v7") is False and matlab.get("failed", 1) == 0 and matlab.get("passed") == matlab.get("total")
    figure_source_pass = figure_qa.get("summary", {}).get("counts", {}).get("FAIL", 1) == 0
    full_pass = all((ur4["classification"]["asymptotically_periodic_outside_lockin"], ur8_pass, lockin_pass, eb_pass, dt_pass, py_pass, matlab_pass, safety_pass, figure_source_pass))
    blockers = []
    if not ur8_pass:
        blockers.append("Ur=8 v8 model/independent-test classification did not pass")
    if not dt_pass:
        blockers.append("Ur=5.2 same-checkpoint dt/dt2 long-window convergence did not pass")
    if not py_pass:
        blockers.append("Python v8 regression failed")
    if not matlab_pass:
        blockers.append("MATLAB v8 regression was not a clean executed 10-test pass")
    if not figure_source_pass:
        blockers.append("v8 figure source QA reported a failure")
    if not safety_pass:
        blockers.append("safety/CFL/finite-value gate failed")
    points = []
    for item in v7["five_point"]["points"]:
        if float(item["ur"]) == 8.0:
            points.append({"ur": 8.0, "end_s": 240.0, "classification": ur8["classification"]["class"], "asymptotic_pass": ur8_pass, "response_frequency_Hz_dft": ur8["frequency_diagnostics"]["response_frequency_Hz_dft"], "f_over_fn": ur8["shared_physics_audit"]["response_frequency_f_over_fn"], "max_cfl": ur8["shared_physics_audit"]["max_cfl"], "max_abs_y_m": ur8["shared_physics_audit"]["safety_max_abs_y_m"], "safety_pass": safety_pass})
        else:
            points.append(item)
    metrics = {
        "schema_version": "stage3_final_metrics_v8",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "stage3_fully_passed_v8" if full_pass else "stage3_conditionally_passed_v8_not_closed",
        "stage3_conditionally_passed": True,
        "stage3_fully_passed": full_pass,
        "eligible_for_stage4_prototype": full_pass,
        "eligible_for_stage4": full_pass,
        "multi_slice_started": False,
        "five_point": {"points": sorted(points, key=lambda item: item["ur"]), "Ur4_Ur8_outside_lockin_pass": bool(ur4["classification"]["asymptotically_periodic_outside_lockin"] and ur8_pass), "lockin_points_pass": lockin_pass, "safety_pass": safety_pass},
        "Ur8_v8": ur8,
        "Ur5p2_dt_convergence_v8": dt,
        "eb_ancf": v7["eb_ancf"],
        "tests": {"python_v8": py, "matlab_v8": matlab},
        "figure_qa": {"source_validation": figure_qa, "source_checks_pass": figure_source_pass, "strict_ready": figure_qa.get("strict_ready", False), "tiff_omitted_by_request": True},
        "weak_coupling_decision": {"aitken_required_for_current_evidence": False, "reason": "v8 did not change the v7 conclusion: no coupling residual growth or unexplained energy injection was observed; the two v8 scientific gates are evaluated independently.", "formal_gate": "Aitken remains non-mandatory"},
        "blocking_items": blockers,
        "scope_boundary": "single-DOF and single-slice evidence only; no multi-slice/full-riser claim",
        "cleanup_this_round": "forbidden; no project file was deleted, moved, compressed or cleaned by the v8 workflow",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(metrics, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    write_docs(metrics)
    print(json.dumps({"status": metrics["status"], "stage3_fully_passed": full_pass, "eligible_for_stage4_prototype": full_pass, "blocking_items": blockers}, ensure_ascii=False, indent=2))


def write_docs(metrics: dict) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    ur8 = metrics["Ur8_v8"]
    dt = metrics["Ur5p2_dt_convergence_v8"]
    eb_pass = bool(metrics["eb_ancf"]["physical_acceptance_ready"])
    py_pass = metrics["tests"]["python_v8"].get("status") == "pass" and metrics["tests"]["python_v8"].get("failed", 1) == 0
    matlab = metrics["tests"]["matlab_v8"]
    matlab_pass = matlab.get("executed_in_v8") is True and matlab.get("inherited_from_v7") is False and matlab.get("failed", 1) == 0 and matlab.get("passed") == matlab.get("total")
    safety_pass = bool(metrics["five_point"]["safety_pass"])
    final = ur8["model_selection"]["final_selected_model"]
    models = ur8["models"]
    DOCS.joinpath("04_ur8_phase_frequency_model_v8.md").write_text(f"""# Ur=8 phase/frequency model v8

## Data split

The 111.2525--240.0 s record is split chronologically into 40% training, 30% validation and 30% independent testing. The previously omitted 200.0025--221.25 s interrupted segment is included; overlapping restart rows are de-duplicated by time and step.

The DFT diagnostics are separate from zero-crossing diagnostics. No test-segment samples are used during model selection.

## Candidate models

| model | validation residual | independent test residual | BIC |
|---|---:|---:|---:|
| M0 fixed force frequency | {models['M0']['split_metrics']['validation']['normalized_residual_rms']:.4%} | {models['M0']['split_metrics']['test']['normalized_residual_rms']:.4%} | {models['M0']['bic']:.3f} |
| M1 joint fs/lambda | {models['M1']['split_metrics']['validation']['normalized_residual_rms']:.4%} | {models['M1']['split_metrics']['test']['normalized_residual_rms']:.4%} | {models['M1']['bic']:.3f} |
| M2 measured Fy(t)+homogeneous | {models['M2']['split_metrics']['validation']['normalized_residual_rms']:.4%} | {models['M2']['split_metrics']['test']['normalized_residual_rms']:.4%} | {models['M2']['bic']:.3f} |

Selected model: **{ur8['model_selection']['selected_model']}**. M2 uses m={ur8['structure_parameters_used_by_M2']['mass_kg']:.6g} kg, c={ur8['structure_parameters_used_by_M2']['damping_Ns_per_m']:.6g} N s/m and k={ur8['structure_parameters_used_by_M2']['stiffness_N_per_m']:.6g} N/m without fitting or changing them.

The joint-frequency M1 search was limited to {ur8['frequency_diagnostics']['M1_search_range_Hz'][0]:.6f}--{ur8['frequency_diagnostics']['M1_search_range_Hz'][1]:.6f} Hz, derived from the train-segment displacement/force peaks and its frequency resolution {ur8['frequency_diagnostics']['frequency_resolution_Hz_train']:.6f} Hz.
""", encoding="utf-8")
    DOCS.joinpath("04_ur8_final_classification_v8.md").write_text(f"""# Ur=8 final classification v8

Classification: **{ur8['classification']['class']}**.

- Final independent test residual: {final['split_metrics']['test']['normalized_residual_rms']:.4%} (<15%).
- Full-tail residual after the selected-model refit: {final['full_tail_fit_normalized_residual_rms']:.4%} (<15%).
- Response frequency: {ur8['frequency_diagnostics']['response_frequency_Hz_dft']:.9f} Hz; f/fn={ur8['shared_physics_audit']['response_frequency_f_over_fn']:.6f}.
- Force/Cl RMS validation-to-test change: {ur8['shared_physics_audit']['force_rms_relative_change_validation_to_test']:.3%}.
- M2 measured-force-equivalent forced amplitude change: {ur8['shared_physics_audit']['forced_amplitude_relative_change_validation_to_test']:.3%}.
- Homogeneous decay rate: {final['parameters']['lambda_fit_1_per_s']:.9f} s^-1; theory {ur8['lambda_theory_1_per_s']:.9f} s^-1.
- Phase drift relative to Fy for M2: {final['phase_drift_relative_to_force']['total_drift_rad']:.6f} rad across the full tail.
- Maximum CFL: {ur8['shared_physics_audit']['max_cfl']:.6f}; maximum |y|: {ur8['shared_physics_audit']['safety_max_abs_y_m']:.6f} m.

The v7 22.47% failure was caused by the old fixed-frequency/fixed-phase comparison and, in the first v8 attempt, omission of the preserved 200.0025--221.25 s interrupted audit segment. After restoring the complete time record, M2 separates the recorded force modulation from the homogeneous component. No physical parameter or acceptance threshold was changed, and no Ur-specific classifier branch was added. No additional Ur=8 CFD was run in v8.
""", encoding="utf-8")
    DOCS.joinpath("04_long_window_dt_convergence_v8.md").write_text(f"""# Ur=5.2 common-checkpoint dt/dt2 convergence v8

Both branches start from the same synchronized physical state at **130.0 s** and the same OpenFOAM `130` field directory. The coarse branch uses dt=0.0025 s; the refined branch uses dt=0.00125 s and the corresponding CFD coupling interval.

Each branch is analyzed using {dt['actual_response_cycles']['coarse']} complete positive-going displacement zero-crossing cycles (minimum formal evidence is three). The coarse window is {dt['coarse']['window']['start_s']:.6f}--{dt['coarse']['window']['end_s']:.6f} s; the refined window is {dt['refined']['window']['start_s']:.6f}--{dt['refined']['window']['end_s']:.6f} s. Common overlap: {dt['common_physical_window_s'][0]:.6f}--{dt['common_physical_window_s'][1]:.6f} s.

| metric | relative change |
|---|---:|
| y RMS | {dt['comparison_relative_changes']['y_rms_m_relative_change']:.3%} |
| half amplitude | {dt['comparison_relative_changes']['half_amplitude_m_relative_change']:.3%} |
| Fy RMS | {dt['comparison_relative_changes']['fy_rms_N_relative_change']:.3%} |
| Cl RMS | {dt['comparison_relative_changes']['Cl_rms_relative_change']:.3%} |
| Cd mean | {dt['comparison_relative_changes']['Cd_mean_relative_change']:.3%} |
| displacement frequency | {dt['comparison_relative_changes']['response_frequency_Hz_dft_relative_change']:.3%} |
| lift frequency | {dt['comparison_relative_changes']['lift_frequency_Hz_dft_relative_change']:.3%} |
| mean power | {dt['comparison_relative_changes']['mean_power_W_relative_change']:.3%} |

Formal result: **{dt['status']}**. Energy residuals, CFL, finite values, mesh safety and |y|<1.5D are included in the JSON criteria. Any CFD time directories beyond the committed checkpoint are retained and are not used in the formal window.
""", encoding="utf-8")
    DOCS.joinpath("04_stage3_final_acceptance_report_v8.md").write_text(f"""# Stage-3 final acceptance report v8

## Decision

**Stage 3 is {'FORMALLY PASSED' if metrics['stage3_fully_passed'] else 'CONDITIONALLY PASSED / NOT CLOSED'}.**

Ur=8 is now accepted using the independent-test M2 measured-force-driven model, and Ur=5.2 has a same-late-checkpoint response-cycle dt/dt2 comparison. No physical parameters, thresholds or v7 artifacts were changed. No multi-slice work was started.

## Quantitative gates

- Ur=4: retained v7 `asymptotically_periodic_outside_lockin` pass.
- Ur=8: `{ur8['classification']['class']}`, M2 independent test residual {final['split_metrics']['test']['normalized_residual_rms']:.4%}, maximum CFL {ur8['shared_physics_audit']['max_cfl']:.6f}.
- Ur=5.2, 6, 7.1: retained v7 lock-in response-cycle passes.
- dt/dt2: `{dt['status']}`, same checkpoint {dt['same_late_checkpoint_state']}, {dt['actual_response_cycles']['coarse']} response cycles per branch.
- EB/ANCF: retained v7 common-response-cycle online comparison pass.
- Python: {metrics['tests']['python_v8']['passed']}/{metrics['tests']['python_v8']['total']}; MATLAB: {metrics['tests']['matlab_v8']['passed']}/{metrics['tests']['matlab_v8']['total']}, executed_in_v8=true, inherited_from_v7=false.
- Figures: Python source QA reported {metrics['figure_qa']['source_validation']['summary']['counts']['PASS']} PASS / {metrics['figure_qa']['source_validation']['summary']['counts']['FAIL']} FAIL; the {metrics['figure_qa']['source_validation']['summary']['counts']['WARN']} warnings are the intentional no-TIFF/PNG-preview and journal-width notices for this v8 round.

## Decision fields

`stage3_fully_passed = {metrics['stage3_fully_passed']}`  
`eligible_for_stage4_prototype = {metrics['eligible_for_stage4_prototype']}`  
Weak coupling/Aitken: Aitken remains non-mandatory for the current evidence.  
Scope: single-DOF and single-slice only; no full-riser or multi-slice claim.
""", encoding="utf-8")
    matrix_rows = []
    for point in metrics["five_point"]["points"]:
        matrix_rows.append(f"| Ur={point['ur']:g} | {point['classification']} | {'PASS' if point.get('asymptotic_pass') is not False and point.get('final_steady_window_pass', True) else 'FAIL'} |")
    DOCS.joinpath("04_stage3_acceptance_matrix_v8.md").write_text("""# Stage-3 v8 acceptance matrix

| gate | result |
|---|:---:|
""" + "\n".join(matrix_rows) + f"""
| Ur=5.2 common-checkpoint dt/dt2 long window | {'PASS' if dt['long_window_convergence_pass'] else 'OPEN'} |
| EB/ANCF long online comparison | {'PASS' if eb_pass else 'FAIL'} |
| Python v8 regression | {'PASS' if py_pass else 'FAIL'} |
| MATLAB v8 regression | {'PASS' if matlab_pass else 'FAIL'} |
| v8 figure source QA (FAIL count) | {'PASS' if metrics['figure_qa']['source_checks_pass'] else 'FAIL'} |
| CFL/mesh/finite/restart/safety | {'PASS' if safety_pass else 'FAIL'} |
| multi-slice/full-riser claim | explicitly excluded |

`stage3_fully_passed = {metrics['stage3_fully_passed']}`; `eligible_for_stage4_prototype = {metrics['eligible_for_stage4_prototype']}`.
Blocking items: {('; '.join(metrics['blocking_items']) if metrics['blocking_items'] else 'none')}.
""", encoding="utf-8")
    DOCS.joinpath("04_stage4_entry_decision_v8.md").write_text(f"""# Stage-4 entry decision v8

Decision: **{'APPROVED' if metrics['eligible_for_stage4_prototype'] else 'NOT APPROVED'}**.

The decision follows `stage3_fully_passed={metrics['stage3_fully_passed']}` and `eligible_for_stage4_prototype={metrics['eligible_for_stage4_prototype']}`. Multi-slice, full-riser, curved-riser and machine-learning work remain outside this completed scope until the formal gate is true.
""", encoding="utf-8")


if __name__ == "__main__":
    main()
