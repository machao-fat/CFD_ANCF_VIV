"""One-shot bounded confirm_008 under the user's explicit authorization.

This wrapper gives the audited confirm implementation a fresh identity and
fresh destinations.  It does not reuse any prior confirm runtime and never
exposes a MATLAB launch path.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as confirm

confirm.STAGE_ID = "stage4f_d_cpp_worker_persistent_ipc_confirm_v8"
confirm.RUN_ID = "cpp_worker_persistent_ipc_confirm_008"
confirm.CASE_ID = "cpp_worker_persistent_ipc_confirm_case_008"
confirm.RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/confirm_008"
confirm.RESULTS = PROJECT / "results/131_cpp_worker_persistent_ipc_confirm_v8"
confirm.DOCS = PROJECT / "docs/131_cpp_worker_persistent_ipc_confirm_v8"
confirm.LIBRARY = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_006/lib/libancfFileMotion.so"


if __name__ == "__main__":
    raise SystemExit(confirm.main())
