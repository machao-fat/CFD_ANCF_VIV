"""Prepared, not auto-started, fresh attempt after Stage215's zero-step failure."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as confirm
from tools.cpp_worker_to30s_v1.restart_template import prepare_fresh_case

STAGE_ID = "stage4f_d_cpp_worker_to30s_v1"
RUN_ID = "cpp_worker_to30s_002"
CASE_ID = "cpp_worker_to30s_case_002"
SOURCE_STEP = 3593
SOURCE_TIME_S = 6.0
SOURCE_TICK = 6_000_000_000
AUTHORIZED_STEPS = 19_200
DT_S = 0.00125
TARGET_STEP = 22_793
TARGET_TIME_S = 30.0
TARGET_TICK = 30_000_000_000
KEEP_FULL_STEPS = 40
SOURCE = PROJECT / "runtime/cpp_worker_to6s_v1/to6s_001/checkpoint/checkpoint_00003593.json"
TEMPLATE_ROOT = PROJECT / "runtime/cpp_worker_to6s_v1/to6s_001/cases"
RUNTIME = PROJECT / "runtime/cpp_worker_to30s_v1/to30s_002"
RESULTS = PROJECT / "results/216_cpp_worker_to30s_v1_retry1"
DOCS = PROJECT / "docs/216_cpp_worker_to30s_v1_retry1"


def _prepare(destination: Path, *, slice_id: int) -> None:
    prepare_fresh_case(destination=destination, expected_destination=RUNTIME / "cases" / f"slice_{slice_id:04d}",
                       slice_id=slice_id, run_id=RUN_ID, case_id=CASE_ID, stage_id=STAGE_ID)


confirm.STAGE_ID = STAGE_ID
confirm.RUN_ID = RUN_ID
confirm.CASE_ID = CASE_ID
confirm.SOURCE = SOURCE
confirm.SOURCE_SHA256 = "01ed80751d2135e55fd80619faf97306ff32a3d0513c78141d22298f8d949ff0"
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
confirm.SPARSE_RETENTION = True
confirm.SPARSE_KEEP_FULL_STEPS = KEEP_FULL_STEPS
confirm.GATE_ID = "STAGE4F_D_CPP_WORKER_TO30S_V1_RETRY1_GATE"
confirm.GATE_FILENAME = "stage4f_d_cpp_worker_to30s_v1_retry1_gate.json"
confirm._prepare_fresh_case_destination = _prepare


if __name__ == "__main__":
    raise SystemExit(confirm.main())
