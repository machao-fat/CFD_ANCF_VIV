"""Freeze the only permitted fresh 0.1 s micro-smoke contract."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.generalized_force_metric_v2 import freeze_contract  # noqa: E402

BASE = ROOT / "tools/moving_mesh_patch_consistency_fix_and_1s_retry_v1/moving_mesh_patch_consistency_fix_and_1s_retry_v1_contract.json"
OUT = Path(__file__).with_name("generalized_force_metric_v2_and_0p1s_micro_smoke_v1_contract.json")


def main() -> int:
    value = copy.deepcopy(json.loads(BASE.read_text(encoding="utf-8")))
    value.update({"schema_version": "generalized-force-metric-v2-and-0p1s-micro-smoke-v1",
                  "run_id": "generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001",
                  "case_id": "generalized_force_metric_v2_0p1s_micro_smoke_v1_case_001",
                  "duration_s": 0.1, "number_of_steps": 20,
                  "source_git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  "generalized_force_metric_v2": freeze_contract(float(value["ANCF"]["length_m"]) / int(value["ANCF"]["elements"])),
                  "micro_smoke_evidence": {"mesh_snapshot_times_s": [0.0, 0.05, 0.1],
                                            "purpose": "coupled mapping and moving-mesh/Courant diagnostic only; no VIV or physical-power conclusion"}})
    OUT.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
