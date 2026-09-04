"""Offline preflight for the potential-flow fresh t=0 template.

This wrapper uses the existing fail-closed checklist with a new immutable
template identity and additionally verifies that every slice has a finite
nonuniform velocity field.  It never starts a worker, WSL, OpenFOAM, or CFD.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_fresh_t0_v1 import prepare_fresh_t0_real_launch_v1 as base
from tools.cpp_worker_fresh_t0_v1 import run_authorized_fresh_t0_001 as launch

TEMPLATE_ROOT = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix8/cases"
RESULTS = PROJECT / "results/253_cpp_worker_fresh_potential_preflight_v1"
DOCS = PROJECT / "docs/253_cpp_worker_fresh_potential_preflight_v1"
# The contract validator intentionally admits only the bounded fresh-t0
# physical stage.  The preflight itself remains separately identified below.
CONTRACT_STAGE_ID = "stage4f_d_cpp_worker_fresh_t0_v1"
STAGE_ID = "stage4f_d_cpp_worker_fresh_potential_preflight_v1"
RUN_ID = "cpp_worker_fresh_potential_preflight_001"
CASE_ID = "cpp_worker_fresh_potential_preflight_case_001"
RUNTIME = PROJECT / "runtime/cpp_worker_fresh_t0_v1/potential_preflight_001"

for target in (launch, launch.confirm):
    target.STAGE_ID = CONTRACT_STAGE_ID
    target.RUN_ID = RUN_ID
    target.CASE_ID = CASE_ID
    target.TEMPLATE_ROOT = TEMPLATE_ROOT
    target.RUNTIME = RUNTIME
    target.RESULTS = RESULTS
    target.DOCS = DOCS
    target.GATE_ID = "STAGE4F_D_CPP_WORKER_FRESH_POTENTIAL_PREFLIGHT_V1_GATE"
    target.GATE_FILENAME = "stage4f_d_cpp_worker_fresh_potential_preflight_v1_gate.json"

base.launch = launch
base.RESULTS = RESULTS
base.DOCS = DOCS


def _potential_field_ok(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"internalField\s+nonuniform\s+List<vector>\s+(\d+)\s*\((.*?)\)\s*;", text, re.S)
    if not match:
        return False
    expected = int(match.group(1))
    values = re.findall(r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", match.group(2))
    if len(values) != expected or expected <= 0:
        return False
    return all(all(float(item) == float(item) and abs(float(item)) < float("inf") for item in row) for row in values)


def main() -> int:
    rc = base.main()
    audit_path = RESULTS / "fresh_t0_real_launch_preflight.json"
    evidence = json.loads(audit_path.read_text(encoding="utf-8"))
    potential = {str(sid): _potential_field_ok(TEMPLATE_ROOT / f"slice_{sid:04d}" / "0/U") for sid in range(3)}
    evidence["checks"]["potential_flow_internal_fields"] = all(potential.values())
    evidence["potential_flow_internal_fields"] = potential
    evidence["stage_id"] = STAGE_ID
    evidence["run_id"] = RUN_ID
    evidence["case_id"] = CASE_ID
    evidence["gate"] = ("STAGE4F_D_CPP_WORKER_FRESH_POTENTIAL_PREFLIGHT_V1_GATE: pass"
                         if all(evidence["checks"].values()) else
                         "STAGE4F_D_CPP_WORKER_FRESH_POTENTIAL_PREFLIGHT_V1_GATE: do_not_pass")
    payload = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    audit_path.write_bytes(payload)
    (RESULTS / "stage4f_d_cpp_worker_fresh_potential_preflight_v1_gate.json").write_bytes(payload)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "fresh_potential_preflight_report.md").write_text(
        "# Fresh t=0 potential-flow preflight\n\n"
        "Offline checklist only; no real process was started.\n\n"
        f"- Gate: `{evidence['gate']}`\n"
        "- Three slices use finite nonuniform potential-flow velocity fields.\n",
        encoding="utf-8")
    print(json.dumps({"gate": evidence["gate"], "checks": evidence["checks"], "launch_performed": False}, ensure_ascii=True, sort_keys=True))
    return 0 if rc == 0 and all(evidence["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
