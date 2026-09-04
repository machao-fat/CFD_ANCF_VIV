"""Fresh t=0 40-step real launch (run 008) using meshfix9 templates.

One-shot bounded entry: source step 0 -> 40, dt=0.00125, three slices.  It
refuses to start without the explicit real authorization switch and refuses
to reuse any existing runtime/results artifact.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_fresh_t0_v1 import run_authorized_fresh_t0_001 as prior

STAGE_ID = "stage4f_d_cpp_worker_fresh_t0_v1"
RUN_ID = "cpp_worker_fresh_t0_real_008"
CASE_ID = "cpp_worker_fresh_t0_real_case_008"
TEMPLATE_ROOT = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix9/cases"
RUNTIME = PROJECT / "runtime/cpp_worker_fresh_t0_v1/real_run_008"
RESULTS = PROJECT / "results/256_cpp_worker_fresh_potential_real_v1"
DOCS = PROJECT / "docs/256_cpp_worker_fresh_potential_real_v1"
PREFLIGHT_AUDIT = PROJECT / "results/255_cpp_worker_fresh_potential_real_preflight_v1/fresh_t0_real_launch_preflight.json"

for name, value in {
    "STAGE_ID": STAGE_ID, "RUN_ID": RUN_ID, "CASE_ID": CASE_ID,
    "TEMPLATE_ROOT": TEMPLATE_ROOT, "RUNTIME": RUNTIME, "RESULTS": RESULTS,
    "DOCS": DOCS, "PREFLIGHT_AUDIT": PREFLIGHT_AUDIT,
}.items():
    setattr(prior, name, value)
    setattr(prior.confirm, name, value)

for name in ("PROJECT", "SOURCE", "SOURCE_SHA256", "WORKER_EXE", "LIBRARY",
             "EXPECTED_LIBRARY_SHA256", "EXPECTED_MODEL_CONTRACT_SHA256",
             "SOURCE_GLOBAL_STEP", "SOURCE_TIME_S", "SOURCE_TICK",
             "AUTHORIZED_STEPS", "TARGET_FINAL_STEP", "TARGET_FINAL_TIME_S",
             "TARGET_FINAL_TICK"):
    globals()[name] = getattr(prior, name)

prior.confirm.SOURCE_GLOBAL_STEP = 0
prior.confirm.SOURCE_TIME_S = 0.0
prior.confirm.SOURCE_TICK = 0
prior.confirm.AUTHORIZED_STEPS = 40
prior.confirm.TARGET_FINAL_STEP = 40
prior.confirm.TARGET_FINAL_TIME_S = 0.05
prior.confirm.TARGET_FINAL_TICK = 50_000_000
prior.confirm.GATE_ID = "STAGE4F_D_CPP_WORKER_FRESH_POTENTIAL_REAL_V1_GATE"
prior.confirm.GATE_FILENAME = "stage4f_d_cpp_worker_fresh_potential_real_v1_gate.json"
prior.confirm.SPARSE_RETENTION = False


def main() -> int:
    return prior.main()


if __name__ == "__main__":
    raise SystemExit(main())
