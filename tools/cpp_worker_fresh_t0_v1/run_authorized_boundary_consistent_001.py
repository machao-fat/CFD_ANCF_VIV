"""Bounded 40-step launcher for the boundary-consistent fresh template.

The launcher is inert unless called with ``--authorize-real``.  It is bound
to a new runtime and the Stage 265 preflight; failed historical runtimes are
never reused.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT)); sys.path.insert(0, str(PROJECT / "src"))
from tools.cpp_worker_fresh_t0_v1 import run_authorized_fresh_t0_001 as prior
from tools.cpp_worker_fresh_t0_v1 import prepare_boundary_consistent_template_v1 as repair

# The immutable contract admits fresh t=0 only under this fixed stage id.
STAGE_ID = "stage4f_d_cpp_worker_fresh_t0_v1"
RUN_ID = "cpp_worker_fresh_boundary_consistency_real_001"
CASE_ID = "cpp_worker_fresh_boundary_consistency_real_case_001"
TEMPLATE_ROOT = repair.DEST
RUNTIME = PROJECT / "runtime/cpp_worker_fresh_t0_v1/boundary_consistent_real_001"
RESULTS = PROJECT / "results/266_cpp_worker_fresh_boundary_consistency_real_v1"
DOCS = PROJECT / "docs/266_cpp_worker_fresh_boundary_consistency_real_v1"
PREFLIGHT_AUDIT = PROJECT / "results/263_cpp_worker_fresh_boundary_consistency_preflight_v1/boundary_consistency_preflight.json"

for name, value in {"STAGE_ID": STAGE_ID, "RUN_ID": RUN_ID, "CASE_ID": CASE_ID,
                    "TEMPLATE_ROOT": TEMPLATE_ROOT, "RUNTIME": RUNTIME,
                    "RESULTS": RESULTS, "DOCS": DOCS, "PREFLIGHT_AUDIT": PREFLIGHT_AUDIT}.items():
    setattr(prior, name, value); setattr(prior.confirm, name, value)
prior.confirm.GATE_ID = "STAGE4F_D_CPP_WORKER_FRESH_BOUNDARY_CONSISTENCY_REAL_V1_GATE"
prior.confirm.GATE_FILENAME = "stage4f_d_cpp_worker_fresh_boundary_consistency_real_v1_gate.json"


def _require_preflight() -> None:
    if not PREFLIGHT_AUDIT.is_file():
        raise RuntimeError("boundary-consistency preflight is missing")
    audit = json.loads(PREFLIGHT_AUDIT.read_text(encoding="utf-8"))
    if audit.get("gate") != "STAGE4F_D_CPP_WORKER_FRESH_BOUNDARY_CONSISTENCY_PREFLIGHT_V1_GATE: pass":
        raise RuntimeError("boundary-consistency preflight did not pass fail-closed")
    if audit.get("launch_performed") is not False or any(audit.get("real_process_starts", {}).values()):
        raise RuntimeError("preflight contains unexpected process starts")
    if audit.get("template_root") != str(TEMPLATE_ROOT) or audit.get("case_id") != "cpp_worker_fresh_boundary_consistency_preflight_case_001":
        raise RuntimeError("preflight identity mismatch")
    if not all(audit.get("checks", {}).values()):
        raise RuntimeError("preflight checks are incomplete")


def main() -> int:
    if sys.argv[1:] != ["--authorize-real"]:
        print("refusing to start: pass --authorize-real only after a new explicit real-CFD authorization", file=sys.stderr)
        return 2
    _require_preflight()
    return prior.main()


# The shared bounded launcher resolves its preflight hook in its own module;
# replace that hook so this entry cannot fall back to the historical template.
prior._require_preflight = _require_preflight


if __name__ == "__main__":
    raise SystemExit(main())
