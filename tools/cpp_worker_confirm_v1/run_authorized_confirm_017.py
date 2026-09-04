"""Prepared continuation with a fresh motion acknowledgement namespace."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as confirm

confirm.STAGE_ID = "stage4f_d_cpp_worker_persistent_ipc_confirm_v17"
confirm.RUN_ID = "cpp_worker_persistent_ipc_confirm_017"
confirm.CASE_ID = "cpp_worker_persistent_ipc_confirm_case_017"
confirm.RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/confirm_017"
confirm.RESULTS = PROJECT / "results/204_cpp_worker_persistent_ipc_confirm_v17"
confirm.DOCS = PROJECT / "docs/204_cpp_worker_persistent_ipc_confirm_v17"
confirm.SOURCE = PROJECT / "cases/openfoam/cpp_worker_persistent_ipc_v1/continuation_source_step00000599_v1.json"
confirm.SOURCE_SHA256 = "21e308fea2073cc9b1cafcc075262e433bcc36df6100fbe282b184f0236aa995"
confirm.TEMPLATE_ROOT = PROJECT / "cases/openfoam/cpp_worker_persistent_ipc_v1/continuation_template_017"
confirm.LIBRARY = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_006/lib/libancfFileMotion.so"
confirm.WORKER_EXE = PROJECT / "runtime/cpp_worker_comprehensive_audit_repair_v1_continuation/build_release_003/cfd_ancf_ancf_kernel_worker.exe"
confirm.SOURCE_GLOBAL_STEP = 599
confirm.SOURCE_TIME_S = 2.2575
confirm.SOURCE_TICK = 2_257_500_000
confirm.TARGET_FINAL_STEP = 639
confirm.TARGET_FINAL_TIME_S = 2.3075
confirm.TARGET_FINAL_TICK = 2_307_500_000

if __name__ == "__main__":
    raise SystemExit(confirm.main())
