"""Prepared fresh 6.0 s continuation using the Stage217 precision-fixed bridge."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as confirm
from tools.cpp_worker_to30s_v1.restart_template import prepare_fresh_case

STAGE_ID = "stage4f_d_cpp_worker_to30s_v1"
RUN_ID = "cpp_worker_to30s_003"
CASE_ID = "cpp_worker_to30s_case_003"
SOURCE_STEP, SOURCE_TIME_S, SOURCE_TICK = 3593, 6.0, 6_000_000_000
AUTHORIZED_STEPS, DT_S = 19_200, 0.00125
TARGET_STEP, TARGET_TIME_S, TARGET_TICK = 22_793, 30.0, 30_000_000_000
KEEP_FULL_STEPS = 40
SOURCE = PROJECT / "runtime/cpp_worker_to6s_v1/to6s_001/checkpoint/checkpoint_00003593.json"
TEMPLATE_ROOT = PROJECT / "runtime/cpp_worker_to6s_v1/to6s_001/cases"
LIBRARY = PROJECT / "runtime/cpp_worker_to30s_v1/bridge_precision_build_001/lib/libancfFileMotion.so"
RUNTIME = PROJECT / "runtime/cpp_worker_to30s_v1/to30s_003"
RESULTS = PROJECT / "results/218_cpp_worker_to30s_v1_precision_retry2"
DOCS = PROJECT / "docs/218_cpp_worker_to30s_v1_precision_retry2"


def _prepare(destination: Path, *, slice_id: int) -> None:
    prepare_fresh_case(destination=destination, expected_destination=RUNTIME / "cases" / f"slice_{slice_id:04d}",
                       slice_id=slice_id, run_id=RUN_ID, case_id=CASE_ID, stage_id=STAGE_ID)


confirm.STAGE_ID = STAGE_ID
confirm.RUN_ID = RUN_ID
confirm.CASE_ID = CASE_ID
confirm.SOURCE = SOURCE
confirm.SOURCE_SHA256 = "01ed80751d2135e55fd80619faf97306ff32a3d0513c78141d22298f8d949ff0"
confirm.TEMPLATE_ROOT = TEMPLATE_ROOT
confirm.LIBRARY = LIBRARY
confirm.EXPECTED_LIBRARY_SHA256 = "39a51c9a01da1ed63a761b4385d8eb954dc201415f7e21aa3ca9f1cb7087bd07"
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
confirm.GATE_ID = "STAGE4F_D_CPP_WORKER_TO30S_V1_PRECISION_RETRY2_GATE"
confirm.GATE_FILENAME = "stage4f_d_cpp_worker_to30s_v1_precision_retry2_gate.json"
confirm._prepare_fresh_case_destination = _prepare


if __name__ == "__main__":
    raise SystemExit(confirm.main())
