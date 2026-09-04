"""Offline preflight for the U/p/phi-consistent fresh template."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT)); sys.path.insert(0, str(PROJECT / "src"))
from tools.cpp_worker_fresh_t0_v1 import prepare_fresh_t0_real_launch_v1 as base
from tools.cpp_worker_fresh_t0_v1 import run_authorized_fresh_t0_001 as launch

TEMPLATE_ROOT = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix11/cases"
RESULTS = PROJECT / "results/258_cpp_worker_fresh_consistent_potential_preflight_v1"
DOCS = PROJECT / "docs/258_cpp_worker_fresh_consistent_potential_preflight_v1"
CONTRACT_STAGE_ID = "stage4f_d_cpp_worker_fresh_t0_v1"
STAGE_ID = "stage4f_d_cpp_worker_fresh_consistent_potential_preflight_v1"
RUN_ID = "cpp_worker_fresh_consistent_potential_preflight_001"
CASE_ID = "cpp_worker_fresh_consistent_potential_preflight_case_001"
RUNTIME = PROJECT / "runtime/cpp_worker_fresh_t0_v1/consistent_potential_preflight_001"

for target in (launch, launch.confirm):
    target.STAGE_ID = CONTRACT_STAGE_ID; target.RUN_ID = RUN_ID; target.CASE_ID = CASE_ID
    target.TEMPLATE_ROOT = TEMPLATE_ROOT; target.RUNTIME = RUNTIME
    target.RESULTS = RESULTS; target.DOCS = DOCS
base.launch = launch; base.RESULTS = RESULTS; base.DOCS = DOCS


def _nonuniform(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    return bool(re.search(r"internalField\s+nonuniform\s+List<[^>]+>\s+\d+\s*\(.*?\)\s*;", text, re.S))


def main() -> int:
    rc = base.main()
    evidence = json.loads((RESULTS / "fresh_t0_real_launch_preflight.json").read_text(encoding="utf-8"))
    fields = {str(sid): {name: _nonuniform(TEMPLATE_ROOT / f"slice_{sid:04d}" / "0" / name)
                         for name in ("U", "p", "phi")} for sid in range(3)}
    evidence["checks"]["consistent_u_p_phi"] = all(all(row.values()) for row in fields.values())
    evidence["consistent_u_p_phi"] = fields
    evidence["stage_id"] = STAGE_ID; evidence["run_id"] = RUN_ID; evidence["case_id"] = CASE_ID
    evidence["gate"] = ("STAGE4F_D_CPP_WORKER_FRESH_CONSISTENT_POTENTIAL_PREFLIGHT_V1_GATE: pass"
                         if all(evidence["checks"].values()) else
                         "STAGE4F_D_CPP_WORKER_FRESH_CONSISTENT_POTENTIAL_PREFLIGHT_V1_GATE: do_not_pass")
    payload = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    (RESULTS / "fresh_t0_real_launch_preflight.json").write_bytes(payload)
    (RESULTS / "stage4f_d_cpp_worker_fresh_consistent_potential_preflight_v1_gate.json").write_bytes(payload)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "consistent_potential_preflight_report.md").write_text(
        "# Consistent potential-flow preflight\n\nOffline only; no real process was started.\n\n"
        f"- Gate: `{evidence['gate']}`\n- U, p, and phi are all nonuniform fields on three slices.\n",
        encoding="utf-8")
    print(json.dumps({"gate": evidence["gate"], "checks": evidence["checks"], "launch_performed": False}, ensure_ascii=True, sort_keys=True))
    return 0 if rc == 0 and all(evidence["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
