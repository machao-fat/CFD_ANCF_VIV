"""Run the explicitly authorized Stage211 continuation from 3.3075 s to 6.0 s."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_long_window_v1 import run_authorized_long_window_001 as prior

STAGE_ID = "stage4f_d_cpp_worker_to6s_v1"
RUN_ID = "cpp_worker_to6s_001"
CASE_ID = "cpp_worker_to6s_case_001"
SOURCE_STEP = 1439
SOURCE_TIME_S = 3.3075
SOURCE_TICK = 3_307_500_000
AUTHORIZED_STEPS = 2154
DT_S = 0.00125
TARGET_STEP = SOURCE_STEP + AUTHORIZED_STEPS
TARGET_TIME_S = SOURCE_TIME_S + AUTHORIZED_STEPS * DT_S
TARGET_TICK = SOURCE_TICK + AUTHORIZED_STEPS * 1_250_000
KEEP_FULL_STEPS = 40
KEEP_FROM_STEP = TARGET_STEP - KEEP_FULL_STEPS + 1
KEEP_FROM_TIME_S = SOURCE_TIME_S + (KEEP_FROM_STEP - SOURCE_STEP) * DT_S

SOURCE = PROJECT / "runtime/cpp_worker_to6s_v1/source_derivation_1439/continuation_source_step00001439_v1.json"
TEMPLATE_ROOT = PROJECT / "runtime/cpp_worker_long_window_v1/long_window_003/cases"
RUNTIME = PROJECT / "runtime/cpp_worker_to6s_v1/to6s_001"
RESULTS = PROJECT / "results/214_cpp_worker_to6s_v1"
DOCS = PROJECT / "docs/214_cpp_worker_to6s_v1"

prior.STAGE_ID = STAGE_ID
prior.RUN_ID = RUN_ID
prior.CASE_ID = CASE_ID
prior.SOURCE_STEP = SOURCE_STEP
prior.SOURCE_TIME_S = SOURCE_TIME_S
prior.SOURCE_TICK = SOURCE_TICK
prior.AUTHORIZED_STEPS = AUTHORIZED_STEPS
prior.TARGET_STEP = TARGET_STEP
prior.TARGET_TIME_S = TARGET_TIME_S
prior.TARGET_TICK = TARGET_TICK
prior.KEEP_FULL_STEPS = KEEP_FULL_STEPS
prior.KEEP_FROM_STEP = KEEP_FROM_STEP
prior.KEEP_FROM_TIME_S = KEEP_FROM_TIME_S
prior.SOURCE = SOURCE
prior.SOURCE_SHA256 = "ecaab0aeb53931ca298bb1f5a28d19cada7d76c470fa56b7a974ad2b9def545d"
prior.TEMPLATE_ROOT = TEMPLATE_ROOT
prior.RUNTIME = RUNTIME
prior.RESULTS = RESULTS
prior.DOCS = DOCS

confirm = prior.confirm
confirm.STAGE_ID = STAGE_ID
confirm.RUN_ID = RUN_ID
confirm.CASE_ID = CASE_ID
confirm.SOURCE = SOURCE
confirm.SOURCE_SHA256 = prior.SOURCE_SHA256
confirm.TEMPLATE_ROOT = TEMPLATE_ROOT
confirm.RUNTIME = RUNTIME
confirm.RESULTS = RESULTS
confirm.DOCS = DOCS
confirm.SOURCE_GLOBAL_STEP = SOURCE_STEP
confirm.SOURCE_TIME_S = SOURCE_TIME_S
confirm.SOURCE_TICK = SOURCE_TICK
confirm.AUTHORIZED_STEPS = AUTHORIZED_STEPS
confirm.TARGET_FINAL_STEP = TARGET_STEP
confirm.TARGET_FINAL_TIME_S = TARGET_TIME_S
confirm.TARGET_FINAL_TICK = TARGET_TICK
confirm.GATE_ID = "STAGE4F_D_CPP_WORKER_TO6S_V1_GATE"
confirm.GATE_FILENAME = "stage4f_d_cpp_worker_to6s_v1_gate.json"
confirm._prepare_fresh_case_destination = prior._prepare_fresh_case_destination
confirm._post_success_retention = prior._post_success_retention


if __name__ == "__main__":
    raise SystemExit(confirm.main())
