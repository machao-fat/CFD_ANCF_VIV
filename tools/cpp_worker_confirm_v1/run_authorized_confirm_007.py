"""One-shot entry point for the freshly authorized bounded C++ confirm.

This wrapper deliberately reuses the audited confirm implementation while
assigning a new stage/run/case/runtime/results/docs identity.  It never
reuses a failed confirm runtime and never exposes a MATLAB path.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as confirm

confirm.STAGE_ID = "stage4f_d_cpp_worker_persistent_ipc_confirm_v7"
confirm.RUN_ID = "cpp_worker_persistent_ipc_confirm_007"
confirm.CASE_ID = "cpp_worker_persistent_ipc_confirm_case_007"
confirm.RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/confirm_007"
confirm.RESULTS = PROJECT / "results/126_cpp_worker_persistent_ipc_confirm_v7"
confirm.DOCS = PROJECT / "docs/126_cpp_worker_persistent_ipc_confirm_v7"
confirm.LIBRARY = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_006/lib/libancfFileMotion.so"


if __name__ == "__main__":
    raise SystemExit(confirm.main())
