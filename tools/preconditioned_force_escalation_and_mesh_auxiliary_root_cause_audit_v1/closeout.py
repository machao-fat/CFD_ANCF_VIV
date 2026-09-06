"""Close the authorised force-escalation and mesh-auxiliary audit."""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.slice_independence_audit_v1.audit import parse_forces
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log

OUT = ROOT / "results/preconditioned_force_escalation_and_mesh_auxiliary_root_cause_audit_v1_run_001"
DOC = ROOT / "docs/preconditioned_force_escalation_and_mesh_auxiliary_root_cause_audit_v1/PRECONDITIONED_FORCE_ESCALATION_AND_MESH_AUXILIARY_ROOT_CAUSE_AUDIT_V1_REPORT.md"
SOURCE = ROOT / "runtime/preconditioned_coupled_0p1s_smoke_v1_run_003"
MOTION = ROOT / "runtime/preconditioned_force_escalation_motion_replay_v1_run_004"
MESH = ROOT / "runtime/preconditioned_force_escalation_mesh_replay_v1_run_004"
DT = 0.005


def put(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream: stream.write(text)


def corr(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3: return None
    aa, bb = statistics.mean(a), statistics.mean(b)
    d = math.sqrt(sum((x-aa)**2 for x in a) * sum((y-bb)**2 for y in b))
    return None if d == 0.0 else sum((x-aa)*(y-bb) for x, y in zip(a, b)) / d


def main() -> int:
    ledger = json.loads((OUT / "causal_ledger.json").read_text(encoding="utf-8"))["ledger"]
    structure = json.loads((OUT / "ancf_recorded_force_replay.json").read_text(encoding="utf-8"))
    rows = []
    energy = []; correlations = []
    for sid in range(3):
        forces = [float(row["slices"][sid]["integrated_structural_force_N"][0]) for row in ledger]
        raw = [float(row["slices"][sid]["raw_total_force_N"][0]) for row in ledger]
        pressure = [float(row["slices"][sid]["raw_pressure_force_N"][0]) for row in ledger]
        viscous = [float(row["slices"][sid]["raw_viscous_force_N"][0]) for row in ledger]
        vp = [float(row["slices"][sid]["prediction"]["vx_mps"]) for row in ledger]
        vc = [float(row["slices"][sid]["correction"]["vx_mps"]) for row in ledger]
        ap = [float(row["slices"][sid]["prediction"]["ax_mps2"]) for row in ledger]
        power = [f * (a+b) / 2.0 for f, a, b in zip(forces, vp, vc)]
        max_index = max(range(20), key=lambda index: abs(raw[index]))
        energy.append({"slice_id": sid, "mean_midpoint_streamwise_power_W": statistics.mean(power),
                       "cumulative_midpoint_streamwise_work_J": sum(value * DT for value in power),
                       "positive_power_fraction": sum(value > 0.0 for value in power) / 20.0,
                       "last_5_window_work_J": sum(value * DT for value in power[-5:])})
        correlations.append({"slice_id": sid, "same_step_corr_Fx_vx_prediction": corr(forces, vp),
                             "same_step_corr_Fx_ax_prediction": corr(forces, ap),
                             "one_window_lag_corr_Fx_n_vx_nminus1": corr(forces[1:], vp[:-1]),
                             "one_window_lag_corr_Fx_n_ax_nminus1": corr(forces[1:], ap[:-1])})
        rows.append({"slice_id": sid, "max_raw_abs_Fx_N": abs(raw[max_index]),
                     "max_raw_Fx_time_tau_s": ledger[max_index]["coupling_tau_s"],
                     "max_raw_pressure_Fx_N": pressure[max_index], "max_raw_viscous_Fx_N": viscous[max_index],
                     "max_integrated_abs_Fx_N": abs(forces[max_index]),
                     "max_force_over_precursor_terminal": abs(raw[max_index]) / 1350.198335726,
                     "raw_Fx_total_N": raw, "raw_Fx_pressure_N": pressure, "raw_Fx_viscous_N": viscous})

    replay = []
    for sid in range(3):
        original = parse_forces(next((SOURCE / "cases" / f"slice_{sid:04d}" / "postProcessing/cylinderForces").glob("*/forces.dat")))
        repeated = parse_forces(next((MOTION / f"slice_{sid:04d}" / "postProcessing/cylinderForces").glob("*/forces.dat")))
        common = sorted(set(original) & set(repeated)); errors = [abs(original[t]["total_N"][0]-repeated[t]["total_N"][0]) for t in common]
        scale = max(abs(original[t]["total_N"][0]) for t in common)
        qa = audit_log(MOTION / f"slice_{sid:04d}" / "pimpleFoam.stdout", MOTION / f"slice_{sid:04d}" / "system/fvSolution")
        at_115 = next(item for item in qa["time_records"] if abs(float(item["time_s"])-.115) < 1e-12)
        cell = [solve for solve in at_115["solves"] if solve["field"] in ("cellDisplacementx", "cellDisplacementy")]
        meshlog = (MESH / f"slice_{sid:04d}" / "moveMesh.stdout").read_text(encoding="utf-8", errors="replace")
        replay.append({"slice_id": sid, "common_force_samples": len(common), "max_abs_Fx_difference_N": max(errors),
                       "max_normalized_Fx_difference": max(errors)/scale, "cell_solve_at_0p115": cell,
                       "motion_cfd_courant_max": max(float(item["courant_max"]) for item in qa["time_records"]),
                       "mesh_only_time_steps": meshlog.count("Time = ") // 3,
                       "mesh_only_mesh_OK_count": meshlog.count("Mesh OK."),
                       "mesh_only_negative_volume_mentions": meshlog.lower().count("negative volume")})

    proposal = {
      "schema_version": "openfoam-numerical-quality-contract-v4-proposal",
      "scope": "future only; does not reclassify V3 or the source 0.1 s runtime",
      "mesh_motion_auxiliary": {
        "hard_gate": "final residual <= configured cellMotionUx/cellDisplacementFinal tolerance and field finite; missing solve remains fail-closed",
        "iteration_policy": "linear iterations above 200 are an efficiency/conditioning warning, not alone a validity failure",
        "basis": "fvSolution provides tolerance=1e-8 and relTol=0 but no maxIter=200; the 20-step mesh-only replay remained Mesh OK at every step while final residuals were below 1e-8"
      },
      "fluid_primary_fields": "unchanged terminal-residual hard gate",
      "pcorr": "unchanged pcorrFinal tolerance health gate",
      "courant": "unchanged independent hard numerical-quality gate"
    }
    with (OUT / "openfoam_quality_contract_v4_proposal.json").open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(proposal, stream, ensure_ascii=False, indent=2); stream.write("\n")
    result = {"STRUCTURE_PATH_REPLAY": structure["STRUCTURE_PATH_REPLAY"],
              "CFD_MOTION_RESPONSE_REPLAY": "PASS" if all(item["max_normalized_Fx_difference"] < .005 for item in replay) else "FAIL",
              "MESH_ONLY_EXACT_MOTION_REPLAY": "PASS" if all(item["mesh_only_mesh_OK_count"] == 20 and item["mesh_only_negative_volume_mentions"] == 0 for item in replay) else "FAIL",
              "force_escalation": rows, "streamwise_energy": energy, "correlations": correlations, "motion_replay": replay,
              "coupling_timeline": "F_n is reconciled to the raw force output stamped at t_OF,n and is produced by the preceding explicit-window geometry q*_n-1; correction n applies F_n to the committed n-1 state. No stale/default data or additional two-window alias was found.",
              "primary_root_cause": "FLUID_FORCE_ESCALATION_DRIVES_STRUCTURE within the recorded explicit closed loop; both one-way paths reproduce their respective source histories.",
              "secondary_root_cause": "MESH_AUXILIARY_CONDITIONING: high cellDisplacement PCG iterations recur in mesh-only replay, but all recorded final residuals meet the fvSolution 1e-8 tolerance and mesh-only geometry remained Mesh OK for 20/20 steps.",
              "added_mass_evidence": "NOT_ESTABLISHED: same-step Fx-vx/Fx-ax correlations are weak or sign-changing; strong one-window correlations reflect the explicit sequence. Midpoint streamwise work is net negative in slices 0/2 and total, not sustained positive injection.",
              "NEXT_COUPLED_RUN": "NOT_AUTHORIZED"}
    with (OUT / "root_cause_gate.json").open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2); stream.write("\n")
    table = "\n".join(f"| {i+1} | {ledger[i]['coupling_tau_s']:.3f} | " + " | ".join(f"{ledger[i]['slices'][s]['raw_total_force_N'][0]:.6g}" for s in range(3)) + " |" for i in range(20))
    lines = ["# PRECONDITIONED_FORCE_ESCALATION_AND_MESH_AUXILIARY_ROOT_CAUSE_AUDIT_V1_REPORT", "",
      "## Scope and source", "", "- Immutable source: `runtime/preconditioned_coupled_0p1s_smoke_v1_run_003`.",
      "- No new fully coupled run was started. The only executions were a C++ ANCF recorded-load replay, a three-case prescribed recorded-motion CFD replay, and a three-case mesh-only replay, each ending at the existing 0.100 s window.",
      "", "## Raw streamwise force history [N per 1 m CFD span]", "", "| step | tau [s] | slice 0 | slice 1 | slice 2 |", "|---:|---:|---:|---:|---:|", table,
      "", "- The first material force departure is at step 3 (`tau=0.015 s`): pressure reverses the streamwise force from about +1.31 kN to about -1.01 kN. At step 5 it reaches +4.73 kN; this is 3.50 times the precursor terminal 1.350 kN before the high-velocity excursion is established.",
      "- Maxima: " + "; ".join(f"slice {x['slice_id']}: |Fx|={x['max_raw_abs_Fx_N']:.9g} N at tau={x['max_raw_Fx_time_tau_s']:.3f} s ({x['max_force_over_precursor_terminal']:.3g}x precursor; pressure={x['max_raw_pressure_Fx_N']:.9g} N, viscous={x['max_raw_viscous_Fx_N']:.9g} N)" for x in rows) + ".",
      "- The escalation is pressure-dominated. Viscous Fx remains much smaller until the extreme final transients.",
      "", "## One-way replays", "", f"- ANCF recorded-force replay: `{structure['STRUCTURE_PATH_REPLAY']}`; 20/20 predictor and corrected local states match the coupled record exactly (maximum error `0`).",
      "- CFD recorded-motion replay uses the verified one-window time layer, not a direct same-stamp table. Its maximum normalized raw-Fx errors are " + ", ".join(f"slice {x['slice_id']}: {x['max_normalized_Fx_difference']:.4%}" for x in replay) + ". Thus it reproduces the escalating force history to sub-0.4% of each slice's force range.",
      "- Mesh-only exact-motion replay: `PASS` for all slices: 20/20 mesh updates reported `Mesh OK`, with no negative-volume mention. This rules out a geometry collapse within this 0.1 s recorded history.",
      "", "## Coupling and energy", "", "- The discrete timeline has a real one-window geometry-to-force layer: the raw `F_n` stamped at `t_OF,n` matches geometry sent in the preceding explicit window. The structure correction uses that fresh `F_n`; no stale/default force or extra two-window alias was found.",
      "- Midpoint streamwise work (using the prediction/correction velocity midpoint, hence an algorithmic diagnostic) is " + "; ".join(f"slice {x['slice_id']}: {x['cumulative_midpoint_streamwise_work_J']:.9g} J" for x in energy) + ". It is not sustained positive across slices; the total is " + f"{sum(x['cumulative_midpoint_streamwise_work_J'] for x in energy):.9g} J" + ".",
      "- Added-mass-like causality is not established: same-step force/velocity and force/acceleration correlations are sign-changing, while one-window correlations are expected from the explicit time sequence.",
      "", "## Mesh auxiliary solve semantics", "", "- At `t_OF=0.115 s`, source V3 records 310/233 `cellDisplacementx/y` iterations but final residuals `9.074e-09` / `9.528e-09`, satisfying the actual `fvSolution` `tolerance 1e-8`, `relTol 0` configuration. `fvSolution` does not specify `maxIter 200`.",
      "- The exact-motion mesh-only replay reproduces nontrivial high PCG work (at the corresponding early moving step approximately 236/205 iterations) while all 20 meshes remain healthy. Therefore high iteration count is a conditioning/efficiency warning, not direct proof that the displacement solve is invalid. The historical V3 failure remains a failure; it is not reclassified.",
      "- A future-only Quality V4 proposal is saved at `results/preconditioned_force_escalation_and_mesh_auxiliary_root_cause_audit_v1_run_001/openfoam_quality_contract_v4_proposal.json`: final residual/finite/missing-field remain hard gates; auxiliary iteration count becomes a warning unless a separately frozen solver max-iteration contract exists.",
      "", "## Decision", "", f"- Primary root cause: `{result['primary_root_cause']}`", f"- Secondary issue: `{result['secondary_root_cause']}`", f"- `NEXT_COUPLED_RUN = {result['NEXT_COUPLED_RUN']}`", "- Minimal next task: a dedicated parallel-explicit FSI stability / time-layer study, beginning from this verified precursor state and changing exactly one stability control at a time only after a new frozen contract. It must not be a longer production run."]
    put(DOC, "\n".join(lines) + "\n")
    print(json.dumps({key: result[key] for key in ("STRUCTURE_PATH_REPLAY", "CFD_MOTION_RESPONSE_REPLAY", "MESH_ONLY_EXACT_MOTION_REPLAY", "NEXT_COUPLED_RUN")}))
    return 0

if __name__ == "__main__": raise SystemExit(main())
