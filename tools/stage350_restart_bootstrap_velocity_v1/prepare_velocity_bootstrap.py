"""Build a fresh lag-1 restart state aligned to saved displacement and velocity."""
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
OUT = ROOT / "results/350_restart_bootstrap_velocity_v1"
DT = 0.005
POSITIONS = (8.333333333333334, 25.0, 41.666666666666664)


def digest(values: list[float]) -> str:
    return hashlib.sha256(struct.pack("<" + "d" * len(values), *values)).hexdigest()


def align(values: list[float], target: list[list[float]], projected: list[tuple[float, float]], label: str) -> tuple[list[float], float]:
    for slice_index, row_target in enumerate(target):
        row = canonical_h_row(POSITIONS[slice_index])
        for component in (0, 1):
            delta = float(row_target[component]) - float(projected[slice_index][component])
            pivot = next(i for i, value in enumerate(row) if i % 6 == component and abs(value) > 1.0e-14)
            values[pivot] += delta / row[pivot]
    after = project_interface(values, values)[0] if label == "q" else None
    if label == "q":
        error = max(((a[0] - t[0]) ** 2 + (a[1] - t[1]) ** 2) ** 0.5 for a, t in zip(after, target))
    else:
        projected_after = project_interface([0.0] * len(values), values)[1]
        error = max(((a[0] - t[0]) ** 2 + (a[1] - t[1]) ** 2) ** 0.5 for a, t in zip(projected_after, target))
    return values, error


def main() -> int:
    source = json.loads(SOURCE_STATE.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in DIAGNOSTICS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if source.get("finalized") is not True or source.get("target_global_step") != 16000:
        raise RuntimeError("source is not finalized at global step 16000")
    if len(rows) < 3 or [rows[-3].get("global_step"), rows[-2].get("global_step")] != [15998, 15999]:
        raise RuntimeError("adjacent diagnostics steps 15998/15999 are required")
    base = build_bootstrap(
        source_global_step=16000, field_time_s=80.0,
        final_q=source["final_q"], final_qdot=source["final_qdot"], final_qddot=source["final_qddot"],
        dt_s=DT, lag_steps=1,
    )
    q = list(base.q)
    qdot = list(base.qdot)
    qddot = list(base.qddot)
    target_q = rows[-2]["interface_positions_xy"]
    target_v = rows[-2]["interface_velocities_xy"]
    target_a = [[(float(rows[-2]["interface_velocities_xy"][i][c]) - float(rows[-3]["interface_velocities_xy"][i][c])) / DT for c in (0, 1)] for i in range(3)]
    q, q_error = align(q, target_q, project_interface(q, qdot)[0], "q")
    qdot, v_error = align(qdot, target_v, project_interface(q, qdot)[1], "qdot")
    qddot, a_error = align(qddot, target_a, project_interface(q, qddot)[1], "qddot")
    if max(q_error, v_error, a_error) > 1.0e-10:
        raise RuntimeError(f"bootstrap kinematic alignment exceeds tolerance: q={q_error}, v={v_error}, a={a_error}")
    payload = {
        "schema_version": 1,
        "stage_id": "stage4f_d_restart_bootstrap_velocity_v1",
        "source_stage": "stage341_dt005_long_convergence_v1",
        "source_global_step": 16000,
        "field_time_s": 80.0,
        "state_time_s": 79.995,
        "lag_steps": 1,
        "dt_s": DT,
        "q": q,
        "qdot": qdot,
        "qddot": qddot,
        "q_sha256": digest(q),
        "qdot_sha256": digest(qdot),
        "qddot_sha256": digest(qddot),
        "alignment": {
            "source_steps": [15998, 15999],
            "displacement_error_m": q_error,
            "velocity_error_m_per_s": v_error,
            "acceleration_error_m_per_s2": a_error,
        },
        "direct_final_q_rejected": True,
        "status": "candidate_only_requires_fresh_smoke",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "restart_bootstrap_state.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate = {
        "gate_id": "STAGE4F_D_RESTART_BOOTSTRAP_VELOCITY_PREPARATION_V1_GATE",
        "status": "pass",
        "checks": {
            "source_finalized": True,
            "adjacent_diagnostics_present": True,
            "displacement_aligned": q_error <= 1.0e-10,
            "velocity_aligned": v_error <= 1.0e-10,
            "acceleration_aligned": a_error <= 1.0e-10,
            "direct_final_q_rejected": True,
            "source_runtime_read_only": True,
            "matlab_starts": 0,
            "openfoam_starts": 0,
            "wsl_starts": 0,
            "cfd_starts": 0,
            "owned_residual": 0,
        },
        "next_action": "fresh real smoke only; continuation must wait for a passing smoke Gate",
    }
    (OUT / "stage4f_d_restart_bootstrap_velocity_preparation_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "displacement_error_m": q_error, "velocity_error_m_per_s": v_error, "acceleration_error_m_per_s2": a_error}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
