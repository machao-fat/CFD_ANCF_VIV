"""Run the explicitly authorized cumulative 0->70 s continuation.

The cumulative timeline is represented by the immutable accepted source at
global step 559 (2.2075 s), then advances exactly to step 56000 (70 s).
This wrapper only binds the exact window and fresh Stage 232 artifacts; the
existing fail-closed coordinator remains authoritative for all protocol and
cleanup checks.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_confirm_v1 import run_authorized_confirm_001 as confirm

confirm.STAGE_ID = "stage4f_d_cpp_worker_to70s_v1"
confirm.RUN_ID = "cpp_worker_to70s_real_001"
confirm.CASE_ID = "cpp_worker_to70s_real_case_001"
confirm.RUNTIME = PROJECT / "runtime/cpp_worker_to70s_real_v1/run_001/campaign"
confirm.RESULTS = PROJECT / "results/233_cpp_worker_to70s_real_v1"
confirm.DOCS = PROJECT / "docs/233_cpp_worker_to70s_real_v1"
confirm.SOURCE = PROJECT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
confirm.SOURCE_SHA256 = "341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226"
confirm.MASS_MATRIX_SOURCE = PROJECT / "cases/openfoam/stage4f_c_case_initialization_repair_v1/C/matlab/committed.mat"
confirm.LIBRARY = PROJECT / "runtime/cpp_worker_to70s_build_retry_v11/lib/libancfFileMotion.so"
confirm.EXPECTED_LIBRARY_SHA256 = "39a51c9a01da1ed63a761b4385d8eb954dc201415f7e21aa3ca9f1cb7087bd07"
confirm.WORKER_EXE = PROJECT / "runtime/cpp_worker_to70s_build_retry_v11/cpp_worker_build/cfd_ancf_ancf_kernel_worker.exe"
confirm.TEMPLATE_ROOT = PROJECT / "cases/openfoam/cpp_worker_persistent_ipc_v1/real_confirm_001"
confirm.SOURCE_GLOBAL_STEP = 559
confirm.SOURCE_TIME_S = 2.2075
confirm.SOURCE_TICK = 2_207_500_000
confirm.AUTHORIZED_STEPS = 55_441
confirm.TARGET_FINAL_STEP = 56_000
confirm.TARGET_FINAL_TIME_S = 70.0
confirm.TARGET_FINAL_TICK = 70_000_000_000
confirm.SPARSE_RETENTION = True
confirm.SPARSE_KEEP_FULL_STEPS = 40
confirm.GATE_ID = "STAGE4F_D_CPP_WORKER_TO70S_REAL_V1_GATE"
confirm.GATE_FILENAME = "stage4f_d_cpp_worker_to70s_real_v1_gate.json"
confirm.os.environ["CFD_ANCF_VIV_CPP_FIXTURE"] = str(
    PROJECT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
)

_base_validate_scope = confirm._validate_scope


def _validate_scope_before_launch(contract, manifest):
    """Reject an incomplete restart case before any process is started."""
    _base_validate_scope(contract, manifest)
    required = ("U", "Uf", "meshPhi", "p", "phi")
    for sid in range(3):
        source_time = confirm.TEMPLATE_ROOT / f"slice_{sid:04d}" / f"{confirm.SOURCE_TIME_S:.12g}"
        missing = [name for name in required if not (source_time / name).is_file()]
        if missing:
            raise RuntimeError(
                f"slice {sid} restart source-time fields are missing at {source_time}: {','.join(missing)}"
            )


confirm._validate_scope = _validate_scope_before_launch


if __name__ == "__main__":
    raise SystemExit(confirm.main())
