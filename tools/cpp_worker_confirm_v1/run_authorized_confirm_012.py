"""Fresh explicitly authorized bounded C++/persistent-IPC confirm (stage196)."""
from __future__ import annotations
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as confirm

confirm.STAGE_ID = "stage4f_d_cpp_worker_persistent_ipc_confirm_v12"
confirm.RUN_ID = "cpp_worker_persistent_ipc_confirm_012"
confirm.CASE_ID = "cpp_worker_persistent_ipc_confirm_case_012"
confirm.RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/confirm_012"
confirm.RESULTS = PROJECT / "results/196_cpp_worker_persistent_ipc_confirm_v12"
confirm.DOCS = PROJECT / "docs/196_cpp_worker_persistent_ipc_confirm_v12"
confirm.LIBRARY = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_006/lib/libancfFileMotion.so"
confirm.WORKER_EXE = PROJECT / "runtime/cpp_worker_comprehensive_audit_repair_v1_continuation/build_release_003/cfd_ancf_ancf_kernel_worker.exe"

if __name__ == "__main__":
    raise SystemExit(confirm.main())
