"""Run a deterministic restart-aware smoke without starting solver processes."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.restart_bootstrap_v1 import (  # noqa: E402
    BootstrapProtocolError,
    BootstrapSession,
    RestartBootstrapState,
    make_bootstrap_ack,
    make_bootstrap_seed,
    reject_direct_final_q,
)

STATE_PATH = ROOT / "results/345_restart_bootstrap_v1/restart_bootstrap_state.json"
SOURCE_STATE_PATH = ROOT / "runtime/stage341_dt005_long_convergence_v1/logs/structure_participant.json"
OUT = ROOT / "results/345_restart_bootstrap_v1"


def main() -> int:
    state = RestartBootstrapState.from_mapping(json.loads(STATE_PATH.read_text(encoding="utf-8")))
    source_final_q = json.loads(SOURCE_STATE_PATH.read_text(encoding="utf-8"))["final_q"]
    session = BootstrapSession(state, "run345_restart_bootstrap_smoke_v1", "case345_restart_bootstrap_smoke_v1")
    accepted = []
    events = []
    for window in (0, 1):
        seed = make_bootstrap_seed(run_id=session.run_id, case_id=session.case_id, window=window, state=state)
        ack = make_bootstrap_ack(seed, state=state)
        events.append({"kind": seed.kind, "window": window, "global_step": seed.global_step, "time_s": seed.time_s, "integer_tick": seed.integer_tick, "payload_hash": seed.payload_hash})
        session.accept_ack(ack)
        events.append({"kind": ack.kind, "window": window, "global_step": ack.global_step, "time_s": ack.time_s, "integer_tick": ack.integer_tick, "payload_hash": ack.payload_hash})
        accepted.append(window)
    session.require_ready_for_normal_continuation()

    injected: dict[str, str] = {}
    try:
        reject_direct_final_q(source_final_q, state)
    except BootstrapProtocolError as exc:
        injected["direct_final_q"] = str(exc)
    else:
        injected["direct_final_q"] = "NOT_REJECTED"
    seed0 = make_bootstrap_seed(run_id=session.run_id, case_id=session.case_id, window=0, state=state)
    bad_ack = replace(make_bootstrap_ack(seed0, state=state), bootstrap_window=1).seal()
    try:
        BootstrapSession(state, session.run_id, session.case_id).accept_ack(bad_ack)
    except BootstrapProtocolError as exc:
        injected["stale_ack"] = str(exc)
    else:
        injected["stale_ack"] = "NOT_REJECTED"
    target_ack = replace(make_bootstrap_ack(seed0, state=state), time_s=state.field_time_s + state.dt_s).seal()
    try:
        BootstrapSession(state, session.run_id, session.case_id).accept_ack(target_ack)
    except BootstrapProtocolError as exc:
        injected["target_time_as_bootstrap"] = str(exc)
    else:
        injected["target_time_as_bootstrap"] = "NOT_REJECTED"
    try:
        BootstrapSession(state, session.run_id, session.case_id).accept_ack(replace(make_bootstrap_ack(seed0, state=state), q_sha256="0" * 64).seal())
    except BootstrapProtocolError as exc:
        injected["q_hash_mismatch"] = str(exc)
    else:
        injected["q_hash_mismatch"] = "NOT_REJECTED"
    result = {
        "schema_version": 1,
        "stage_id": "stage4f_d_restart_bootstrap_smoke_v1",
        "run_id": session.run_id,
        "case_id": session.case_id,
        "source_global_step": state.source_global_step,
        "field_time_s": state.field_time_s,
        "state_time_s": state.state_time_s,
        "accepted_bootstrap_windows": accepted,
        "events": events,
        "bootstrap_ready": session.bootstrap_acked,
        "injected_faults": injected,
        "real_process_counts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "owned_residual": 0,
    }
    gate = {
        "gate_id": "STAGE4F_D_RESTART_BOOTSTRAP_SMOKE_V1_GATE",
        "status": "pass" if accepted == [0, 1] and session.bootstrap_acked and all(value != "NOT_REJECTED" for value in injected.values()) else "do_not_pass",
        "checks": {
            "two_bootstrap_windows_acked": accepted == [0, 1],
            "normal_continuation_gated": session.bootstrap_acked,
            "direct_final_q_rejected": injected["direct_final_q"] != "NOT_REJECTED",
            "stale_ack_rejected": injected["stale_ack"] != "NOT_REJECTED",
            "real_process_counts_zero": result["real_process_counts"] == {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
            "owned_residual_zero": result["owned_residual"] == 0,
        },
        "source_runtime_read_only": True,
        "next_action": "request a new explicit authorization for a fresh short restart smoke; do not resume Stage343",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "restart_bootstrap_smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "stage4f_d_restart_bootstrap_smoke_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "accepted": accepted, "real_process_counts": result["real_process_counts"]}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
