"""Stage 303 retry 2: fresh runtime after preflight launcher defect."""
from __future__ import annotations

import importlib.util
from pathlib import Path

BASE_PATH = Path(__file__).with_name("run_stage303_fresh_zero_to10s.py")
SPEC = importlib.util.spec_from_file_location("stage303_fresh_base_retry2", BASE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Stage 303 base launcher unavailable")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
BASE.RUNTIME = BASE.ROOT / "runtime/stage303_interface_mapping_repair_v1_fresh_zero_to10s_retry2"
BASE.RESULTS = BASE.ROOT / "results/303_interface_mapping_repair_v1_retry2"
BASE.LOGS = BASE.RUNTIME / "logs"
BASE.RUN_ID = "s303_fresh_zero_to10s_mapping_diag_retry2"
BASE.CASE_ID = "c303_fresh_zero_to10s_mapping_diag_retry2"


if __name__ == "__main__":
    raise SystemExit(BASE.main())
