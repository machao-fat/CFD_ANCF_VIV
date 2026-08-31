"""Stage347 fresh lag-1 restart smoke followed by gated continuation."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/stage346_restart_bootstrap_real_v1/run_stage346.py"
spec = importlib.util.spec_from_file_location("stage346_impl", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load stage346 launcher implementation")
impl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(impl)

# All identities and paths are fresh. Stage346 failed evidence is untouched.
impl.BOOTSTRAP_STATE = ROOT / "results/347_restart_bootstrap_lag1_v1/restart_bootstrap_state.json"
impl.SMOKE_RUNTIME = ROOT / "runtime/stage347_restart_bootstrap_lag1_smoke_v1"
impl.SMOKE_RESULTS = ROOT / "results/347_restart_bootstrap_lag1_smoke_v1"
impl.CONT_RUNTIME = ROOT / "runtime/stage347_restart_bootstrap_lag1_continuation_v1"
impl.CONT_RESULTS = ROOT / "results/347_restart_bootstrap_lag1_continuation_v1"
impl.SMOKE_RUN_ID = "run347_restart_bootstrap_lag1_smoke_v1"
impl.SMOKE_CASE_ID = "case347_restart_bootstrap_lag1_smoke_v1"
impl.CONT_RUN_ID = "run347_restart_bootstrap_lag1_continuation_v1"
impl.CONT_CASE_ID = "case347_restart_bootstrap_lag1_continuation_v1"

if __name__ == "__main__":
    raise SystemExit(impl.main())
