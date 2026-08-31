"""Build an offline, coherent restart manifest from the completed 80 s state.

The candidate contains no CFD fields and cannot be used to launch a run by
itself.  It records the exact source field/state pairing and validates that
all three slices share the same mesh and clock.  A later real Smoke requires a
new explicit authorization and a separate runtime.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUNTIME = ROOT / "runtime/stage341_dt005_long_convergence_v1"
SOURCE_STATE = SOURCE_RUNTIME / "logs/structure_participant.json"
BOOTSTRAP = ROOT / "results/350_restart_bootstrap_velocity_v1/restart_bootstrap_state.json"
RUNTIME = ROOT / "runtime/stage363_restart_coherent_candidate_v1"
RESULTS = ROOT / "results/363_restart_coherent_candidate_v1"
SOURCE_STEP = 16000
SOURCE_TIME = 80.0
DT = 0.005


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def time_value(path: Path) -> float:
    text = path.read_text(encoding="latin1")
    match = re.search(r"^value\s+([-+0-9.eE]+);", text, flags=re.MULTILINE)
    if not match:
        raise ValueError(f"missing OpenFOAM time value: {path}")
    return float(match.group(1))


def list_count(path: Path) -> int:
    data = path.read_bytes()
    match = re.search(rb"\n(\d+)\s*\n\(", data)
    if not match:
        raise ValueError(f"missing OpenFOAM list count: {path}")
    return int(match.group(1))


def main() -> int:
    if RUNTIME.exists() and any(RUNTIME.iterdir()):
        raise RuntimeError(f"refusing to reuse non-empty runtime: {RUNTIME}")
    source = json.loads(SOURCE_STATE.read_text(encoding="utf-8"))
    bootstrap = json.loads(BOOTSTRAP.read_text(encoding="utf-8"))
    if source.get("finalized") is not True or source.get("target_global_step") != SOURCE_STEP:
        raise RuntimeError("source structure state is not finalized at step 16000")
    if abs(float(source.get("target_time_s", -1.0)) - SOURCE_TIME) > 1e-12:
        raise RuntimeError("source structure state is not finalized at 80 s")
    if int(bootstrap.get("source_global_step", -1)) != SOURCE_STEP or abs(float(bootstrap.get("field_time_s", -1.0)) - SOURCE_TIME) > 1e-12:
        raise RuntimeError("bootstrap state is not the completed 80 s state")
    slices = []
    for index in range(3):
        root = SOURCE_RUNTIME / f"slice_{index:04d}"
        field = root / "80"
        required = [field / name for name in ("U", "p", "pointDisplacement", "cellDisplacement", "Force", "polyMesh/points", "uniform/time")]
        if not all(path.is_file() for path in required):
            raise RuntimeError(f"incomplete 80 s source fields in {root}")
        value = time_value(field / "uniform/time")
        if abs(value - SOURCE_TIME) > 1e-8:
            raise RuntimeError(f"slice {index} time mismatch: {value}")
        slices.append({
            "slice_id": f"slice_{index:04d}",
            "field_directory": "80",
            "field_time_s": value,
            "field_counts": {name: list_count(field / name) for name in ("U", "p", "pointDisplacement", "cellDisplacement")},
            "field_sha256": {str(path.relative_to(root)): sha(path) for path in required},
        })
    if len({item["field_counts"]["U"] for item in slices}) != 1 or len({item["field_counts"]["pointDisplacement"] for item in slices}) != 1:
        raise RuntimeError("three slices do not share mesh field sizes")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "stage_id": "stage4f_d_restart_coherent_candidate_v1",
        "candidate_only": True,
        "source_stage": "stage341_dt005_long_convergence_v1",
        "source_runtime_read_only": True,
        "source_global_step": SOURCE_STEP,
        "source_time_s": SOURCE_TIME,
        "target_step_if_smoked": SOURCE_STEP + 40,
        "target_time_s_if_smoked": SOURCE_TIME + 40 * DT,
        "dt_s": DT,
        "slice_count": 3,
        "structure_state_sha256": sha(SOURCE_STATE),
        "bootstrap_state_sha256": sha(BOOTSTRAP),
        "bootstrap_state": {
            "q_sha256": bootstrap.get("q_sha256"),
            "qdot_sha256": bootstrap.get("qdot_sha256"),
            "qddot_sha256": bootstrap.get("qddot_sha256"),
            "state_time_s": bootstrap.get("state_time_s"),
            "lag_steps": bootstrap.get("lag_steps"),
        },
        "slices": slices,
        "repair_contract": {
            "copy_source_field_80_without_reserializing": True,
            "preserve_polyMesh_points_with_field_80": True,
            "preserve_U_cylinder_boundary_from_source": True,
            "do_not_synthesize_derived_flux": True,
            "require_first_step_mesh_quality_audit": True,
            "fail_closed_on_min_edge_collapse_or_courant_spike": True,
        },
        "real_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "owned_residual": 0,
        "status": "pass",
        "gate_id": "STAGE4F_D_RESTART_COHERENT_CANDIDATE_V1_GATE",
        "next_action": "request one new 40-step Smoke using a launcher that preserves the 80 s source fields; no continuation",
    }
    (RUNTIME / "candidate_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "candidate_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "stage4f_d_restart_coherent_candidate_v1_gate.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": "pass", "source_step": SOURCE_STEP, "source_time_s": SOURCE_TIME, "real_process_starts": manifest["real_process_starts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
