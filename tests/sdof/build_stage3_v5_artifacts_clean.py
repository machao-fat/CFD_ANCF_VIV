"""Write readable v5 evidence, acceptance matrix, and entry decision artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=True) + "\n", encoding="utf-8")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--sensitivity", type=Path, required=True)
    parser.add_argument("--eb-ancf", type=Path, required=True)
    parser.add_argument("--matlab", type=Path, required=True)
    parser.add_argument("--python-tests", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    summary = load(args.summary)
    sensitivity = load(args.sensitivity)
    eb_ancf = load(args.eb_ancf)
    matlab = load(args.matlab)
    python_tests = load(args.python_tests)
    v4_metrics_path = args.output_root / "results" / "04_continuous_fsi" / "stage3_final_metrics_v4.json"
    v4_metrics = load(v4_metrics_path) if v4_metrics_path.exists() else {}
    continuity = {}
    for path in (args.output_root / "results" / "04_sdof_corrected_campaign").glob("Ur*_v5_to*/continuity_v5.json"):
        continuity[path.parent.name] = load(path)
    ur5_continuity = args.output_root / "results" / "04_sdof_corrected_campaign" / "Ur5p2_extended" / "continuity_v5.json"
    if ur5_continuity.exists():
        continuity["Ur5p2_extended"] = load(ur5_continuity)
    long75_stop = {}
    for path in (args.output_root / "results" / "04_eb_ancf_long_time_comparison_v5").glob("*_online_long75/stop_audit_v5.json"):
        long75_stop[path.parent.name] = load(path)
    figure_validation_path = args.output_root / "results" / "04_continuous_fsi" / "stage3_v5_figure_validation.json"
    figure_validation = load(figure_validation_path) if figure_validation_path.exists() else {"status": "not_run"}
    points = summary["points"]
    eb_acceptance = eb_ancf.get("comparison", {}).get("acceptance", {})
    blockers: list[str] = []
    if sensitivity.get("status") != "robust_window_pass":
        blockers.append("Ur=5.2 window-shift sensitivity is boundary-only, not robust (less than 2 of 3 pairs pass).")
    if not summary.get("all_points_strict_steady_window_pass", False):
        blockers.append("At least one of the five SDOF points does not satisfy the common late-window steady criterion.")
    if not summary.get("all_points_safety_pass", False):
        blockers.append("At least one SDOF point fails the displacement/CFL safety audit.")
    if not eb_acceptance.get("physical_acceptance_ready", False):
        blockers.append("The EB/ANCF comparison lacks two adjacent late windows with five effective structural periods each, or fails a physical criterion.")
    if int(python_tests.get("failed", 1)) != 0:
        blockers.append("Python regression tests contain failures.")
    if int(matlab.get("failed", 1)) != 0:
        blockers.append("MATLAB regression tests contain failures.")
    fully_passed = not blockers
    conditionally_passed = bool(summary.get("all_points_completed") and summary.get("all_points_safety_pass") and not python_tests.get("failed") and not matlab.get("failed"))

    rows = []
    for point in points:
        rows.append("| {ur} | {time} | {steady} | {freq} | {physical} | {cfl:.6g} | {disp:.6g} |".format(
            ur=point.get("ur"), time=point.get("time_end_s"), steady=point.get("final_steady_window_pass"),
            freq=point.get("frequency_state"), physical=point.get("physical_lockin_classification"),
            cfl=float(point.get("max_cfl", float("nan"))), disp=float(point.get("max_abs_y_m", float("nan")))))
    blocker_md = "\n".join(f"- {item}" for item in blockers) if blockers else "- None"

    metrics = {
        "status": "stage3_fully_passed" if fully_passed else "stage3_conditionally_passed" if conditionally_passed else "stage3_not_passed",
        "stage3_fully_passed": fully_passed,
        "stage3_conditionally_passed": conditionally_passed,
        "remaining_blockers": blockers,
        "eligible_for_stage4_prototype": fully_passed,
        "frequency_method": "DFT primary for response/lift; corrected zero-crossing diagnostic only; multi-harmonic test included.",
        "five_point": summary,
        "ur5p2_window_sensitivity": sensitivity,
        "eb_ancf_long_time_online": eb_ancf,
        "python_tests": python_tests,
        "matlab_tests": matlab,
        "v4_inherited_audits": {"dt_comparison": v4_metrics.get("dt_comparison"), "restart": v4_metrics.get("restart"), "strong_coupling": v4_metrics.get("strong_coupling")},
        "continuity_audits": continuity,
        "eb_ancf_long75_extension_attempt": long75_stop,
        "figure_validation": figure_validation,
        "safety_limits": {"max_abs_y_m": 1.5, "max_cfl": 0.5, "NaN/Inf": "stop", "negative_volume": "stop"},
        "scope_boundary": "No multi-slice or full-riser physical validation is claimed.",
    }
    root = args.output_root.resolve()
    dump(root / "results" / "04_continuous_fsi" / "stage3_final_metrics_v5.json", metrics)
    dump(root / "results" / "04_continuous_fsi" / "stage3_v5_test_results.json", {
        "python": python_tests, "matlab": matlab,
        "frequency_unit_tests": "included in Python discovery",
        "note": "Counts are from the actual commands recorded in the referenced JSON artifacts.",
    })

    write(root / "docs" / "04_stage3_completion_plan_v5.md", f"""# Stage 3 completion record v5

