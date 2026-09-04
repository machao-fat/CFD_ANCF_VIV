"""Offline preflight for the repaired fresh t=0 template."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT)); sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_fresh_t0_v1 import run_authorized_fresh_t0_repair_002 as launch
from tools.cpp_worker_fresh_t0_v1 import prepare_fresh_t0_real_launch_v1 as base

base.launch = launch
base.RESULTS = PROJECT / "results/248_cpp_worker_fresh_t0_repair_preflight_v1"
base.DOCS = PROJECT / "docs/248_cpp_worker_fresh_t0_repair_preflight_v1"

if __name__ == "__main__":
    raise SystemExit(base.main())
