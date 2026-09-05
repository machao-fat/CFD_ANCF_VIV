#!/usr/bin/env python3
"""Read-only run_008 PIMPLE residual audit; writes new derived evidence only."""
from __future__ import annotations

import json
from pathlib import Path

from coupling.openfoam_numerical_quality_contract_v2 import audit_log


ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "runtime" / "stage_force_contract_smoke_v1_run_008" / "logs" / "fluid_0000.stdout"
FVSOLUTION = ROOT / "runtime" / "stage_force_contract_smoke_v1_run_008" / "cases" / "slice_0000" / "system" / "fvSolution"
OUT = ROOT / "results" / "numerical_quality_evidence_closure_v1" / "run_008_residual_audit.json"


def main() -> int:
    value = audit_log(LOG, FVSOLUTION)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