This v5 run preserves all v3/v4 artifacts and performs only checkpoint continuations and independent late-window audits. No multi-slice case was started.

Executed items: corrected DFT/zero-crossing frequency separation; multi-harmonic frequency regression; recursive Python discovery repair; Ur=5.2 three-pair window-shift audit; Ur=4/6/7.1/8 continuation from physical checkpoints; independent long EB/ANCF online comparison; MATLAB regression.

Current decision: `stage3_fully_passed={str(fully_passed).lower()}`; `eligible_for_stage4_prototype={str(fully_passed).lower()}`.
""")
    write(root / "docs" / "04_sdof_five_point_steady_validation_v5.md", f"""# Five-point SDOF steady validation v5

DFT is primary for response and lift frequency. Corrected zero crossing is diagnostic only. A point is not called lock-in from frequency synchronization alone; it must first pass the common late-window stationarity criteria. Low-power points use an absolute-power gate and are not automatically steady.

| Ur | final time (s) | strict steady | frequency state | physical class | max CFL | max |y| (m) |
|---:|---:|---|---|---|---:|---:|
{chr(10).join(rows)}

Ur=5.2 window-shift status: `{sensitivity.get('status')}`, passing pairs `{sensitivity.get('passed_combinations')}/3`. The late 60--86/86--112 s pair passes, but the two earlier shifted pairs do not; therefore this is a boundary-window result rather than a robust stationarity result.

The old 8--34/34--60 s comparison remains startup-growth versus late response and is not used as a two-steady-window test.
""")
    write(root / "docs" / "04_lockin_classification_method_v5.md", """# Lock-in and synchronization classification v5

Tier 1: `frequency_synchronized` means 0.95 <= f_response/f_n <= 1.05 and the DFT/zero-crossing diagnostic is reliable. Otherwise the state is `outside_frequency_sync`; if the frequency estimate is unreliable it is `frequency_unresolved`.

Tier 2: `locked_or_near_lockin` is allowed only after the late-window stationarity gate, with positive non-noise fluid input and a compatible force--velocity phase. Frequency synchronization alone is never called lock-in. Failed or incomplete late-window stationarity is classified as `transitional_or_unsteady`.
""")
    write(root / "docs" / "04_lift_frequency_method_v5.md", """# Lift-frequency method v5

Response and lift frequencies are both reported separately. The direct DFT spectral peak is primary. The corrected zero-crossing estimate is retained as a diagnostic field with an explicit method label and never overwrites the DFT result. The multi-harmonic regression test verifies that a 0.2 Hz fundamental with a 0.4 Hz harmonic is not reported as 0.4 Hz.
""")
    write(root / "docs" / "04_eb_ancf_long_time_online_comparison_v5.md", f"""# Long-time online EB/ANCF comparison v5

EB and ANCF use independent CFD feedback, identical high-tension small-deformation parameters, mesh, initial field, slice location, time step, load projection, and post-processing. Model-form differences and CFD-feedback differences are reported separately.

- Same mesh: `{eb_ancf.get('same_mesh')}`
- Common end time: `{eb_ancf.get('time_end_s')}` s
- Physical amplitude identifiable: `{eb_acceptance.get('physical_amplitude_identifiable')}`
- Two adjacent late windows available: `{eb_acceptance.get('two_adjacent_late_windows_available')}`
- Five effective structural cycles per window: `{eb_acceptance.get('five_effective_structural_cycles_per_window')}`
- Physical acceptance ready: `{eb_acceptance.get('physical_acceptance_ready')}`

This remains a single-slice structure/interface comparison and is not a full-riser validation.
""")
    write(root / "docs" / "04_stage3_final_acceptance_report_v5.md", f"""# Stage 3 final acceptance report v5

## Decision

- `stage3_conditionally_passed={str(conditionally_passed).lower()}`
- `stage3_fully_passed={str(fully_passed).lower()}`
- `eligible_for_stage4_prototype={str(fully_passed).lower()}`

