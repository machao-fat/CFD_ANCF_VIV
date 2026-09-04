"""Fresh Stage 302 retry with protocol-safe short identities."""
from __future__ import annotations

import importlib.util
from pathlib import Path

BASE_PATH = Path(__file__).with_name("run_stage300_cpp_worker_precice_three_slice_to150s_observed.py")
SPEC = importlib.util.spec_from_file_location("stage300_base_stage302", BASE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("observed launcher module unavailable")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

BASE.RUNTIME = BASE.ROOT / "runtime/302_cpp_worker_precice_three_slice_continue150s_observed_v1"
BASE.LOGS = BASE.RUNTIME / "logs"
BASE.RESULTS = BASE.ROOT / "results/302_cpp_worker_precice_three_slice_continue150s_observed_v1"
# Kernel protocol IDs are fixed at 64 bytes including the NUL terminator.
BASE.RUN_ID = "s302_cw3_cont125_275_obs_v1"
BASE.CASE_ID = "c302_cw3_cont125_275_obs_v1"
BASE.SOURCE_RUNTIME = BASE.ROOT / "runtime/298_cpp_worker_precice_three_slice_to125s_v1"
BASE.SOURCE_STATE = BASE.SOURCE_RUNTIME / "logs/structure_participant.json"
BASE.SOURCE_STEP = 25000
BASE.SOURCE_TIME = 125.0
BASE.STEPS = 30000
BASE.TARGET_STEP = BASE.SOURCE_STEP + BASE.STEPS
BASE.TARGET_TIME = BASE.SOURCE_TIME + BASE.STEPS * BASE.DT


if __name__ == "__main__":
    raise SystemExit(BASE.main())
