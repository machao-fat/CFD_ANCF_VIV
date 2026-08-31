"""Prepare a time-aligned fresh smoke/continuation chain (not started here)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/stage346_restart_bootstrap_real_v1/run_stage346.py"
spec = importlib.util.spec_from_file_location("stage346_impl", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load shared launcher")
impl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(impl)

impl.BOOTSTRAP_STATE = ROOT / "results/347_restart_bootstrap_lag1_v1/restart_bootstrap_state.json"
impl.SMOKE_RUNTIME = ROOT / "runtime/stage348_restart_field_time_smoke_v1"
impl.SMOKE_RESULTS = ROOT / "results/348_restart_field_time_smoke_v1"
impl.CONT_RUNTIME = ROOT / "runtime/stage348_restart_field_time_continuation_v1"
impl.CONT_RESULTS = ROOT / "results/348_restart_field_time_continuation_v1"
impl.SOURCE_STEP = 15999
impl.SOURCE_TIME = 79.995
impl.SMOKE_STEPS = 41
impl.SMOKE_TARGET = 80.2
impl.CONT_STEPS = 23960
impl.CONT_TARGET = 200.0
impl.SMOKE_RUN_ID = "run348_restart_field_time_smoke_v1"
impl.SMOKE_CASE_ID = "case348_restart_field_time_smoke_v1"
impl.CONT_RUN_ID = "run348_restart_field_time_continuation_v1"
impl.CONT_CASE_ID = "case348_restart_field_time_continuation_v1"

_original_verify = impl.verify_source


def verify_source_anchored():
    # Shared source audit expects the finalized checkpoint at 16000/80 s;
    # the runtime contract itself starts from the matching field step 15999.
    old_step, old_time = impl.SOURCE_STEP, impl.SOURCE_TIME
    impl.SOURCE_STEP, impl.SOURCE_TIME = 16000, 80.0
    try:
        return _original_verify()
    finally:
        impl.SOURCE_STEP, impl.SOURCE_TIME = old_step, old_time


impl.verify_source = verify_source_anchored
_original_prepare = impl.prepare_cases


def prepare_cases_time_aligned(runtime, source_runtime, source_time_dir, source_time, target_time, source_manifest):
    cases = _original_prepare(runtime, source_runtime, "80", source_time, target_time, source_manifest)
    if source_runtime == impl.SOURCE_RUNTIME and abs(source_time - 79.995) < 1e-12:
        for case in cases:
            old = case / "80"
            aligned = case / "79.995"
            old.rename(aligned)
            time_file = aligned / "uniform/time"
            text = time_file.read_text(encoding="utf-8")
            text = text.replace("location    \"80/uniform\";", "location    \"79.995/uniform\";")
            text = text.replace("value           79.99999999999973;", "value           79.995;")
            text = text.replace('name            "80";', 'name            "79.995";')
            text = text.replace("index           16000;", "index           15999;")
            time_file.write_text(text, encoding="utf-8")
    return cases


impl.prepare_cases = prepare_cases_time_aligned


if __name__ == "__main__":
    raise SystemExit(impl.main())
