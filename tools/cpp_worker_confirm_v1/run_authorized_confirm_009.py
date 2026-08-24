"""Fresh bounded-confirm entry point prepared after numerical validation.

This module only binds fresh identities and destinations.  It must be invoked
only after a new explicit real-confirm authorization; importing it starts no
MATLAB, OpenFOAM, WSL, CFD, or worker process.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as confirm

confirm.STAGE_ID = "stage4f_d_cpp_worker_persistent_ipc_confirm_v9"
confirm.RUN_ID = "cpp_worker_persistent_ipc_confirm_009"
confirm.CASE_ID = "cpp_worker_persistent_ipc_confirm_case_009"
confirm.RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/confirm_009"
confirm.RESULTS = PROJECT / "results/146_cpp_worker_persistent_ipc_confirm_v9"
confirm.DOCS = PROJECT / "docs/146_cpp_worker_persistent_ipc_confirm_v9"
confirm.LIBRARY = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_006/lib/libancfFileMotion.so"
confirm.WORKER_EXE = PROJECT / "runtime/cpp_worker_numerical_equivalence_before_cfd_v1/build_mass_matrix_001/cfd_ancf_ancf_kernel_worker.exe"


if __name__ == "__main__":
    raise SystemExit(confirm.main())