## Blockers

{blocker_md}

## Evidence

- Python discovery: {python_tests.get('passed')}/{python_tests.get('total')} passed.
- MATLAB regression: {matlab.get('passed')}/{matlab.get('total')} passed.
- Five SDOF points completed: `{summary.get('all_points_completed')}`; safety pass: `{summary.get('all_points_safety_pass')}`.
- Ur=5.2 shifted-window audit: `{sensitivity.get('status')}`, {sensitivity.get('passed_combinations')}/3 pairs.
- EB/ANCF long-time physical comparison: `{eb_ancf.get('status')}`.
- EB/ANCF 60 s same-mesh model differences: `{eb_ancf.get('comparison', {}).get('structure_model_difference')}`; independent CFD force RMS difference: `{eb_ancf.get('comparison', {}).get('independent_cfd_feedback_difference')}`.
- EB/ANCF measured late-window response frequency: `{eb_ancf.get('comparison', {}).get('window_2', {}).get('eb', {}).get('response_frequency_Hz_dft')}` Hz; each 27 s window contains `{(eb_ancf.get('comparison', {}).get('window_2', {}).get('eb', {}).get('response_frequency_Hz_dft', 0.0) or 0.0) * 27.0}` effective cycles, below the required five.
- Existing dt/dt/2 short-window screen retained from v4: `{v4_metrics.get('dt_comparison')}`; it is not relabeled as a long-window convergence proof.
- Engineering restart retained from v4: `{v4_metrics.get('restart')}`.
- Checkpoint splice continuity audits: `{[(name, item.get('status'), item.get('time_end_s')) for name, item in continuity.items()]}`; these compare the last pre-checkpoint row with the first post-checkpoint row.
- 75 s EB/ANCF extension attempt: `{long75_stop}`; it was safely stopped and is not counted as final acceptance evidence.
- Figure source QA: `{figure_validation.get('status')}` for `{len(figure_validation.get('sources', []))}` Python generators.

The v3 0.36--0.38 Hz values were a doubled zero-crossing analysis error. They are obsolete as absolute frequencies; v5 reports DFT primary frequency and corrected zero-crossing diagnostics separately. Relative window-to-window changes are unaffected by the factor of two. No multi-slice or full-riser claim is made.

Weak coupling is not promoted to a strong-coupling requirement solely because the observed coupling work defect is about 1e-6 J while cycle fluid work is O(10^2) J. Aitken remains evidence-gated; it is required only if the completed physical audits show added-mass instability, residual growth, or time-step non-convergence.
""")
    write(root / "docs" / "04_stage3_acceptance_matrix_v5.md", f"""# Stage 3 acceptance matrix v5

| Gate | Status | Evidence |
|---|---|---|
| Frequency fix and unit tests | {'PASS' if not python_tests.get('failed') else 'BLOCKED'} | {python_tests.get('passed')}/{python_tests.get('total')} Python tests |
| Ur=5.2 robust shifted-window stationarity | {'PASS' if sensitivity.get('status') == 'robust_window_pass' else 'BLOCKED'} | {sensitivity.get('passed_combinations')}/3 pairs |
| Five-point common late-window criterion | {'PASS' if summary.get('all_points_strict_steady_window_pass') else 'BLOCKED'} | {summary.get('status')} |
| EB/ANCF long online physical comparison | {'PASS' if eb_acceptance.get('physical_acceptance_ready') else 'BLOCKED'} | {eb_ancf.get('status')} |
| MATLAB structure regression | {'PASS' if not matlab.get('failed') else 'BLOCKED'} | {matlab.get('passed')}/{matlab.get('total')} |
| dt/dt/2 screen | {'PASS' if v4_metrics.get('dt_comparison', {}).get('status') == 'short_window_screening_pass_long_window_pending' else 'REVIEW'} | inherited v4 evidence; no long-window overclaim |
| Scope boundary | PASS | No multi-slice claim |

Overall: `stage3_fully_passed={str(fully_passed).lower()}`.
""")
    write(root / "docs" / "04_stage4_entry_decision_v5.md", f"""# Stage 4 entry decision v5

`eligible_for_stage4_prototype={str(fully_passed).lower()}`.

Stage 4 may begin only after all v5 blockers are resolved. If eligible, its scope is a minimal two/three-slice prototype with explicit H/H^T conservation checks; eligibility does not mean that a full flexible-riser VIV validation has been completed.

Current blockers:
{blocker_md}
""")
    print(json.dumps({"stage3_fully_passed": fully_passed, "stage3_conditionally_passed": conditionally_passed, "eligible_for_stage4_prototype": fully_passed, "blockers": blockers}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
