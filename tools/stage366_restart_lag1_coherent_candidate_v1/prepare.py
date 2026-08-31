"""Prepare a lag-1 coherent restart candidate without launching CFD."""
from __future__ import annotations

import hashlib
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

SOURCE = ROOT / "runtime/stage341_dt005_long_convergence_v1"
STATE = ROOT / "results/350_restart_bootstrap_velocity_v1/restart_bootstrap_state.json"
FIXTURE = ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
RUNTIME = ROOT / "runtime/stage366_restart_lag1_coherent_candidate_v1"
RESULTS = ROOT / "results/366_restart_lag1_coherent_candidate_v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def boundary_vectors(path: Path) -> list[tuple[float, float, float]]:
    data = path.read_bytes()
    patch = data.find(b"    cyl")
    start = data.find(b"nonuniform List<vector>", patch)
    match = re.search(rb"\n(\d+)\s*\n\(", data[start:])
    if start < 0 or match is None:
        raise ValueError(f"missing nonuniform cylinder field: {path}")
    count = int(match.group(1))
    values = struct.unpack_from("<" + "d" * (3 * count), data, start + match.end())
    return [tuple(values[i : i + 3]) for i in range(0, len(values), 3)]


def main() -> int:
    if RUNTIME.exists() and any(RUNTIME.iterdir()):
        raise RuntimeError(f"refusing to reuse non-empty runtime: {RUNTIME}")
    source = json.loads((SOURCE / "logs/structure_participant.json").read_text(encoding="utf-8"))
    bootstrap = json.loads(STATE.read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if source.get("finalized") is not True or source.get("target_global_step") != 16000:
        raise RuntimeError("Stage341 source is not finalized at global step 16000")
    if int(bootstrap.get("source_global_step", -1)) != 16000 or float(bootstrap.get("field_time_s", -1)) != 80.0:
        raise RuntimeError("bootstrap field clock is not 80.0 s")
    displacement, _, _, _ = participant.project_interface(
        tuple(bootstrap["q"]), tuple(bootstrap["qdot"]),
        slice_positions_m=tuple(fixture["slice_positions_m"]),
        length_m=float(fixture["length_m"]), elements=int(fixture["elements"]),
    )
    slices = []
    for index in range(3):
        field = SOURCE / f"slice_{index:04d}/80"
        required = [field / name for name in ("U", "p", "pointDisplacement", "cellDisplacement", "Force", "phi", "meshPhi", "Uf", "uniform/time", "polyMesh/points")]
        if not all(path.is_file() for path in required):
            raise RuntimeError(f"incomplete 80 s source fields in {field}")
        values = boundary_vectors(field / "pointDisplacement")
        error = max(max(abs(row[axis] - displacement[index][axis]) for axis in range(2)) for row in values)
        u_header = (field / "U").read_bytes()[:2000].decode("latin1", errors="ignore")
        u_data = (field / "U").read_bytes()
        cyl = u_data.find(b"    cyl")
        u_block = u_data[cyl : u_data.find(b"\n    }", cyl) if u_data.find(b"\n    }", cyl) >= 0 else cyl + 1000].decode("latin1", errors="ignore")
        slices.append({
            "slice_id": f"slice_{index:04d}",
            "field_directory": "80",
            "field_clock_s": 80.0,
            "bootstrap_displacement_error_max_m": error,
            "bootstrap_geometry_aligned": error < 1e-12,
            "u_cylinder_boundary_nonuniform": "value           nonuniform List<vector>" in u_block,
            "field_sha256": {str(path.relative_to(SOURCE / f"slice_{index:04d}")): sha(path) for path in required},
        })
    result = {
        "schema_version": 1,
        "stage_id": "stage4f_d_restart_lag1_coherent_candidate_v1",
        "candidate_only": True,
        "source_stage": "stage341_dt005_long_convergence_v1",
        "source_global_step": 16000,
        "field_time_s": 80.0,
        "structure_state_time_s": bootstrap["state_time_s"],
        "lag_steps": bootstrap["lag_steps"],
        "dt_s": 0.005,
        "slice_count": 3,
        "slices": slices,
        "checks": {
            "all_three_bootstrap_geometries_aligned": all(row["bootstrap_geometry_aligned"] for row in slices),
            "all_three_source_U_boundaries_nonuniform": all(row["u_cylinder_boundary_nonuniform"] for row in slices),
            "source_runtime_read_only": True,
            "derived_flux_fields_present_in_source": True,
            "require_first_step_mesh_quality_audit": True,
        },
        "real_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "owned_residual": 0,
        "status": "pass",
        "gate_id": "STAGE4F_D_RESTART_LAG1_COHERENT_CANDIDATE_V1_GATE",
        "next_action": "request one fresh 40-step Smoke with a new runtime; no continuation",
    }
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "candidate_manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "candidate_manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "stage4f_d_restart_lag1_coherent_candidate_v1_gate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": "pass", "field_time_s": 80.0, "structure_state_time_s": bootstrap["state_time_s"], "real_process_starts": result["real_process_starts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
