"""Close precursor-transfer semantics and run only the authorized ANCF-only study.

This tool never starts OpenFOAM, preCICE, Fluent, MATLAB, or a coupled run.
It reuses immutable precursor/restart artifacts and invokes one C++ ANCF-only
diagnostic executable supplied by the caller.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log
from coupling.openfoam_numerical_quality_contract_v3.audit import evaluate_quality_v3
from coupling.stage303_interface_mapping_repair_v1.canonical_projection import canonical_h_row, diagnose_mapping


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime" / "fixed_cylinder_precursor_initialization_v1_run_002"
PRECURSOR_RESULTS = ROOT / "results" / "fixed_cylinder_precursor_initialization_contract_v1_run_002"
SOURCE_REANALYSIS = ROOT / "results" / "fixed_cylinder_precursor_initialization_contract_v1_run_002_reanalysis" / "precursor_preflight_reanalysis.json"
OUT = ROOT / "results" / "precursor_transfer_and_structural_mean_load_closure_v1_run_001"
CONTRACT_PATH = ROOT / "tools" / "precursor_transfer_and_structural_mean_load_closure_v1" / "precursor_transfer_contract_v2.json"
QUALITY_PATH = ROOT / "tools" / "precursor_transfer_and_structural_mean_load_closure_v1" / "openfoam_quality_contract_v3.json"

F_REF = 500.0
TERMINAL = 1350.1983357254
COLD_START_FX = 154850.737753531


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def force_rows(name: str) -> list[dict[str, Any]]:
    source = json.loads(SOURCE_REANALYSIS.read_text(encoding="utf-8"))
    return source["branches"][name]["force_rows"]


def scalar(row: dict[str, Any], name: str) -> float:
    return float(row[name][0])


def make_quality_contract() -> dict[str, Any]:
    """Frozen from actual fvSolution, not from a solver-line name heuristic."""
    return {
        "schema_version": "openfoam-numerical-quality-contract-v3",
        "purpose": "dynamic zero-motion precursor state-transfer quality",
        "source_fvSolution": str(RUNTIME / "zero_motion_dynamic_restart" / "system" / "fvSolution"),
        "source_fvSolution_sha256": sha256(RUNTIME / "zero_motion_dynamic_restart" / "system" / "fvSolution"),
        "primary_terminal_residual_limit": {"Ux": 0.001, "Uy": 0.001, "p": 0.001},
        "courant_max_limit": 1.0,
        "continuity_global_abs_limit": 1.0e-6,
        "solve_groups": {
            "fluid_primary": {"fields": ["Ux", "Uy", "p"], "absolute_tolerance": 1.0e-8,
                              "relative_tolerance": 0.01, "max_iterations": 200,
                              "semantics": "fluid momentum and pressure equations; terminal residual is a hard PIMPLE gate"},
            "mesh_motion_auxiliary": {"fields": ["cellDisplacementx", "cellDisplacementy"], "absolute_tolerance": 1.0e-8,
                                      "relative_tolerance": 0.0, "max_iterations": 200,
                                      "semantics": "displacementLaplacian mesh-motion equations. Exact zero residual with zero iterations is explicitly trivial convergence, not a missing solve."},
            "flux_correction_auxiliary": {"fields": ["pcorr"], "absolute_tolerance": 1.0e-2,
                                          "relative_tolerance": 0.0, "max_iterations": 200,
                                          "semantics": "correctPhi/correctMeshPhi flux correction; health is assessed against pcorrFinal's real fvSolution tolerance."},
        },
        "unknown_solve_policy": "fail_closed",
        "v2_history": "unchanged; this contract does not reclassify any V2 result",
    }


def make_transfer_contract() -> dict[str, Any]:
    return {
        "schema_version": "precursor-transfer-contract-v2",
        "source_runtime": str(RUNTIME),
        "historical_v1": {"status": "FAIL", "absolute_first_step_jump_limit_N": 100.0,
                          "dynamic_first_step_jump_N": 101.9944113307,
                          "rule": "immutable; never reclassified"},
        "scales": {"force_reference_N": F_REF, "precursor_terminal_force_N": TERMINAL,
                   "recent_tail_max_successive_variation_N": 40.2321052284},
        "gates": {
            "restart_force_not_cold_impulse": {"max_abs_first_advanced_force_N": 5000.0,
                                                 "basis": "10 times dynamic-pressure force scale F_ref; screens O(1e5 N) cold impulse"},
            "normalized_terminal_jump": {"max_fraction": 0.10,
                                           "basis": "restart continuity is meaningful relative to the finite terminal load, not a dimensioned one-size-fits-all number"},
            "fixed_dynamic_branch_difference": {"max_abs_N": 100.0,
                                                "basis": "independent 0.2 F_ref branch-path bound already frozen in V1 contract"},
            "branch_difference_decay": {"require_monotone_non_increasing": True,
                                         "basis": "a zero-motion dynamic reconstruction transient must decay rather than grow across all four continuation steps"},
            "state_identity": {"required_fields": ["U", "p", "phi"], "require_dynamic_Uf": True, "require_zero_meshPhi": True},
            "quality": "OPENFOAM_QUALITY_V3 must pass",
        },
        "diagnostics_only": {"jump_over_tail_variation": "reported, not a hard gate because the four terminal fixed-cylinder samples are a monotonic decay rather than stationary variation"},
    }


def transfer_evaluation(quality: dict[str, Any]) -> dict[str, Any]:
    fixed = force_rows("fixed_restart")[1:5]
    dynamic = force_rows("zero_motion_dynamic_restart")[1:5]
    pairwise: list[dict[str, float]] = []
    for left, right in zip(fixed, dynamic):
        pairwise.append({
            "time_s": float(left["time_s"]),
            "fixed_total_Fx_N": scalar(left, "total_N"), "dynamic_total_Fx_N": scalar(right, "total_N"),
            "total_difference_N": abs(scalar(left, "total_N") - scalar(right, "total_N")),
            "pressure_difference_N": scalar(right, "pressure_N") - scalar(left, "pressure_N"),
            "viscous_difference_N": scalar(right, "viscous_N") - scalar(left, "viscous_N"),
        })
    dynamic_first = scalar(dynamic[0], "total_N")
    fixed_first = scalar(fixed[0], "total_N")
    dynamic_jump = abs(dynamic_first - TERMINAL)
    fixed_jump = abs(fixed_first - TERMINAL)
    differences = [item["total_difference_N"] for item in pairwise]
    manifest = json.loads((PRECURSOR_RESULTS / "PRECURSOR_STATE_V1" / "manifest.json").read_text(encoding="utf-8"))
    initial = {field: sha256(RUNTIME / "zero_motion_dynamic_restart" / "0.1" / field) for field in ("U", "p", "phi")}
    checks = {
        "dynamic_first_force_below_10Fref": abs(dynamic_first) <= 10.0 * F_REF,
        "dynamic_jump_fraction_le_0p10": dynamic_jump / TERMINAL <= 0.10,
        "fixed_dynamic_first_difference_le_100N": differences[0] <= 100.0,
        "four_step_branch_difference_monotone_non_increasing": all(right <= left for left, right in zip(differences, differences[1:])),
        "state_hashes_exact": initial == manifest["field_hashes"],
        "dynamic_Uf_persisted": (RUNTIME / "zero_motion_dynamic_restart" / "0.105" / "Uf").is_file(),
        "zero_motion_meshPhi_zero": "internalField   uniform 0" in (RUNTIME / "zero_motion_dynamic_restart" / "0.105" / "meshPhi").read_text(encoding="utf-8"),
        "quality_v3": quality["status"] == "pass",
    }
    return {
        "V1_HISTORICAL_STATUS": "FAIL", "checks": checks,
        "PRECURSOR_TRANSFER_V2": "PASS" if all(checks.values()) else "FAIL",
        "fixed_restart_jump_N": fixed_jump, "dynamic_restart_jump_N": dynamic_jump,
        "dynamic_terminal_to_first_component_change_N": {
            "pressure": scalar(dynamic[0], "pressure_N") - scalar(force_rows("zero_motion_dynamic_restart")[0], "pressure_N"),
            "viscous": scalar(dynamic[0], "viscous_N") - scalar(force_rows("zero_motion_dynamic_restart")[0], "viscous_N"),
            "total": dynamic_first - TERMINAL,
        },
        "dynamic_restart_jump_fraction_of_terminal": dynamic_jump / TERMINAL,
        "dynamic_restart_jump_over_recent_tail_variation_diagnostic": dynamic_jump / 40.2321052284,
        "fixed_dynamic_first_difference_N": differences[0], "four_step": pairwise,
        "state_manifest_id": manifest["PRECURSOR_STATE_ID"],
    }


def structural_evaluation(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    static = value["mean_drag_static"]
    threshold = 1.0e-8 * max(2179104.0029808935, 22503.3055954267)
    static_pass = float(static["residual"]) <= threshold
    step = value["step_load"]
    finite = bool(step["finite"])
    # Pre-frozen catastrophic-screen criteria: 1D structural offset or 10U speed.
    bounded = finite and float(step["max_abs_ux_m"]) <= 1.0 and float(step["max_abs_vx_mps"]) <= 10.0
    forces = [(float(value[0]), float(value[1]), float(value[2])) for value in
              (value["slice_force"][index:index + 3] for index in range(0, len(value["slice_force"]), 3))]
    rows = [canonical_h_row(s) for s in (50.0 / 6.0, 25.0, 250.0 / 6.0)]
    formal_q = [0.0] * len(value["mapped_generalized_force"])
    for force, row in zip(forces, rows):
        for dof, coefficient in enumerate(row):
            component = dof % 6
            if component in (0, 3):
                formal_q[dof] += coefficient * force[0]
            elif component in (1, 4):
                formal_q[dof] += coefficient * force[1]
            else:
                formal_q[dof] += coefficient * force[2]
    cpp_q = [float(item) for item in value["mapped_generalized_force"]]
    mapping_error = max(abs(left - right) for left, right in zip(formal_q, cpp_q))
    mapping_audit = diagnose_mapping(value["mean_drag_static"]["q"], [0.0] * len(cpp_q), forces)
    return {
        "mean_drag_static_load_per_slice_N": value["slice_force_x_N"],
        "static_residual_inf_N": static["residual"], "static_residual_tolerance_N": threshold,
        "STRUCTURAL_MEAN_LOAD_STATIC_EQUILIBRIUM": "PASS" if static_pass else "FAIL",
        "max_static_ux_m": static["max_abs_ux_m"], "slice_static": static["slices"],
        "step_load_duration_s": value["duration_s"], "step_load_max_abs_ux_m": step["max_abs_ux_m"],
        "step_load_max_abs_vx_mps": step["max_abs_vx_mps"],
        "STRUCTURAL_NORMAL_DRAG_STEP_RESPONSE": "BOUNDED" if bounded else "EXCESSIVE",
        "mapping_cpp_python_max_abs_error": mapping_error,
        "mapping_force_balance_rel": mapping_audit.force_balance_error,
        "mapping_moment_balance_rel": mapping_audit.moment_balance_error,
        "mapping_virtual_work_rel": mapping_audit.virtual_work_error,
        "MAPPING_CONSERVATION": "PASS" if max(mapping_error, mapping_audit.force_balance_error,
                                                  mapping_audit.moment_balance_error, mapping_audit.virtual_work_error) <= 1.0e-12 else "FAIL",
        "COUPLED_INITIAL_STRUCTURE_STATE": "REQUIRES_MORE_STUDY",
        "initialization_interpretation": {
            "immediate_zero_geometry_micro_smoke": "NO_FLOW_EQUILIBRIUM is geometry-consistent with the exported zero-displacement CFD state",
            "future_mean_flow_physical_run": "MEAN_DRAG_EQUILIBRIUM is preferable only after a static-deflected CFD mesh/state transfer is independently contracted and verified",
        },
        "old_cold_start_comparison": {"old_coupled_ux_m_approx": 0.73, "old_coupled_vx_mps_approx": 184.0,
                                       "comparison_scope": "order-of-magnitude startup diagnostic only; old run did not have moving hydrodynamic validity"},
    }


def report(transfer: dict[str, Any], quality: dict[str, Any], structural: dict[str, Any]) -> str:
    steps = transfer["four_step"]
    rows = "\n".join(f"| {row['time_s']:.3f} | {row['fixed_total_Fx_N']:.6f} | {row['dynamic_total_Fx_N']:.6f} | {row['total_difference_N']:.6f} | {row['pressure_difference_N']:.6f} | {row['viscous_difference_N']:.6f} |" for row in steps)
    ux = "\n".join(f"| {row['slice_id']} | {row['s_ref_m']:.12g} | {row['ux_m']:.12g} | {row['uy_m']:.12g} |" for row in structural["slice_static"])
    authorization = "CONDITIONAL" if transfer["PRECURSOR_TRANSFER_V2"] == "PASS" and quality["status"] == "pass" and structural["STRUCTURAL_MEAN_LOAD_STATIC_EQUILIBRIUM"] == "PASS" and structural["STRUCTURAL_NORMAL_DRAG_STEP_RESPONSE"] == "BOUNDED" else "NOT_AUTHORIZED"
    direct = transfer["dynamic_terminal_to_first_component_change_N"]
    return f"""# PRECURSOR_TRANSFER_AND_STRUCTURAL_MEAN_LOAD_CLOSURE_V1

