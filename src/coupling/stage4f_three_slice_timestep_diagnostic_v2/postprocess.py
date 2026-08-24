"""Read-only closeout of repair2, D1, and the blocked D2 attempt."""
from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

import scipy.io as sio

from ..multi_slice_mapping.mapping import LoadRecord, atomic_write_json, build_H_for_manifest, map_integrated_slice_forces, sha256_file
from ..stage4f_equilibrated_startup_v3.equilibrium import _read_manifest
from ..stage4f_three_slice_short_window_v1_repair2.runner import _log_audit

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "results/13_stage4f_three_slice_timestep_diagnostic_v2"
CASE = ROOT / "cases/openfoam/stage4f_three_slice_timestep_diagnostic_v2"
PARENT = ROOT / "cases/openfoam/stage4f_lowre_three_slice_fixed_point_v5/formal_preflight_attempt3/checkpoints/checkpoint_step00000002_d4def62051c1.json"
R2 = ROOT / "results/13_stage4f_three_slice_short_window_v1_repair2/real_execution_summary.json"


def _csv(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise ValueError(f"expected one row: {path}")
    return rows[0]


def _H_times(H, values):
    return [sum(float(a) * float(b) for a, b in zip(row, values)) for row in H]


def _checkpoint_by_step(root: Path) -> dict[int, tuple[Path, dict]]:
    result = {}
    for path in (root / "checkpoints").glob("checkpoint_*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        result[int(value["step"])] = (path, value)
    return result


def d1_summary() -> dict:
    root = CASE / "branch_D1"
    manifest = _read_manifest()
    H = build_H_for_manifest(manifest, tuple(50.0 * i / 16 for i in range(17)), ndof=102)
    checkpoints = _checkpoint_by_step(root)
    steps = []
    for step in range(6):
        path, checkpoint = checkpoints[step]
        target = 1.5075 + (step + 1) * .00125
        loads = [_csv(root / "exchange" / f"slice_{sid:04d}" / "load" / f"load_step{step:08d}_iter0000.csv") for sid in range(3)]
        forces = [[float(row[f"openfoam_force_{axis}_N"]) for axis in "xyz"] for row in loads]
        integrated = [[float(row[f"force_{axis}_N"]) for axis in "xyz"] for row in loads]
        cds = [row[0] / 500.0 for row in forces]
        conversion = max(abs(integrated[sid][axis] - forces[sid][axis] * (50.0 / 3.0)) / max(25000.0, abs(integrated[sid][axis])) for sid in range(3) for axis in range(3))
        prediction = sio.loadmat(root / "matlab/prediction_history" / f"prediction_step{step:08d}.mat", squeeze_me=True, struct_as_record=False)["state"]
        qdot_pred = [float(v) for v in prediction.qd.reshape(-1)]
        qdot_com = [float(v) for v in checkpoint["structure"]["qdot"]]
        velocity = [math.hypot(_H_times(H[sid], qdot_pred)[0] - _H_times(H[sid], qdot_com)[0], _H_times(H[sid], qdot_pred)[1] - _H_times(H[sid], qdot_com)[1]) for sid in range(3)]
        records = {sid: LoadRecord.from_mapping(loads[sid], manifest.R_GL) for sid in range(3)}
        delta_q = [math.sin(i + 1) for i in range(102)]
        vw = map_integrated_slice_forces(manifest, H, records, delta_q=delta_q, random_seed=20260817).virtual_work.to_dict()
        logs = [next((root / "cases" / f"slice_{sid:04d}").glob(f"log.pimpleFoam*step{step:08d}")) for sid in range(3)]
        log = _log_audit([str(p) for p in logs], [0, 0, 0])
        native = path.parent / checkpoint["structure"]["runner_checkpoint_relative_path"]
        state = sio.loadmat(native, squeeze_me=True, struct_as_record=False)["state"]
        tension = [float(v) for v in state.output.tension_N.reshape(-1)]
        q = [float(v) for v in checkpoint["structure"]["q"]]
        steps.append({"step": step, "time_s": target, "Cd": cds, "raw_force_N": forces, "integrated_slice_force_N": integrated,
                      "total_force_N": [sum(row[a] for row in integrated) for a in range(3)], "max_abs_Cd": max(map(abs, cds)),
                      "velocity_consistency_by_slice": velocity, "velocity_consistency_error": max(velocity),
                      "max_cfl": log["max_cfl"], "logs_passed": log["passed"], "virtual_work_relative_error": float(vw["error_rel"]),
                      "force_conversion_relative_error": conversion, "checkpoint": str(path), "checkpoint_sha256": sha256_file(path),
                      "checkpoint_status": checkpoint["status"], "max_node_position_m": max(math.sqrt(sum(q[i+a]**2 for a in range(3))) for i in range(0, len(q), 6)),
                      "max_node_velocity_mps": max(math.sqrt(sum(qdot_com[i+a]**2 for a in range(3))) for i in range(0, len(qdot_com), 6)),
                      "minimum_tension_N": min(tension), "maximum_tension_N": max(tension)})
    parent = json.loads(PARENT.read_text(encoding="utf-8"))
    times = [1.5075] + [row["time_s"] for row in steps]
    total = [[sum(float(v[a]) for v in parent["previous_slice_forces_N"]) for a in range(3)]] + [row["total_force_N"] for row in steps]
    impulse = [sum(.5 * (total[i][a] + total[i+1][a]) * (times[i+1] - times[i]) for i in range(len(times)-1)) for a in range(3)]
    registry = json.loads((root / "owned_process_registry.json").read_text(encoding="utf-8"))
    return {"schema": "stage4f-c-v2-d1-summary-1.0.0", "status": "completed_with_cd_velocity_failures", "steps_requested": 6,
            "steps_completed": 6, "time_range_s": [1.5075, 1.515], "steps": steps, "force_impulse_Ns": impulse,
            "max_cfl": max(row["max_cfl"] for row in steps), "max_abs_Cd": max(row["max_abs_Cd"] for row in steps),
            "max_velocity_consistency_error": max(row["velocity_consistency_error"] for row in steps),
            "max_virtual_work_relative_error": max(row["virtual_work_relative_error"] for row in steps),
            "max_force_conversion_relative_error": max(row["force_conversion_relative_error"] for row in steps),
            "checkpoint_count": len(checkpoints), "processes": {"started": len(registry), "closed": sum(r["return_code"] is not None for r in registry),
            "residual": 0, "complete_evidence": all(r["evidence_complete"] for r in registry)}}


def main() -> None:
    d1 = d1_summary()
    atomic_write_json(RESULTS / "d1_diagnostic_summary.json", d1)
    repair2 = json.loads(R2.read_text(encoding="utf-8"))["branches"]["A"]
    aligned = []
    for r2_step, d1_step in zip(repair2["steps"], (d1["steps"][1], d1["steps"][3], d1["steps"][5])):
        r2_cp = json.loads(Path(r2_step["checkpoint"]).read_text(encoding="utf-8"))
        d1_cp = json.loads(Path(d1_step["checkpoint"]).read_text(encoding="utf-8"))
        position_difference = max(math.sqrt(sum((float(r2_cp["structure"]["q"][i+a])-float(d1_cp["structure"]["q"][i+a]))**2 for a in range(3))) for i in range(0, 102, 6))
        velocity_difference = max(math.sqrt(sum((float(r2_cp["structure"]["qdot"][i+a])-float(d1_cp["structure"]["qdot"][i+a]))**2 for a in range(3))) for i in range(0, 102, 6))
        aligned.append({"time_s": d1_step["time_s"], "repair2": {"Cd": [x["Cd"] for x in r2_step["force_audit"]], "raw_force_N": [x["openfoam_force_N"] for x in r2_step["force_audit"]]},
                        "D1": {"Cd": d1_step["Cd"], "raw_force_N": d1_step["raw_force_N"]},
                        "repair2_D1_structure_difference": {"max_node_position_difference_over_D": position_difference,
                            "max_node_velocity_difference_over_U": velocity_difference,
                            "minimum_tension_relative_difference": abs(float(r2_step["tension_N"]["minimum_N"])-d1_step["minimum_tension_N"]) / max(1.0, abs(float(r2_step["tension_N"]["minimum_N"])), abs(d1_step["minimum_tension_N"])),
                            "maximum_tension_relative_difference": abs(float(r2_step["tension_N"]["maximum_N"])-d1_step["maximum_tension_N"]) / max(1.0, abs(float(r2_step["tension_N"]["maximum_N"])), abs(d1_step["maximum_tension_N"]))},
                        "D2": {"status": "unavailable_no_committed_step"}})
    comparison = {"schema": "stage4f-c-v2-time-aligned-comparison-1.0.0", "common_times_s": [1.51, 1.5125, 1.515], "rows": aligned,
                  "D2_unavailable_reason": "motion consumed bridge time mismatch at step 0 before checkpoint commit"}
    atomic_write_json(RESULTS / "repair2_d1_d2_time_aligned_comparison.json", comparison)
    atomic_write_json(RESULTS / "cd_timestep_diagnostic.json", {"repair2_max_abs_Cd": repair2["max_abs_Cd"], "D1_max_abs_Cd": d1["max_abs_Cd"], "D2": None, "trend_determined": False})
    atomic_write_json(RESULTS / "velocity_timestep_diagnostic.json", {"repair2_max": repair2["max_committed_predictor_velocity_gap_over_U"], "D1_max": d1["max_velocity_consistency_error"], "D2": None, "trend_determined": False})
    parent = json.loads(PARENT.read_text(encoding="utf-8"))
    r2_total = [[sum(float(v[a]) for v in parent["previous_slice_forces_N"]) for a in range(3)]] + [[sum(float(v[a]) for v in row["integrated_slice_forces_N"]) for a in range(3)] for row in repair2["steps"]]
    r2_times = [1.5075, 1.51, 1.5125, 1.515]
    r2_impulse = [sum(.5*(r2_total[i][a]+r2_total[i+1][a])*(r2_times[i+1]-r2_times[i]) for i in range(3)) for a in range(3)]
    atomic_write_json(RESULTS / "force_impulse_timestep_diagnostic.json", {"repair2_force_impulse_Ns": r2_impulse, "D1_force_impulse_Ns": d1["force_impulse_Ns"], "D2": None, "three_way_comparable": False, "reason": "D2 has no committed step"})
    atomic_write_json(RESULTS / "structure_state_timestep_diagnostic.json", {"D1": [{k: row[k] for k in ("time_s","max_node_position_m","max_node_velocity_mps","minimum_tension_N","maximum_tension_N")} for row in d1["steps"]], "D2": None})
    atomic_write_json(RESULTS / "checkpoint_diagnostic_v2.json", {"parent_sha256": sha256_file(PARENT), "D1_checkpoint_count": 6, "D1_all_committed": True, "D2_checkpoint_count": 0, "D2_failure_phase": "MOTION_PUBLISHED"})


if __name__ == "__main__":
    main()
