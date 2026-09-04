"""Fresh authorized retry after Stage209's zero-commit restart-clock failure.

Stage209 is read-only and is never resumed.  This entry reuses only the
accepted step639 source reconstruction and applies the verified restart-clock
staging check before any WSL/OpenFOAM process can launch.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_long_window_v1 import run_authorized_long_window_001 as prior


STAGE_ID = "stage4f_d_cpp_worker_long_window_v1"
RUN_ID = "cpp_worker_long_window_002"
CASE_ID = "cpp_worker_long_window_case_002"
RUNTIME = PROJECT / "runtime/cpp_worker_long_window_v1/long_window_002"
RESULTS = PROJECT / "results/210_cpp_worker_long_window_v1_retry1"
DOCS = PROJECT / "docs/210_cpp_worker_long_window_v1_retry1"

# The helper functions in entry 001 intentionally obtain their values from
# module globals.  Rebind them to this fresh attempt before injecting them
# into the shared bounded executor.
prior.STAGE_ID = STAGE_ID
prior.RUN_ID = RUN_ID
prior.CASE_ID = CASE_ID
prior.RUNTIME = RUNTIME
prior.RESULTS = RESULTS
prior.DOCS = DOCS

confirm = prior.confirm
confirm.STAGE_ID = STAGE_ID
confirm.RUN_ID = RUN_ID
confirm.CASE_ID = CASE_ID
confirm.RUNTIME = RUNTIME
confirm.RESULTS = RESULTS
confirm.DOCS = DOCS
confirm.GATE_ID = "STAGE4F_D_CPP_WORKER_LONG_WINDOW_V1_RETRY1_GATE"
confirm.GATE_FILENAME = "stage4f_d_cpp_worker_long_window_v1_retry1_gate.json"
confirm._prepare_fresh_case_destination = prior._prepare_fresh_case_destination
confirm._post_success_retention = prior._post_success_retention


if __name__ == "__main__":
    raise SystemExit(confirm.main())