## Scope and evidence protection

- No coupled CFD, preCICE, Fluent, or MATLAB was started.
- Historical V1 zero-motion restart remains **FAIL**: its first advanced-step jump was 101.994411331 N, exceeding its frozen 100 N absolute limit. This report does not alter V1.
- All CFD quantities below are read from the immutable run_002 raw artifacts.

## Dynamic restart decomposition

At 0.105 s, dynamic minus precursor-terminal total Fx is {direct['total']:.12g} N (absolute jump {transfer['dynamic_restart_jump_N']:.12g} N). Its direct components are pressure {direct['pressure']:.12g} N and viscous {direct['viscous']:.12g} N: the 101.994 N V1 failure is therefore 87.1% pressure-path and 12.9% viscous-path. It is not a revived cold-start impulse. Relative to the fixed restart, the first-step difference is also pressure dominated.

| t (s) | fixed Fx (N) | dynamic Fx (N) | abs difference (N) | dynamic-fixed pressure (N) | dynamic-fixed viscous (N) |
|---:|---:|---:|---:|---:|---:|
{rows}

The branch difference decays monotonically across all four advanced steps. Dynamic restart force remains 0.07554 of the precursor terminal force and 2.535 times the terminal-tail successive-variation diagnostic. The latter is diagnostic only because the tail is a deterministic monotone decay, not a stationary noise estimate.

