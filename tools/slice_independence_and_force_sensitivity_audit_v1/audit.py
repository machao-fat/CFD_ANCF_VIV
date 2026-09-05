#!/usr/bin/env python3
"""Read-only A-G evidence audit for the 20 s three-slice sanity runtime."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.slice_independence_audit_v1.audit import (exact_file_equality, finite_force_differences, force_object_status, force_samples, motion_path_status, precice_binding, sha256, synthetic_channel_probe, xml_pair)

RUNTIME = ROOT / "runtime" / "three_slice_physical_sanity_20s_v1_run_001"
RESULTS = ROOT / "results" / "slice_independence_and_force_sensitivity_audit_v1"
CONTROLLED_GATE = ROOT / "results" / "slice_force_sensitivity_controlled_v6" / "controlled_sensitivity_gate.json"
SAMPLES = (0.005, 0.5, 1.0, 5.0, 10.0, 15.0, 20.0)


def main() -> int:
    if not RUNTIME.is_dir():
        raise RuntimeError(f"missing immutable runtime: {RUNTIME}")
    cases = [RUNTIME / "cases" / f"slice_{sid:04d}" for sid in range(3)]
    force_paths = [case / "postProcessing" / "cylinderForces" / "0" / "forces.dat" for case in cases]
    if not all(path.is_file() for path in force_paths):
        raise RuntimeError("raw forces.dat evidence is incomplete")
    bindings = [precice_binding(case / "system" / "preciceDict") for case in cases]
    pairs = [xml_pair(case / "precice-config.xml") for case in cases]
    fields: dict[str, object] = {}
    for time_s in ("5", "10", "20"):
        u_paths = [case / time_s / "U" for case in cases]
        p_paths = [case / time_s / "p" for case in cases]
        if not all(path.is_file() for path in (*u_paths, *p_paths)):
            raise RuntimeError(f"missing p/U evidence at {time_s} s")
        fields[time_s] = {"U_sha256": [sha256(path) for path in u_paths], "p_sha256": [sha256(path) for path in p_paths],
                          "U_byte_identical": exact_file_equality(u_paths), "p_byte_identical": exact_file_equality(p_paths)}
    geometry = []
    for sid, case in enumerate(cases):
        binding = bindings[sid]
        point = case / "20" / "pointDisplacement"; mesh_points = case / "20" / "polyMesh" / "points"
        geometry.append({"slice_id": sid, "persisted_constant_points_sha256": sha256(case / "constant" / "polyMesh" / "points"),
                         "cellDisplacement_sha256": sha256(case / "20" / "cellDisplacement"),
                         "motion_path": motion_path_status(binding, case / "constant" / "dynamicMeshDict", point, mesh_points)})
    controlled = json.loads(CONTROLLED_GATE.read_text(encoding="utf-8")) if CONTROLLED_GATE.is_file() else {"CONTROLLED_PRESCRIBED_MOTION_SENSITIVITY": "NOT_COMPLETED"}
    output = {
        "audit_id": "SLICE_INDEPENDENCE_AND_FORCE_SENSITIVITY_AUDIT_V1",
        "source_runtime": str(RUNTIME), "source_runtime_mode": "read_only",
        "cross_slice_identity": [{"slice_id": sid, "case_path": str(case), "participant": bindings[sid]["participant"],
            "structure_participant": pairs[sid]["socket_structure"], "fluid_participant": pairs[sid]["socket_fluid"], "mesh": bindings[sid]["mesh"],
            "read_data": bindings[sid]["read_data"], "write_data": bindings[sid]["write_data"], "force_path": str(force_paths[sid]),
            "motion_input": str(case / "system" / "preciceDict"), "solver_log": str(RUNTIME / "logs" / f"fluid_{sid:04d}.stdout")}
            for sid, case in enumerate(cases)],
        "raw_force": {"paths": [str(path) for path in force_paths], "sha256": [sha256(path) for path in force_paths],
                      "byte_identical": exact_file_equality(force_paths), "row_count": [sum(1 for line in path.read_text().splitlines() if line and not line.startswith("#")) for path in force_paths],
                      "max_inter_slice_Fy_difference_N": finite_force_differences(force_paths), "samples": force_samples(force_paths, SAMPLES)},
        "field_file_evidence": fields,
        "motion_geometry_evidence": geometry,
        "forces_function_object": [force_object_status(case / "system" / "controlDict") for case in cases],
        "precice_pairing": pairs, "synthetic_channel_probe": synthetic_channel_probe(pairs),
        "root_cause": "MOVING_MESH_NOT_APPLIED_BUG: launcher configured namePointDisplacement unused while dynamicFvMesh uses displacementLaplacian; distinct cellDisplacement values were not projected to the pointDisplacement field required to move mesh points.",
        "controlled_prescribed_motion_sensitivity": controlled,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "slice_independence_audit.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"root_cause": output["root_cause"], "results": str(RESULTS)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
