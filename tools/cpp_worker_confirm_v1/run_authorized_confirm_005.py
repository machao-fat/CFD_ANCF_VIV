"""One-shot wrapper for the explicitly authorized fresh C++ confirm."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as confirm
confirm.STAGE_ID = "stage4f_d_cpp_worker_persistent_ipc_confirm_v6"
confirm.RUN_ID = "cpp_worker_persistent_ipc_confirm_006"
confirm.CASE_ID = "cpp_worker_persistent_ipc_confirm_case_006"
confirm.RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/confirm_006"
confirm.RESULTS = PROJECT / "results/124_cpp_worker_persistent_ipc_confirm_v6"
confirm.DOCS = PROJECT / "docs/124_cpp_worker_persistent_ipc_confirm_v6"
confirm.LIBRARY = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_006/lib/libancfFileMotion.so"


if __name__ == "__main__":
    raise SystemExit(confirm.main())