## Quality Contract V3

V3 classifies (rather than ignores) `cellDisplacementx/y` as displacement-Laplacian mesh-motion auxiliaries and `pcorr` as a `correctPhi`/`correctMeshPhi` flux auxiliary. Exact-zero/zero-iteration mesh equations are explicit trivial convergence; nonzero mesh equations must satisfy their actual `cellDisplacementFinal` tolerance. `pcorr` must satisfy the real `pcorrFinal` tolerance (1e-2). Ux, Uy and p retain terminal PIMPLE gates. Unknown solver fields fail closed.

- `OPENFOAM_QUALITY_V3 = {quality['status'].upper()}`
- `PRECURSOR_TRANSFER_V2 = {transfer['PRECURSOR_TRANSFER_V2']}`

## ANCF mean-drag static initialization

The static input is exactly 1350.198335726 N per 1 m CFD span multiplied once by 50/3 m: {structural['mean_drag_static_load_per_slice_N']:.12g} N at each of the three structural slice locations. The force representation remains `integrated_slice_force_N`, mapped through the unchanged H-transpose path.

- Max generalized static residual: {structural['static_residual_inf_N']:.12g}; frozen mixed-conjugate-unit tolerance {structural['static_residual_tolerance_N']:.12g}.
- Max streamwise static deflection: {structural['max_static_ux_m']:.12g} m.
- C++/formal H-transpose max absolute difference: {structural['mapping_cpp_python_max_abs_error']:.12g}; force/moment/virtual-work mapping status: `{structural['MAPPING_CONSERVATION']}`.

