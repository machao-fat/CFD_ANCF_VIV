"""Read-only hard-gate audit of the sole real rollback fixture runtime."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = "precice_rollback_fixture_configuration_fix_and_qualification_v1_run_001"
RUNTIME, RESULTS = ROOT / "runtime" / RUN, ROOT / "results" / RUN
CONFIG = ROOT / "results" / "precice_rollback_fixture_configuration_fix_and_qualification_v1_config_validation_001" / "config_validation.json"
OFF_ON = ROOT / "results" / "precice_rollback_fixture_configuration_fix_and_qualification_v1_off_on_003_reanalysis" / "off_on_regression_reanalysis.json"


def force_total() -> list[float]:
    path = RUNTIME / "case" / "postProcessing" / "cylinderForces" / "0.1" / "forces.dat"
    line = [row for row in path.read_text(encoding="utf-8").splitlines() if row and not row.startswith("#")][-1]
    values = [float(value) for value in re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", line)]
    # Time, pressure xyz, viscous xyz, then moments: force totals only.
    return [values[1 + axis] + values[4 + axis] for axis in range(3)]


def main() -> int:
    raw = json.loads((RESULTS / "real_rollback_raw.json").read_text(encoding="utf-8"))
    trace = {event["event"]: event for event in raw["adapter_trace"]}
    checkpoint, restored, final = (trace.get(name) for name in ("CHECKPOINT_WRITE", "POST_ROLLBACK_BEFORE_NEXT_INPUT", "FINAL_COMMIT"))
    required = ("U", "p", "phi", "Uf", "pointDisplacement", "cellDisplacement", "mesh_points", "old_points")
    restored_identity = {name: checkpoint["states"][name].get("canonical_hash_fnv1a64") == restored["states"][name].get("canonical_hash_fnv1a64") for name in required}
    old_time_identity = {name: checkpoint["states"][name].get("old_time_levels") == restored["states"][name].get("old_time_levels") for name in ("U", "p", "phi", "Uf", "pointDisplacement", "cellDisplacement")}
    mesh_phi = {
        "checkpoint": checkpoint["states"]["meshPhi"]["classification"],
        "restored": restored["states"]["meshPhi"]["classification"],
        "identity": checkpoint["states"]["meshPhi"] == restored["states"]["meshPhi"],
    }
    points = {
        "checkpoint_centroid_xyz": checkpoint["states"]["mesh_points"]["centroid_xyz"],
        "trial1_centroid_xyz": trace["PRE_ROLLBACK_TRIAL"]["states"]["mesh_points"]["centroid_xyz"],
        "restored_centroid_xyz": restored["states"]["mesh_points"]["centroid_xyz"],
        "trial2_centroid_xyz": final["states"]["mesh_points"]["centroid_xyz"],
        "mesh_hash_identity": restored_identity["mesh_points"],
        "old_points_hash_identity": restored_identity["old_points"],
    }
    participant = raw["participant"]
    trial_inputs = [row["trial_displacement_y_m"] for row in participant["rows"] if row["event"] == "TRIAL_ADVANCED"]
    input_applied = points["trial1_centroid_xyz"] != points["checkpoint_centroid_xyz"] or points["trial2_centroid_xyz"] != points["checkpoint_centroid_xyz"]
    result = {
        "fixture_configuration": json.loads(CONFIG.read_text(encoding="utf-8")),
        "non_intrusive_regression": json.loads(OFF_ON.read_text(encoding="utf-8")),
        "callback_events": [item["event"] for item in raw["adapter_trace"]],
        "real_callbacks_observed": all(name in trace for name in ("CHECKPOINT_WRITE", "PRE_ROLLBACK_TRIAL", "POST_ROLLBACK_BEFORE_NEXT_INPUT", "FINAL_COMMIT")),
        "field_current_value_identity": restored_identity,
        "old_time_level_identity": old_time_identity,
        "meshPhi": mesh_phi,
        "mesh": points,
        "time_identity": {"checkpoint": [checkpoint["physical_time"], checkpoint["time_index"]], "restored": [restored["physical_time"], restored["time_index"]], "pass": checkpoint["physical_time"] == restored["physical_time"] and checkpoint["time_index"] == restored["time_index"]},
        "participant": participant,
        "trial_displacements_y_m": trial_inputs,
        "trial_input_applied_to_actual_mesh": input_applied,
        "final_openfoam_time_s": final["physical_time"],
        "final_raw_force_N": force_total(),
        "ADAPTER_ROLLBACK_QUALIFICATION": "FAIL",
        "first_blocker": "FIELD_ROLLBACK_IDENTITY_FAILURE: meshPhi is absent at CHECKPOINT_WRITE but persistent after restore; U and Uf oldTime-level counts do not return to checkpoint identity.",
        "secondary_qualification_gap": "The supplied +/-0.002 m trial displacements did not alter pointDisplacement or mesh points in this single-window adapter execution; distinct-input geometry contamination and same-input deterministic retry are therefore not established.",
    }
    (RESULTS / "rollback_qualification_audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ADAPTER_ROLLBACK_QUALIFICATION": result["ADAPTER_ROLLBACK_QUALIFICATION"], "first_blocker": result["first_blocker"], "final_raw_force_N": result["final_raw_force_N"]}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
