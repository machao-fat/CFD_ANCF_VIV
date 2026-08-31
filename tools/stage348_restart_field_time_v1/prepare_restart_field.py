"""Offline helper for materializing the saved field at its actual CFD time."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime/stage341_dt005_long_convergence_v1"
OUT = ROOT / "results/348_restart_field_time_v1"


def main() -> int:
    checks = []
    for index in range(3):
        source = SOURCE / f"slice_{index:04d}/80/uniform/time"
        text = source.read_text(encoding="utf-8")
        checks.append("value           79.99999999999973;" in text and 'name            "80";' in text)
    report = {
        "schema_version": 1,
        "stage_id": "stage4f_d_restart_field_time_v1",
        "source_stage": "stage341_dt005_long_convergence_v1",
        "source_directory": "80",
        "source_uniform_time_value_s": 79.99999999999973,
        "matching_mapping_step": 15999,
        "matching_mapping_time_s": 79.995,
        "required_materialized_directory": "79.995",
        "required_uniform_time_value_s": 79.995,
        "required_uniform_time_index": 15999,
        "checks": {
            "source_uniform_time_metadata_present": all(checks),
            "source_runtime_read_only": True,
            "matlab_starts": 0,
            "openfoam_starts": 0,
            "wsl_starts": 0,
            "cfd_starts": 0,
            "owned_residual": 0,
        },
        "action": "copy source 80 fields to a fresh runtime directory named 79.995; patch only uniform/time metadata; start OpenFOAM at 79.995 with source global step 15999",
        "status": "offline_preparation_only",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "restart_field_time_preparation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate = dict(report, gate_id="STAGE4F_D_RESTART_FIELD_TIME_PREPARATION_V1_GATE", status="pass" if all(checks) else "do_not_pass")
    (OUT / "stage4f_d_restart_field_time_preparation_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "source_value_s": report["source_uniform_time_value_s"], "required_time_s": report["required_uniform_time_value_s"]}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
