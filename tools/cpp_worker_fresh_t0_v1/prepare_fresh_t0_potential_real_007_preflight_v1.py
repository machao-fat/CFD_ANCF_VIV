"""Offline preflight for fresh t=0 run 007 with the potential-flow template.

This wrapper binds the existing immutable checklist to a new run/case and to
the potential-flow template.  It never starts a worker, WSL, OpenFOAM, or CFD.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_fresh_t0_v1 import run_authorized_fresh_t0_001 as launch
from tools.cpp_worker_fresh_t0_v1 import prepare_fresh_t0_real_launch_v1 as base

TEMPLATE_ROOT = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix8/cases"
RUN_ID = "cpp_worker_fresh_t0_real_007"
CASE_ID = "cpp_worker_fresh_t0_real_case_007"
RUNTIME = PROJECT / "runtime/cpp_worker_fresh_t0_v1/real_run_007"
RESULTS = PROJECT / "results/254_cpp_worker_fresh_potential_real_preflight_v1"
DOCS = PROJECT / "docs/254_cpp_worker_fresh_potential_real_preflight_v1"

for target in (launch, launch.confirm):
    target.RUN_ID = RUN_ID
    target.CASE_ID = CASE_ID
    target.TEMPLATE_ROOT = TEMPLATE_ROOT
    target.RUNTIME = RUNTIME
    target.RESULTS = RESULTS
    target.DOCS = DOCS

base.launch = launch
base.RESULTS = RESULTS
base.DOCS = DOCS


if __name__ == "__main__":
    raise SystemExit(base.main())
