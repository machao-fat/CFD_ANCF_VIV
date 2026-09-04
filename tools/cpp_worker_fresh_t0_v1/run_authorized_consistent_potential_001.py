"""One-shot 40-step launcher bound to the consistent fresh t=0 template."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT)); sys.path.insert(0, str(PROJECT / "src"))
from tools.cpp_worker_fresh_t0_v1 import run_authorized_fresh_t0_001 as prior

STAGE_ID = "stage4f_d_cpp_worker_fresh_t0_v1"
RUN_ID = "cpp_worker_fresh_t0_consistent_real_001"
CASE_ID = "cpp_worker_fresh_t0_consistent_real_case_001"
TEMPLATE_ROOT = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix11/cases"
RUNTIME = PROJECT / "runtime/cpp_worker_fresh_t0_v1/consistent_real_run_001"
RESULTS = PROJECT / "results/259_cpp_worker_fresh_consistent_potential_real_v1"
DOCS = PROJECT / "docs/259_cpp_worker_fresh_consistent_potential_real_v1"
PREFLIGHT_AUDIT = PROJECT / "results/258_cpp_worker_fresh_consistent_potential_preflight_v1/fresh_t0_real_launch_preflight.json"

for name, value in {"STAGE_ID": STAGE_ID, "RUN_ID": RUN_ID, "CASE_ID": CASE_ID,
                    "TEMPLATE_ROOT": TEMPLATE_ROOT, "RUNTIME": RUNTIME,
                    "RESULTS": RESULTS, "DOCS": DOCS, "PREFLIGHT_AUDIT": PREFLIGHT_AUDIT}.items():
    setattr(prior, name, value); setattr(prior.confirm, name, value)

prior.confirm.GATE_ID = "STAGE4F_D_CPP_WORKER_FRESH_CONSISTENT_POTENTIAL_REAL_V1_GATE"
prior.confirm.GATE_FILENAME = "stage4f_d_cpp_worker_fresh_consistent_potential_real_v1_gate.json"


def _require_preflight() -> None:
    path = PREFLIGHT_AUDIT
    if not path.is_file():
        raise RuntimeError("consistent potential preflight is missing")
    import json
    audit = json.loads(path.read_text(encoding="utf-8"))
    if audit.get("gate") != "STAGE4F_D_CPP_WORKER_FRESH_CONSISTENT_POTENTIAL_PREFLIGHT_V1_GATE: pass":
        raise RuntimeError("consistent potential preflight did not pass fail-closed")
    if audit.get("case_id") != "cpp_worker_fresh_consistent_potential_preflight_case_001":
        raise RuntimeError("consistent potential preflight case identity mismatch")
    if audit.get("launch_performed") is not False or any(audit.get("real_process_starts", {}).values()):
        raise RuntimeError("consistent potential preflight contains unexpected process starts")
    if not audit.get("checks", {}).get("consistent_u_p_phi", False):
        raise RuntimeError("consistent U/p/phi check is missing")


prior._require_preflight = _require_preflight


def main() -> int:
    return prior.main()


if __name__ == "__main__":
    raise SystemExit(main())