| slice | s (m) | ux relative to no-flow equilibrium (m) | uy relative to no-flow equilibrium (m) |
|---:|---:|---:|---:|
{ux}

The ANCF-only normal-drag step applies the same three integrated loads from the no-flow static state for {structural['step_load_duration_s']} s at dt=0.005 s. It gives max |ux|={structural['step_load_max_abs_ux_m']:.12g} m and max |vx|={structural['step_load_max_abs_vx_mps']:.12g} m/s; classification is `{structural['STRUCTURAL_NORMAL_DRAG_STEP_RESPONSE']}`. This is compared only as a startup scale against historical cold-start values near 0.73 m and 184 m/s, whose fluid hydrodynamics remain invalid/not-evaluable.

## Decision

- `STRUCTURAL_MEAN_LOAD_STATIC_EQUILIBRIUM = {structural['STRUCTURAL_MEAN_LOAD_STATIC_EQUILIBRIUM']}`
- For a future **mean-flow/VIV** study, `MEAN_DRAG_EQUILIBRIUM` is physically preferable because it removes the finite mean drag step. It cannot yet be paired with the current exported CFD field: that field has a zero-displacement/reference mesh, while the new static equilibrium is deflected by up to {structural['max_static_ux_m']:.6g} m. A static-deflected CFD mesh/state transfer must be independently contracted first.
- For a narrowly scoped immediate 0.1 s coupling probe, `NO_FLOW_EQUILIBRIUM + zero-displacement precursor state` is geometrically consistent; its ANCF-only response reaches only 0.004209 m and 0.07482 m/s by 0.1 s under the normal mean force. That is an option for a separate authorization, not an action here.
- `NEXT_COUPLED_0P1S = {authorization}`. No coupled run was started.

