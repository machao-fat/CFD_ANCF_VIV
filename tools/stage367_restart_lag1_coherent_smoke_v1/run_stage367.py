"""Run one fresh 40-step lag-1 coherent restart Smoke."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "tools/stage346_restart_bootstrap_real_v1/run_stage346.py"
spec = importlib.util.spec_from_file_location("stage346_impl", SHARED)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load shared launcher")
impl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(impl)

impl.SOURCE_RUNTIME = ROOT / "runtime/stage341_dt005_long_convergence_v1"
impl.SOURCE_STATE = impl.SOURCE_RUNTIME / "logs/structure_participant.json"
impl.BOOTSTRAP_STATE = ROOT / "results/350_restart_bootstrap_velocity_v1/restart_bootstrap_state.json"
impl.SMOKE_RUNTIME = ROOT / "runtime/stage367_restart_lag1_coherent_smoke_v1"
impl.SMOKE_RESULTS = ROOT / "results/367_restart_lag1_coherent_smoke_v1"
impl.CONT_RUNTIME = ROOT / "runtime/stage367_continuation_forbidden"
impl.CONT_RESULTS = ROOT / "results/367_continuation_forbidden"
impl.SOURCE_STEP = 16000
impl.SOURCE_TIME = 80.0
impl.SMOKE_STEPS = 40
impl.SMOKE_TARGET = 80.2
impl.SMOKE_RUN_ID = "run367_restart_lag1_coherent_smoke_v1"
impl.SMOKE_CASE_ID = "case367_restart_lag1_coherent_smoke_v1"


def main() -> int:
    source_manifest, bootstrap = impl.verify_source()
    candidate = json.loads((ROOT / "results/366_restart_lag1_coherent_candidate_v1/candidate_manifest.json").read_text(encoding="utf-8"))
    if candidate.get("status") != "pass" or not candidate.get("checks", {}).get("all_three_bootstrap_geometries_aligned"):
        raise RuntimeError("Stage366 lag-1 candidate Gate is not passing")
    for path in (impl.SMOKE_RUNTIME, impl.SMOKE_RESULTS, impl.CONT_RUNTIME, impl.CONT_RESULTS):
        if path.exists() and any(path.iterdir()):
            raise RuntimeError(f"refusing to reuse non-empty path: {path}")
    started = datetime.now(timezone.utc)
    cases = impl.prepare_cases(impl.SMOKE_RUNTIME, impl.SOURCE_RUNTIME, "80", 80.0, 80.2, source_manifest)
    initial = impl.SMOKE_RUNTIME / "logs" / "bootstrap_initial_state.json"
    initial.write_text(json.dumps({
        "final_q": list(bootstrap.q), "final_qdot": list(bootstrap.qdot), "final_qddot": list(bootstrap.qddot),
        "bootstrap_state_time_s": bootstrap.state_time_s, "field_time_s": bootstrap.field_time_s,
        "lag_steps": bootstrap.lag_steps, "source_global_step": bootstrap.source_global_step,
        "q_sha256": bootstrap.q_sha256,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run_return, elapsed = impl.launch(
        impl.SMOKE_RUNTIME, cases, initial_state=initial, source_step=16000, source_time=80.0,
        steps=40, run_id=impl.SMOKE_RUN_ID, case_id=impl.SMOKE_CASE_ID,
    )
    gate = impl.audit(
        impl.SMOKE_RUNTIME, impl.SMOKE_RESULTS, run_id=impl.SMOKE_RUN_ID, case_id=impl.SMOKE_CASE_ID,
        source_step=16000, source_time=80.0, steps=40, target_time=80.2, run_return=run_return,
        elapsed_s=elapsed, bootstrap=True, source_manifest=source_manifest,
    )
    gate.update({
        "gate_id": "STAGE4F_D_RESTART_LAG1_COHERENT_SMOKE_V1_GATE",
        "stage_id": "stage4f_d_restart_lag1_coherent_smoke_v1",
        "authorization": "user_authorized_real_smoke",
        "initial_state_binding": "Stage350 lag-1 q/qdot/qddot at state_time=79.995 s with field clock 80.0 s",
        "candidate_manifest": str(ROOT / "results/366_restart_lag1_coherent_candidate_v1/stage4f_d_restart_lag1_coherent_candidate_v1_gate.json"),
        "first_step_mesh_quality_audit": "required_by_launcher_and_quality_records",
    })
    impl.SMOKE_RESULTS.mkdir(parents=True, exist_ok=True)
    (impl.SMOKE_RESULTS / "stage4f_d_restart_lag1_coherent_smoke_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (impl.SMOKE_RESULTS / "chain_decision.json").write_text(json.dumps({
        "decision": "smoke_complete_no_continuation" if gate["status"] == "pass" else "stop_fail_closed",
        "smoke_gate": gate["status"], "continuation_started": False,
        "started_utc": started.isoformat(), "source_time_s": 80.0, "target_time_s": 80.2,
        "initial_state_binding": gate["initial_state_binding"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
