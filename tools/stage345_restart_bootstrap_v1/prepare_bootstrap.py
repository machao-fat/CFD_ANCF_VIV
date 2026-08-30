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

SOURCE = ROOT / "runtime/stage341_dt005_long_convergence_v1/logs/structure_participant.json"
OUT = ROOT / "results/345_restart_bootstrap_v1"


def main() -> int:
    state = json.loads(SOURCE.read_text(encoding="utf-8"))
    bootstrap = build_bootstrap(
        source_global_step=int(state["target_global_step"]),
        field_time_s=float(state["target_time_s"]),
        final_q=state["final_q"], final_qdot=state["final_qdot"], final_qddot=state["final_qddot"],
        dt_s=0.005, lag_steps=2,
    )
    final_q = tuple(float(value) for value in state["final_q"])
    source_final_q_sha256 = hashlib.sha256(struct.pack("<" + "d" * len(final_q), *final_q)).hexdigest()
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
        "q": list(bootstrap.q),
        "qdot": list(bootstrap.qdot),
        "qddot": list(bootstrap.qddot),
        "q_sha256": bootstrap.q_sha256,
        "source_final_q_sha256": source_final_q_sha256,
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
