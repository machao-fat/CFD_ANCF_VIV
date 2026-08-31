"""Fresh retry of the Stage348 time-aligned smoke/continuation chain.

Stage348 is preserved as failed evidence. This wrapper only changes identity
and runtime paths; the physical contract and corrected launcher are shared.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/stage348_restart_field_time_v1/run_stage348.py"
spec = importlib.util.spec_from_file_location("stage348_impl", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load Stage348 launcher")
stage348 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage348)

impl = stage348.impl
impl.SMOKE_RUNTIME = ROOT / "runtime/stage349_restart_field_time_retry_v1_smoke"
impl.SMOKE_RESULTS = ROOT / "results/349_restart_field_time_retry_v1_smoke"
impl.CONT_RUNTIME = ROOT / "runtime/stage349_restart_field_time_retry_v1_continuation"
impl.CONT_RESULTS = ROOT / "results/349_restart_field_time_retry_v1_continuation"
impl.SMOKE_RUN_ID = "run349_restart_field_time_retry_v1_smoke"
impl.SMOKE_CASE_ID = "case349_restart_field_time_retry_v1_smoke"
impl.CONT_RUN_ID = "run349_restart_field_time_retry_v1_continuation"
impl.CONT_CASE_ID = "case349_restart_field_time_retry_v1_continuation"


if __name__ == "__main__":
    raise SystemExit(impl.main())