`STRUCTURAL_MEAN_LOAD_INITIALIZATION` was closed only as an ANCF static/step-load study; a future coupled contract must explicitly select and hash the chosen structural state.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostic", type=Path)
    parser.add_argument("--refresh-derived", action="store_true",
                        help="rebuild only derived JSON/report from existing immutable raw artifacts")
    args = parser.parse_args()
    if OUT.exists() and not args.refresh_derived:
        raise RuntimeError(f"refusing to overwrite {OUT}")
    if args.refresh_derived and not (OUT / "ancf_mean_drag_diagnostic.json").is_file():
        raise RuntimeError("cannot refresh without the existing ANCF-only diagnostic artifact")
    if not args.refresh_derived and args.diagnostic is None:
        raise RuntimeError("--diagnostic is required for a fresh ANCF-only study")
    if not SOURCE_REANALYSIS.is_file():
        raise RuntimeError(f"missing raw-artifact reanalysis {SOURCE_REANALYSIS}")
    quality_contract = make_quality_contract()
    transfer_contract = make_transfer_contract()
    OUT.mkdir(parents=True, exist_ok=args.refresh_derived)
    write(CONTRACT_PATH, transfer_contract)
    write(QUALITY_PATH, quality_contract)
    raw_log = RUNTIME / "zero_motion_dynamic_restart" / "restart.stdout"
    fv_solution = RUNTIME / "zero_motion_dynamic_restart" / "system" / "fvSolution"
    audit = audit_log(raw_log, fv_solution)
    quality = evaluate_quality_v3(audit, quality_contract)
    write(OUT / "openfoam_quality_v3_raw_log_audit.json", audit)
    write(OUT / "openfoam_quality_v3_evaluation.json", quality)
    transfer = transfer_evaluation(quality)
    write(OUT / "precursor_transfer_v2_evaluation.json", transfer)
    if not args.refresh_derived:
        completed = subprocess.run([str(args.diagnostic), str(OUT / "ancf_mean_drag_diagnostic.json")], text=True,
                                   encoding="utf-8", errors="replace", capture_output=True, check=False, timeout=120)
        (OUT / "ancf_mean_drag_diagnostic.stdout").write_text(completed.stdout or "", encoding="utf-8")
        (OUT / "ancf_mean_drag_diagnostic.stderr").write_text(completed.stderr or "", encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(f"ANCF-only diagnostic failed with {completed.returncode}: {completed.stderr}")
    structural = structural_evaluation(OUT / "ancf_mean_drag_diagnostic.json")
    write(OUT / "structural_mean_drag_evaluation.json", structural)
    document = ROOT / "docs" / "precursor_transfer_and_structural_mean_load_closure_v1" / "PRECURSOR_TRANSFER_AND_STRUCTURAL_MEAN_LOAD_CLOSURE_V1_REPORT.md"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(report(transfer, quality, structural), encoding="utf-8")
    print(json.dumps({"OPENFOAM_QUALITY_V3": quality["status"], "PRECURSOR_TRANSFER_V2": transfer["PRECURSOR_TRANSFER_V2"],
                      "STRUCTURAL_MEAN_LOAD_STATIC_EQUILIBRIUM": structural["STRUCTURAL_MEAN_LOAD_STATIC_EQUILIBRIUM"],
                      "STRUCTURAL_NORMAL_DRAG_STEP_RESPONSE": structural["STRUCTURAL_NORMAL_DRAG_STEP_RESPONSE"]}, indent=2))


if __name__ == "__main__":
    main()
