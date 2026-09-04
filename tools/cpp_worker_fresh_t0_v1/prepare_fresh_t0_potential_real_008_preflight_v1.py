"""Offline preflight for fresh t=0 run 008 (potential flow + Bernoulli p).

This wrapper binds the existing immutable checklist to a new run/case and to
the meshfix9 template, then adds finite/consistent checks for the nonuniform
potential velocity and Bernoulli pressure fields.  It never starts a worker,
WSL, OpenFOAM, or CFD.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from tools.cpp_worker_fresh_t0_v1 import run_authorized_fresh_t0_001 as launch
from tools.cpp_worker_fresh_t0_v1 import prepare_fresh_t0_real_launch_v1 as base

TEMPLATE_ROOT = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v3/run_20260827_meshfix9/cases"
RUN_ID = "cpp_worker_fresh_t0_real_008"
CASE_ID = "cpp_worker_fresh_t0_real_case_008"
RUNTIME = PROJECT / "runtime/cpp_worker_fresh_t0_v1/real_run_008"
RESULTS = PROJECT / "results/255_cpp_worker_fresh_potential_real_preflight_v1"
DOCS = PROJECT / "docs/255_cpp_worker_fresh_potential_real_preflight_v1"

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


def _nonuniform_vector_ok(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"internalField\s+nonuniform\s+List<vector>\s+(\d+)\s*\((.*?)\)\s*;", text, re.S)
    if not match:
        return False
    values = re.findall(r"\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", match.group(2))
    if int(match.group(1)) != len(values) or not values:
        return False
    return all(all(math.isfinite(float(item)) for item in row) for row in values)


def _nonuniform_scalar_ok(path: Path, *, min_value: float, max_value: float) -> bool:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"internalField\s+nonuniform\s+List<scalar>\s+(\d+)\s*\((.*?)\)\s*;", text, re.S)
    if not match:
        return False
    values = [float(item) for item in re.findall(r"[-+0-9.eE]+", match.group(2))]
    if int(match.group(1)) != len(values) or not values:
        return False
    return all(math.isfinite(item) and min_value <= item <= max_value for item in values)


def main() -> int:
    rc = base.main()
    audit_path = RESULTS / "fresh_t0_real_launch_preflight.json"
    evidence = json.loads(audit_path.read_text(encoding="utf-8"))
    velocity_ok = {str(sid): _nonuniform_vector_ok(TEMPLATE_ROOT / f"slice_{sid:04d}" / "0/U") for sid in range(3)}
    pressure_ok = {str(sid): _nonuniform_scalar_ok(
        TEMPLATE_ROOT / f"slice_{sid:04d}" / "0/p", min_value=-2.0, max_value=0.6) for sid in range(3)}
    evidence["checks"]["potential_flow_internal_fields"] = all(velocity_ok.values())
    evidence["checks"]["bernoulli_pressure_fields"] = all(pressure_ok.values())
    evidence["potential_flow_internal_fields"] = velocity_ok
    evidence["bernoulli_pressure_fields"] = pressure_ok
    payload = (json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    audit_path.write_bytes(payload)
    (RESULTS / "stage4f_d_cpp_worker_fresh_t0_real_preflight_v1_gate.json").write_bytes(payload)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "fresh_potential_real_preflight_report.md").write_text(
        "# Fresh t=0 run 008 preflight (potential flow + Bernoulli p)\n\n"
        "Offline checklist only; no real process was started.\n\n"
        f"- Base gate: `{evidence['gate']}`\n"
        "- Three slices use finite nonuniform potential velocity and Bernoulli pressure.\n",
        encoding="utf-8")
    print(json.dumps({"gate": evidence["gate"], "checks": evidence["checks"],
                      "launch_performed": False}, ensure_ascii=True, sort_keys=True))
    return 0 if rc == 0 and all(evidence["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
