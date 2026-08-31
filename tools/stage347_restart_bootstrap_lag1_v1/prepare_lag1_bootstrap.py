"""Prepare a fresh lag-1 restart state matching the saved 79.995 s field."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.restart_alignment_v1 import build_bootstrap  # noqa: E402
from coupling.stage303_interface_mapping_repair_v1 import canonical_h_row, project_interface  # noqa: E402

SOURCE_RUNTIME = ROOT / "runtime/stage341_dt005_long_convergence_v1"
SOURCE_STATE = SOURCE_RUNTIME / "logs/structure_participant.json"
DIAGNOSTICS = SOURCE_RUNTIME / "logs/mapping_diagnostics.jsonl"
OUT = ROOT / "results/347_restart_bootstrap_lag1_v1"


def digest(values: list[float]) -> str:
    return hashlib.sha256(struct.pack("<" + "d" * len(values), *values)).hexdigest()


def main() -> int:
    source = json.loads(SOURCE_STATE.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in DIAGNOSTICS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if source.get("finalized") is not True or source.get("target_global_step") != 16000 or abs(float(source.get("target_time_s", -1)) - 80.0) > 1e-12:
        raise RuntimeError("source is not finalized at 16000/80 s")
    if len(rows) < 2 or rows[-2].get("global_step") != 15999:
        raise RuntimeError("saved-field matching diagnostic step 15999 is missing")
    b = build_bootstrap(source_global_step=16000, field_time_s=80.0, final_q=source["final_q"], final_qdot=source["final_qdot"], final_qddot=source["final_qddot"], dt_s=0.005, lag_steps=1)
    q = list(b.q)
    projected = project_interface(q, list(b.qdot))[0]
    target = [tuple(float(v) for v in row) for row in rows[-2]["interface_positions_xy"]]
    positions = (8.333333333333334, 25.0, 41.666666666666664)
    for slice_index, position in enumerate(positions):
        row = canonical_h_row(position)
        for component in (0, 1):
            delta = target[slice_index][component] - projected[slice_index][component]
            pivot = next(i for i, value in enumerate(row) if i % 6 == component and abs(value) > 1e-14)
            q[pivot] += delta / row[pivot]
    aligned = project_interface(q, list(b.qdot))[0]
    error = max(((a[0] - t[0]) ** 2 + (a[1] - t[1]) ** 2) ** 0.5 for a, t in zip(aligned, target))
    if error > 1e-12:
        raise RuntimeError(f"lag1 interface alignment error {error} exceeds tolerance")
    payload = {
        "schema_version": 1,
        "stage_id": "stage4f_d_restart_bootstrap_lag1_v1",
        "source_stage": "stage341_dt005_long_convergence_v1",
        "source_global_step": 16000,
        "field_time_s": 80.0,
        "state_time_s": 79.995,
        "lag_steps": 1,
        "dt_s": 0.005,
        "q": q,
        "qdot": list(b.qdot),
        "qddot": list(b.qddot),
        "q_sha256": digest(q),
        "source_final_q_sha256": digest([float(v) for v in source["final_q"]]),
        "saved_field_interface_xy": [list(v) for v in target],
        "saved_field_alignment_error_m": error,
        "direct_final_q_rejected": True,
        "status": "candidate_only_requires_fresh_smoke",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "restart_bootstrap_state.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate = {
        "gate_id": "STAGE4F_D_RESTART_BOOTSTRAP_LAG1_PREPARATION_V1_GATE",
        "status": "pass",
        "checks": {"source_finalized": True, "saved_field_step": 15999, "lag_steps": 1, "field_alignment_error_m": error, "direct_final_q_rejected": True, "source_runtime_read_only": True, "matlab_starts": 0, "openfoam_starts": 0, "wsl_starts": 0, "cfd_starts": 0, "owned_residual": 0},
        "next_action": "fresh Stage347 real smoke only; continuation must wait for its pass gate",
    }
    (OUT / "stage4f_d_restart_bootstrap_lag1_preparation_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "lag_steps": 1, "state_time_s": 79.995, "field_alignment_error_m": error}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
