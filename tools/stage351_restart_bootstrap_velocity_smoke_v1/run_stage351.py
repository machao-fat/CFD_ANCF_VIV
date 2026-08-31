"""Run one fresh real smoke using the Stage350 kinematic bootstrap."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/stage348_restart_field_time_v1/run_stage348.py"
spec = importlib.util.spec_from_file_location("stage348_impl", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load shared restart launcher")
stage348 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage348)
impl = stage348.impl

impl.BOOTSTRAP_STATE = ROOT / "results/350_restart_bootstrap_velocity_v1/restart_bootstrap_state.json"
impl.SMOKE_RUNTIME = ROOT / "runtime/stage351_restart_bootstrap_velocity_smoke_v1"
impl.SMOKE_RESULTS = ROOT / "results/351_restart_bootstrap_velocity_smoke_v1"
impl.SMOKE_RUN_ID = "run351_restart_bootstrap_velocity_smoke_v1"
impl.SMOKE_CASE_ID = "case351_restart_bootstrap_velocity_smoke_v1"

started = datetime.now(timezone.utc)
source_manifest, bootstrap = impl.verify_source()
if impl.SMOKE_RUNTIME.exists() and any(impl.SMOKE_RUNTIME.iterdir()):
    raise RuntimeError(f"refusing to reuse non-empty runtime: {impl.SMOKE_RUNTIME}")
cases = impl.prepare_cases(
    impl.SMOKE_RUNTIME, impl.SOURCE_RUNTIME, "80", impl.SOURCE_TIME,
    impl.SMOKE_TARGET, source_manifest,
)
initial = impl.SMOKE_RUNTIME / "logs" / "bootstrap_initial_state.json"
initial.write_text(json.dumps({
    "final_q": list(bootstrap.q), "final_qdot": list(bootstrap.qdot),
    "final_qddot": list(bootstrap.qddot), "bootstrap_state_time_s": bootstrap.state_time_s,
    "field_time_s": bootstrap.field_time_s, "lag_steps": bootstrap.lag_steps,
    "q_sha256": bootstrap.q_sha256,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
run_return, elapsed = impl.launch(
    impl.SMOKE_RUNTIME, cases, initial_state=initial,
    source_step=impl.SOURCE_STEP, source_time=impl.SOURCE_TIME,
    steps=impl.SMOKE_STEPS, run_id=impl.SMOKE_RUN_ID, case_id=impl.SMOKE_CASE_ID,
)
gate = impl.audit(
    impl.SMOKE_RUNTIME, impl.SMOKE_RESULTS, run_id=impl.SMOKE_RUN_ID,
    case_id=impl.SMOKE_CASE_ID, source_step=impl.SOURCE_STEP,
    source_time=impl.SOURCE_TIME, steps=impl.SMOKE_STEPS,
    target_time=impl.SMOKE_TARGET, run_return=run_return,
    elapsed_s=elapsed, bootstrap=True, source_manifest=source_manifest,
)
(impl.SMOKE_RESULTS / "chain_decision.json").write_text(json.dumps({
    "decision": "smoke_only_complete",
    "smoke_gate": gate["status"],
    "continuation_started": False,
    "started_utc": started.isoformat(),
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
raise SystemExit(0 if gate["status"] == "pass" else 1)
