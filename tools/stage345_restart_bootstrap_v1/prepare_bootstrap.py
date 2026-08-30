"""Prepare, but do not execute, a restart bootstrap state for Stage341.

The generated state is a candidate for a future fresh smoke only.  It is not a
replacement for numerical equivalence or a license to resume Stage343.
"""
from __future__ import annotations

import json
import hashlib
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.restart_alignment_v1 import build_bootstrap  # noqa: E402
from coupling.stage303_interface_mapping_repair_v1 import canonical_h_row, project_interface  # noqa: E402

SOURCE = ROOT / "runtime/stage341_dt005_long_convergence_v1/logs/structure_participant.json"
OUT = ROOT / "results/345_restart_bootstrap_v1"


def main() -> int:
    state = json.loads(SOURCE.read_text(encoding="utf-8"))
    diagnostics_path = SOURCE.parent / "mapping_diagnostics.jsonl"
    diagnostics = [json.loads(line) for line in diagnostics_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(diagnostics) < 2 or diagnostics[-2].get("global_step") != int(state["target_global_step"]) - 1:
        raise RuntimeError("missing saved-field matching diagnostic step")
    bootstrap = build_bootstrap(
        source_global_step=int(state["target_global_step"]),
        field_time_s=float(state["target_time_s"]),
        final_q=state["final_q"], final_qdot=state["final_qdot"], final_qddot=state["final_qddot"],
        dt_s=0.005, lag_steps=2,
    )
    final_q = tuple(float(value) for value in state["final_q"])
    source_final_q_sha256 = hashlib.sha256(struct.pack("<" + "d" * len(final_q), *final_q)).hexdigest()
    # Keep the lagged restart state, then correct only the six exported x/y
    # interface values to the saved-field evidence. This does not alter the
    # ANCF kernel or physical parameters; it removes the restart boundary jump.
    target_xy = [tuple(float(value) for value in row) for row in diagnostics[-2]["interface_positions_xy"]]
    aligned_q = list(bootstrap.q)
    projected = project_interface(aligned_q, list(bootstrap.qdot))[0]
    positions = (8.333333333333334, 25.0, 41.666666666666664)
    for slice_index, position in enumerate(positions):
        row = canonical_h_row(position)
        for component in (0, 1):
            delta = target_xy[slice_index][component] - projected[slice_index][component]
            pivot = next((index for index, coefficient in enumerate(row) if abs(coefficient) > 1.0e-14 and index % 6 == component), None)
            if pivot is None:
                raise RuntimeError("interface alignment row has no pivot")
            aligned_q[pivot] += delta / row[pivot]
    aligned_projected = project_interface(aligned_q, list(bootstrap.qdot))[0]
    alignment_error = max(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in zip(aligned_projected, target_xy))
    if alignment_error > 1.0e-12:
        raise RuntimeError(f"bootstrap interface alignment exceeds tolerance: {alignment_error}")
    aligned_q_sha256 = hashlib.sha256(struct.pack("<" + "d" * len(aligned_q), *aligned_q)).hexdigest()
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "stage_id": "stage4f_d_restart_bootstrap_v1",
        "source_stage": "stage341_dt005_long_convergence_v1",
        "source_global_step": bootstrap.source_global_step,
        "field_time_s": bootstrap.field_time_s,
        "state_time_s": bootstrap.state_time_s,
        "lag_steps": bootstrap.lag_steps,
        "dt_s": bootstrap.dt_s,
        "q": aligned_q,
        "qdot": list(bootstrap.qdot),
        "qddot": list(bootstrap.qddot),
        "q_sha256": aligned_q_sha256,
        "source_final_q_sha256": source_final_q_sha256,
        "saved_field_interface_xy": [list(value) for value in target_xy],
        "saved_field_alignment_error_m": alignment_error,
        "direct_final_q_rejected": bootstrap.direct_final_q_rejected,
        "use_contract": "first two continuation windows are explicit bootstrap synchronization; normal continuation only after bootstrap ack",
        "status": "candidate_only_requires_fresh_smoke",
    }
    (OUT / "restart_bootstrap_state.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "gate_id": "STAGE4F_D_RESTART_BOOTSTRAP_PREPARATION_V1_GATE",
        "status": "pass",
        "source_runtime_read_only": True,
        "candidate": str(OUT / "restart_bootstrap_state.json"),
        "checks": {
            "source_finalized": state.get("finalized") is True,
            "state_time_before_field_time": bootstrap.state_time_s < bootstrap.field_time_s,
            "lag_explicit": bootstrap.lag_steps == 2,
            "direct_final_q_rejected": bootstrap.direct_final_q_rejected,
            "matlab_starts": 0,
            "openfoam_starts": 0,
            "wsl_starts": 0,
            "cfd_starts": 0,
            "owned_residual": 0,
        },
        "next_action": "new explicit authorization required for a fresh short restart smoke using this candidate",
    }
    (OUT / "stage4f_d_restart_bootstrap_preparation_v1_gate.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": manifest["status"], "candidate": str(OUT / "restart_bootstrap_state.json"), "state_time_s": bootstrap.state_time_s, "field_time_s": bootstrap.field_time_s}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
