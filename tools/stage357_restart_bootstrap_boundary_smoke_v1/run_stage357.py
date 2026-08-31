"""Run one fresh restart smoke with a state and field at the same clock time."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/stage346_restart_bootstrap_real_v1/run_stage346.py"
spec = importlib.util.spec_from_file_location("stage346_impl", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load shared restart launcher")
impl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(impl)

impl.SOURCE_RUNTIME = ROOT / "runtime/stage356_restart_bootstrap_boundary_alignment_v1_fresh"
impl.SOURCE_STATE = ROOT / "runtime/stage341_dt005_long_convergence_v1/logs/structure_participant.json"
# This file supplies the source manifest required by the shared verifier; the
# actual 80.0 s state passed to the participant is the Stage356 aligned state.
impl.BOOTSTRAP_STATE = ROOT / "results/350_restart_bootstrap_velocity_v1/restart_bootstrap_state.json"
impl.SMOKE_RUNTIME = ROOT / "runtime/stage357_restart_bootstrap_boundary_smoke_v1"
impl.SMOKE_RESULTS = ROOT / "results/357_restart_bootstrap_boundary_smoke_v1"
impl.CONT_RUNTIME = ROOT / "runtime/stage357_continuation_forbidden"
impl.CONT_RESULTS = ROOT / "results/357_continuation_forbidden"
impl.SOURCE_STEP = 16000
impl.SOURCE_TIME = 80.0
impl.SMOKE_STEPS = 40
impl.SMOKE_TARGET = 80.2
impl.CONT_STEPS = 0
impl.CONT_TARGET = 80.2
impl.SMOKE_RUN_ID = "run357_restart_bootstrap_boundary_smoke_v1"
impl.SMOKE_CASE_ID = "case357_restart_bootstrap_boundary_smoke_v1"
impl.CONT_RUN_ID = "run357_continuation_forbidden"
impl.CONT_CASE_ID = "case357_continuation_forbidden"


def main() -> int:
    started = datetime.now(timezone.utc)
    source_manifest, _ = impl.verify_source()
    for path in (impl.SMOKE_RUNTIME, impl.SMOKE_RESULTS, impl.CONT_RUNTIME, impl.CONT_RESULTS):
        if path.exists() and any(path.iterdir()):
            raise RuntimeError(f"refusing to reuse non-empty path: {path}")
    cases = impl.prepare_cases(impl.SMOKE_RUNTIME, impl.SOURCE_RUNTIME, "80", impl.SOURCE_TIME, impl.SMOKE_TARGET, source_manifest)
    aligned_state = impl.SOURCE_RUNTIME / "logs" / "initial_state.json"
    if not aligned_state.is_file():
        raise RuntimeError(f"missing Stage356 aligned state: {aligned_state}")
    initial = impl.SMOKE_RUNTIME / "logs" / "bootstrap_initial_state.json"
    initial.write_text(aligned_state.read_text(encoding="utf-8"), encoding="utf-8")
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
    decision = {
        "decision": "smoke_complete_no_continuation",
        "smoke_gate": gate["status"],
        "continuation_started": False,
        "started_utc": started.isoformat(),
        "stage356_source_runtime": str(impl.SOURCE_RUNTIME),
        "aligned_state_time_s": 80.0,
    }
    (impl.SMOKE_RESULTS / "chain_decision.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
