"""Offline audit for the OpenFOAM field-clock/lag-1 structure restart pair."""
from __future__ import annotations

import importlib.util
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "runtime/284_precice_single_slice_smoke_real_v1/python_deps"))
PARTICIPANT = ROOT / "tools/stage305_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"
spec = importlib.util.spec_from_file_location("participant", PARTICIPANT)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load interface projection")
participant = importlib.util.module_from_spec(spec)
spec.loader.exec_module(participant)

SOURCE_RUNTIME = ROOT / "runtime/stage341_dt005_long_convergence_v1"
SOURCE_STATE = SOURCE_RUNTIME / "logs/structure_participant.json"
BOOTSTRAP = ROOT / "results/350_restart_bootstrap_velocity_v1/restart_bootstrap_state.json"
FIXTURE = ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
RESULTS = ROOT / "results/365_restart_bootstrap_field_alignment_v1"


def read_boundary_vectors(path: Path) -> list[tuple[float, float, float]]:
    data = path.read_bytes()
    patch = data.find(b"    cyl")
    list_start = data.find(b"nonuniform List<vector>", patch)
    match = re.search(rb"\n(\d+)\s*\n\(", data[list_start:])
    if list_start < 0 or match is None:
        raise ValueError(f"missing cylinder boundary list: {path}")
    count = int(match.group(1))
    start = list_start + match.end()
    values = struct.unpack_from("<" + "d" * (3 * count), data, start)
    return [tuple(values[index : index + 3]) for index in range(0, len(values), 3)]


def max_error(actual: list[tuple[float, float, float]], expected: tuple[float, float]) -> float:
    return max(max(abs(row[axis] - expected[axis]) for axis in range(2)) for row in actual)


def main() -> int:
    source = json.loads(SOURCE_STATE.read_text(encoding="utf-8"))
    bootstrap = json.loads(BOOTSTRAP.read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if source.get("finalized") is not True or source.get("target_global_step") != 16000:
        raise RuntimeError("Stage341 source is not finalized at step 16000")
    disp, _, _, _ = participant.project_interface(
        tuple(bootstrap["q"]), tuple(bootstrap["qdot"]),
        slice_positions_m=tuple(fixture["slice_positions_m"]),
        length_m=float(fixture["length_m"]), elements=int(fixture["elements"]),
    )
    rows = []
    for index in range(3):
        field = SOURCE_RUNTIME / f"slice_{index:04d}/80/pointDisplacement"
        values = read_boundary_vectors(field)
        err = max_error(values, disp[index])
        rows.append({
            "slice_id": f"slice_{index:04d}",
            "field_directory": "80",
            "field_clock_s": 80.0,
            "field_geometry_state": "79.995 s lag-1 bootstrap",
            "projected_bootstrap_displacement_xy_m": list(disp[index]),
            "boundary_vector_count": len(values),
            "boundary_displacement_error_max_m": err,
            "aligned": err < 1e-12,
        })
    final_disp, _, _, _ = participant.project_interface(
        tuple(source["final_q"]), tuple(source["final_qdot"]),
        slice_positions_m=tuple(fixture["slice_positions_m"]),
        length_m=float(fixture["length_m"]), elements=int(fixture["elements"]),
    )
    result = {
        "schema_version": 1,
        "stage_id": "stage4f_d_restart_bootstrap_field_alignment_v1",
        "offline_only": True,
        "source_global_step": 16000,
        "field_clock_s": 80.0,
        "bootstrap_state_time_s": bootstrap["state_time_s"],
        "bootstrap_lag_steps": bootstrap["lag_steps"],
        "slices": rows,
        "comparison": {
            "bootstrap_matches_field_geometry": all(row["aligned"] for row in rows),
            "final_state_matches_field_geometry": False,
            "final_state_displacement_difference_from_field_m": [
                max(abs(final_disp[index][axis] - disp[index][axis]) for axis in range(2)) for index in range(3)
            ],
        },
        "repair_decision": "use_lag1_bootstrap_state_with_80_field_clock_for_next_smoke",
        "real_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "owned_residual": 0,
        "gate_id": "STAGE4F_D_RESTART_BOOTSTRAP_FIELD_ALIGNMENT_V1_GATE",
        "status": "pass" if all(row["aligned"] for row in rows) else "do_not_pass",
        "next_action": "request a new explicit 40-step Smoke; no continuation",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "bootstrap_field_alignment.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "stage4f_d_restart_bootstrap_field_alignment_v1_gate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": result["status"], "decision": result["repair_decision"], "real_process_starts": result["real_process_starts"]}, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
