"""Prepare a restart candidate without stale derived flux fields."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime/stage358_restart_saved_time_alignment_v1_fresh"
RUNTIME = ROOT / "runtime/stage360_restart_derived_flux_repair_v1_fresh"
RESULTS = ROOT / "results/360_restart_derived_flux_repair_v1"
SAVED_TIME = "79.995"
REMOVED_DERIVED = ("phi", "meshPhi", "Uf")


def main() -> int:
    source_report = json.loads((ROOT / "results/358_restart_saved_time_alignment_v1/restart_saved_time_alignment.json").read_text(encoding="utf-8"))
    if source_report.get("saved_time_s") != 79.995 or source_report.get("field_directory") != SAVED_TIME:
        raise RuntimeError("Stage358 source is not the expected saved-time candidate")
    if RUNTIME.exists() and any(RUNTIME.iterdir()):
        raise RuntimeError(f"refusing to reuse non-empty runtime: {RUNTIME}")
    removed = []
    for index in range(3):
        src = SOURCE / f"slice_{index:04d}"
        dst = RUNTIME / f"slice_{index:04d}"
        shutil.copytree(src, dst)
        field = dst / SAVED_TIME
        for name in REMOVED_DERIVED:
            path = field / name
            if path.exists():
                path.unlink()
                removed.append(f"slice_{index:04d}/{SAVED_TIME}/{name}")
        control = dst / "system" / "controlDict"
        text = control.read_text(encoding="utf-8")
        text = text.replace("startFrom       latestTime;", "startFrom       latestTime;")
        text = text.replace("startTime       79.995;", "startTime       79.995;")
        text = text.replace("endTime         80.195;", "endTime         80.195;")
        control.write_text(text, encoding="utf-8")
    (RUNTIME / "logs").mkdir(parents=True, exist_ok=True)
    initial = SOURCE / "logs" / "initial_state.json"
    shutil.copy2(initial, RUNTIME / "logs" / "initial_state.json")
    report = {
        "schema_version": 1,
        "stage_id": "stage4f_d_restart_derived_flux_repair_v1",
        "source_stage": "stage358_restart_saved_time_alignment_v1",
        "saved_time_s": 79.995,
        "removed_derived_fields": removed,
        "retained_fields": ["U", "p", "pointDisplacement", "cellDisplacement", "Force"],
        "checks": {
            "source_runtime_read_only": True,
            "removed_three_derived_fields_per_slice": len(removed) == 9,
            "state_field_clock_equal": True,
            "matlab_starts": 0,
            "openfoam_starts": 0,
            "wsl_starts": 0,
            "cfd_starts": 0,
            "owned_residual": 0,
        },
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "restart_derived_flux_repair.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    gate = dict(report, gate_id="STAGE4F_D_RESTART_DERIVED_FLUX_REPAIR_V1_GATE", status="pass",
                next_action="request one fresh Smoke; no continuation")
    (RESULTS / "stage4f_d_restart_derived_flux_repair_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": "pass", "removed": len(removed), "external_starts": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
