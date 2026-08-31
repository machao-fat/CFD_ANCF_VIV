"""Run one fresh Smoke from the derived-flux-free restart candidate."""
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

impl.SOURCE_RUNTIME = ROOT / "runtime/stage360_restart_derived_flux_repair_v1_fresh"
impl.SOURCE_STATE = ROOT / "runtime/stage341_dt005_long_convergence_v1/logs/structure_participant.json"
impl.BOOTSTRAP_STATE = ROOT / "results/350_restart_bootstrap_velocity_v1/restart_bootstrap_state.json"
impl.SMOKE_RUNTIME = ROOT / "runtime/stage361_restart_derived_flux_smoke_v1"
impl.SMOKE_RESULTS = ROOT / "results/361_restart_derived_flux_smoke_v1"
impl.CONT_RUNTIME = ROOT / "runtime/stage361_continuation_forbidden"
impl.CONT_RESULTS = ROOT / "results/361_continuation_forbidden"
impl.SOURCE_STEP = 15999
impl.SOURCE_TIME = 79.995
impl.SMOKE_STEPS = 40
impl.SMOKE_TARGET = 80.195
impl.CONT_STEPS = 0
impl.CONT_TARGET = 80.195
impl.SMOKE_RUN_ID = "run361_restart_derived_flux_smoke_v1"
impl.SMOKE_CASE_ID = "case361_restart_derived_flux_smoke_v1"
impl.CONT_RUN_ID = "run361_continuation_forbidden"
impl.CONT_CASE_ID = "case361_continuation_forbidden"


def verify_saved_time_source():
    required = (impl.SOURCE_STATE, impl.BOOTSTRAP_STATE, impl.FIXTURE, impl.WORKER, impl.PARTICIPANT, impl.QUALITY)
    if not all(path.is_file() for path in required):
        missing = [str(path) for path in required if not path.is_file()]
        raise RuntimeError(f"missing required source: {missing}")
    source = json.loads(impl.SOURCE_STATE.read_text(encoding="utf-8"))
    if source.get("finalized") is not True or source.get("target_global_step") != 16000:
        raise RuntimeError("Stage341 source is not finalized at global step 16000")
    bootstrap = impl.RestartBootstrapState.from_mapping(json.loads(impl.BOOTSTRAP_STATE.read_text(encoding="utf-8")))
    if bootstrap.source_global_step != 16000 or abs(bootstrap.state_time_s - 79.995) > 1e-12:
        raise RuntimeError("Stage350 bootstrap is not the expected 79.995 s state")
    for index in range(3):
        restart = impl.SOURCE_RUNTIME / f"slice_{index:04d}" / "79.995"
        required_fields = ("U", "p", "pointDisplacement", "cellDisplacement", "Force")
        if not all((restart / name).is_file() for name in required_fields):
            raise RuntimeError(f"missing retained field in {restart}")
        if any((restart / name).exists() for name in ("phi", "meshPhi", "Uf")):
            raise RuntimeError(f"derived flux field was not removed in {restart}")
    return {
        "source_state_sha256": impl.file_sha(impl.SOURCE_STATE),
        "bootstrap_sha256": impl.file_sha(impl.BOOTSTRAP_STATE),
        "source_step": 15999,
        "source_time_s": 79.995,
        "saved_field_label": "79.995",
        "derived_flux_fields_absent": True,
    }, bootstrap


def main() -> int:
    started = datetime.now(timezone.utc)
    source_manifest, bootstrap = verify_saved_time_source()
    for path in (impl.SMOKE_RUNTIME, impl.SMOKE_RESULTS, impl.CONT_RUNTIME, impl.CONT_RESULTS):
        if path.exists() and any(path.iterdir()):
            raise RuntimeError(f"refusing to reuse non-empty path: {path}")
    cases = impl.prepare_cases(impl.SMOKE_RUNTIME, impl.SOURCE_RUNTIME, "79.995", impl.SOURCE_TIME, impl.SMOKE_TARGET, source_manifest)
    aligned_state = impl.SOURCE_RUNTIME / "logs" / "initial_state.json"
    if not aligned_state.is_file():
        raise RuntimeError(f"missing Stage360 initial state: {aligned_state}")
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
    (impl.SMOKE_RESULTS / "chain_decision.json").write_text(json.dumps({
        "decision": "smoke_complete_no_continuation", "smoke_gate": gate["status"],
        "continuation_started": False, "started_utc": started.isoformat(),
        "saved_field_time_s": 79.995, "derived_flux_fields_absent": True,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
