#!/usr/bin/env python3
"""Freeze the fresh 20 s physical-sanity contract before any CFD launch."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.multi_slice_mapping.mapping import SliceDefinition, SliceManifest, build_H_for_manifest, motion_from_ancf_state
BASE = ROOT / "tools" / "three_slice_force_contract_smoke_v2" / "three_slice_force_contract_smoke_v2_run_001.json"
STATE = ROOT / "runtime" / "stage4f_d_cpp_worker_initialization_v1" / "run_20260827_cpp_only" / "ancf_t0_state_cpp.json"
QUALITY = ROOT / "tools" / "numerical_quality_evidence_closure_v1" / "openfoam_numerical_quality_contract_v2.json"
OUT = Path(__file__).with_name("three_slice_physical_sanity_20s_v1_contract.json")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if OUT.exists():
        raise RuntimeError("refusing to overwrite frozen physical-sanity contract")
    base = json.loads(BASE.read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("equilibrated") is not True or digest(STATE) != base["ANCF"]["initial_state"]["sha256"]:
        raise RuntimeError("static-equilibrium source state identity is invalid")
    length, elements = float(base["ANCF"]["length_m"]), int(base["ANCF"]["elements"])
    items = base["slices"]["items"]
    positions = [float(item["s_ref_m"]) for item in items]
    boundaries = [0.0] + [(left + right) / 2.0 for left, right in zip(positions, positions[1:])] + [length]
    definitions = tuple(SliceDefinition(int(item["slice_id"]), float(item["s_ref_m"]), boundaries[index + 1] - boundaries[index], float(item["unit_span_m"])) for index, item in enumerate(items))
    manifest = SliceManifest("0.2.1", str(base["case_id"]), length, length, definitions)
    H = build_H_for_manifest(manifest, tuple(length * index / elements for index in range(elements + 1)))
    initial_local = [motion_from_ancf_state(manifest, sid, H[sid], state["q"], state["qdot"], state["qddot"], step=0, time_s=0.0, reference_position_m=(0.0, 0.0, definitions[sid].s_ref_m)).to_dict() for sid in range(3)]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    base.update({
        "schema_version": "three-slice-physical-sanity-20s-v1",
        "run_id": "three_slice_physical_sanity_20s_v1_run_001",
        "case_id": "three_slice_physical_sanity_20s_v1_case_001",
        "git_commit": commit,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "dt_s": 0.005,
        "duration_s": 20.0,
        "number_of_steps": 4000,
        "reference_semantics": {
            "mesh_displacement_reference": "undeformed_reference_mesh",
            "structural_initialization_reference": "static_equilibrium_configuration",
            "fluid_initial_condition_source": "fresh copy of cases/openfoam/single_slice_ancf_fsi/0; uniform initialized flow; not a restart"
        },
        "initial_state": {
            "source": str(STATE.relative_to(ROOT)).replace("\\", "/"), "sha256": digest(STATE),
            "global_step": state["global_step"], "time_s": state["time_s"], "integer_tick": state["integer_tick"],
            "equilibrated": state["equilibrated"], "q": state["q"], "qdot": state["qdot"], "qddot": state["qddot"],
            "delta_q0_relative_to_static_equilibrium": [0.0] * len(state["q"]),
            "delta_q0_norm": 0.0, "qdot0_norm": 0.0, "qddot0_norm": 0.0
        },
        "initial_local_slice_state": initial_local,
        "quality_contract_v2": {"source": str(QUALITY.relative_to(ROOT)).replace("\\", "/"), "sha256": digest(QUALITY), "frozen_before_run": True},
        "physical_sanity_contract": {
            "windows_s": {"FULL": [0.0, 20.0], "EARLY": [0.0, 5.0], "MID": [5.0, 10.0], "LATE": [10.0, 20.0]},
            "modal_projection": "not_available; no solver rewrite authorized",
            "spectrum_status": "exploratory_short_window; FFT_resolution_Hz=0.05",
            "hard_blowup_guard": {"max_abs_transverse_displacement_m": 7.5, "basis": "half of actual initial mesh vertical clearance from cylinder centre to y=+/-15 m"},
            "formal_status": {"FORMAL_STABLE_VIV": "not_evaluated", "FORMAL_LOCK_IN": "not_evaluated", "FORMAL_AMPLITUDE_CONVERGENCE": "not_evaluated", "FORMAL_FREQUENCY_CONVERGENCE": "not_evaluated"}
        }
    })
    OUT.write_text(json.dumps(base, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
