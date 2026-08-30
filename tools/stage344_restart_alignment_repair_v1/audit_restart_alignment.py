"""Offline audit of the Stage341 restart-field/structure-state alignment.

The Stage341 final OpenFOAM field at directory ``80`` is compared with the
retained mapping diagnostics.  This identifies the coupling output lag that
caused the Stage343 restart displacement jump.  No solver or CFD process is
started and no source runtime is modified.
"""
from __future__ import annotations

import json
import math
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.stage303_interface_mapping_repair_v1 import project_interface  # noqa: E402

SOURCE_RUNTIME = ROOT / "runtime/stage341_dt005_long_convergence_v1"
RESULTS = ROOT / "results/344_restart_alignment_repair_v1"
DT = 0.005


def read_cylinder_displacement(path: Path) -> tuple[float, float, float]:
    raw = path.read_bytes()
    marker = raw.find(b"cyl\n")
    if marker < 0:
        raise ValueError(f"cyl patch missing: {path}")
    opening = raw.find(b"(", marker)
    if opening < 0:
        raise ValueError(f"cyl value missing: {path}")
    return struct.unpack_from("<3d", raw, opening + 1)


def load_diagnostics() -> list[dict[str, object]]:
    path = SOURCE_RUNTIME / "logs/mapping_diagnostics.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError("mapping diagnostics are empty")
    return rows


def max_error(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    return max(math.hypot(x[0] - y[0], x[1] - y[1]) for x, y in zip(a, b))


def main() -> int:
    state_path = SOURCE_RUNTIME / "logs/structure_participant.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    diagnostics = load_diagnostics()
    if diagnostics[-1]["global_step"] != 16000 or diagnostics[-2]["global_step"] != 15999:
        raise ValueError("Stage341 diagnostics do not end at steps 15999/16000")
    field_xy = []
    for index in range(3):
        field = SOURCE_RUNTIME / f"slice_{index:04d}/80/pointDisplacement"
        value = read_cylinder_displacement(field)
        field_xy.append((value[0], value[1]))
    diag_15999 = [tuple(float(value) for value in row) for row in diagnostics[-2]["interface_positions_xy"]]
    diag_16000 = [tuple(float(value) for value in row) for row in diagnostics[-1]["interface_positions_xy"]]
    field_match_15999 = max_error(field_xy, [(row[0], row[1]) for row in diag_15999])
    field_match_16000 = max_error(field_xy, [(row[0], row[1]) for row in diag_16000])
    q = [float(value) for value in state["final_q"]]
    qdot = [float(value) for value in state["final_qdot"]]
    qddot = [float(value) for value in state["final_qddot"]]
    lagged_states = {}
    for lag_steps in (1, 2):
        horizon = lag_steps * DT
        lag_q = [q[i] - horizon * qdot[i] + 0.5 * horizon * horizon * qddot[i] for i in range(len(q))]
        lag_qdot = [qdot[i] - horizon * qddot[i] for i in range(len(qdot))]
        projected = project_interface(lag_q, lag_qdot)[0]
        lagged_states[str(lag_steps)] = {
            "q": lag_q,
            "qdot": lag_qdot,
            "projected_interface_xy": [list(value) for value in projected],
            "error_to_saved_field_max_m": max_error(projected, field_xy),
        }
    report = {
        "schema_version": 1,
        "stage_id": "stage4f_d_restart_alignment_repair_v1",
        "source_stage": "stage341_dt005_long_convergence_v1",
        "source_state": {"path": str(state_path), "target_step": state["target_global_step"], "target_time_s": state["target_time_s"]},
        "saved_field_role": {
            "directory_time_s": 80.0,
            "matching_diagnostics_step": 15999,
            "matching_diagnostics_time_s": float(diagnostics[-2]["time_s"]),
            "field_matches_step_15999_max_m": field_match_15999,
            "field_matches_step_16000_max_m": field_match_16000,
            "diagnostic_hash_evidence": "mapping_diagnostics.jsonl retained source evidence",
        },
        "lagged_state_estimates": lagged_states,
        "restart_contract": {
            "reject_direct_final_q": True,
            "reason": "final_q is one coupling state newer than the saved OpenFOAM boundary field",
            "required_bootstrap": "explicit state/field synchronization before normal continuation",
            "provisional_lag_steps": 2,
            "provisional_lag_is_not_numerical_equivalence": True,
        },
        "checks": {
            "saved_field_matches_step_15999": field_match_15999 < 1.0e-12,
            "saved_field_not_step_16000": field_match_16000 > field_match_15999,
            "source_finalized": state.get("finalized") is True,
            "offline_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
            "source_runtime_modified": False,
            "owned_residual": 0,
        },
        "gate": "pass" if field_match_15999 < 1.0e-12 and field_match_16000 > field_match_15999 else "do_not_pass",
        "next_action": "implement and offline-test explicit bootstrap; require a fresh short real smoke before any 80->200 continuation",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "restart_alignment_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "stage4f_d_restart_alignment_repair_v1_gate.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": report["gate"], "field_match_step15999_m": field_match_15999, "field_match_step16000_m": field_match_16000, "offline_process_starts": report["checks"]["offline_process_starts"]}, ensure_ascii=False))
    return 0 if report["gate"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
