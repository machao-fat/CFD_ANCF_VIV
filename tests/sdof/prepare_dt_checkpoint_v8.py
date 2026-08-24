"""Prepare branch-local checkpoints from the same synchronized Ur=5.2 state."""

from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "results/04_sdof_corrected_campaign/Ur5p2_v6_retry_to130/sdof_checkpoint.json"
OUT_ROOT = ROOT / "results/04_sdof_corrected_campaign/dt_convergence_v8"


def make_branch(name: str, dt: float, case_name: str) -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8-sig"))
    state = source["state"]
    interface = source["interface_state_used_by_cfd"]
    source_time = float(state["time_s"])
    if not math.isclose(source_time, 130.0, abs_tol=1.0e-10):
        raise ValueError(f"unexpected source checkpoint time: {source_time}")
    if int(state["step"]) != 52000 or int(interface["step"]) != 52000:
        raise ValueError("source checkpoint is not the expected 52,000-step state")
    if not math.isclose(float(interface["time_s"]), source_time, abs_tol=1.0e-10):
        raise ValueError("source interface time is not synchronized")
    out = json.loads(json.dumps(source))
    out["parameters"]["dt"] = dt
    new_step = int(round(source_time / dt))
    out["state"]["step"] = new_step
    out["state"]["time_s"] = source_time
    out["interface_state_used_by_cfd"]["step"] = new_step
    out["interface_state_used_by_cfd"]["time_s"] = source_time
    out["cfd"]["time_s"] = source_time
    out["cfd"]["time_directory"] = str((ROOT / "cases/openfoam" / case_name / "130").absolute())
    out["v8_provenance"] = {
        "source_checkpoint": str(SOURCE.absolute()),
        "common_physical_time_s": source_time,
        "common_source_step": 52000,
        "branch_dt_s": dt,
        "branch_step_at_common_time": new_step,
        "only_dt_and_time_index_rewritten": True,
        "same_cfd_initial_field": True,
        "parameters_modified": False,
    }
    target = OUT_ROOT / name / "sdof_checkpoint.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    make_branch("Ur5p2_dt0025_from130", 0.0025, "single_dof_free_viv_Ur5p2_v8_dt0025_from130")
    make_branch("Ur5p2_dt00125_from130", 0.00125, "single_dof_free_viv_Ur5p2_v8_dt00125_from130")
    source = json.loads(SOURCE.read_text(encoding="utf-8-sig"))
    manifest = {
        "schema_version": "common_dt_checkpoint_manifest_v8",
        "source_checkpoint": str(SOURCE.absolute()),
        "common_physical_time_s": float(source["state"]["time_s"]),
        "common_source_step": int(source["state"]["step"]),
        "state": source["state"],
        "interface_state_used_by_cfd": source["interface_state_used_by_cfd"],
        "previous_force_y_N": source["previous_force_y_N"],
        "parameters_without_dt": {key: value for key, value in source["parameters"].items() if key != "dt"},
        "branches": [
            {"dt_s": 0.0025, "step_at_common_time": 52000, "case": "cases/openfoam/single_dof_free_viv_Ur5p2_v8_dt0025_from130"},
            {"dt_s": 0.00125, "step_at_common_time": 104000, "case": "cases/openfoam/single_dof_free_viv_Ur5p2_v8_dt00125_from130"},
        ],
        "same_cfd_initial_field_required": True,
        "parameters_modified": False,
    }
    (OUT_ROOT / "common_checkpoint_manifest_v8.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("prepared common checkpoint at t=130 s for dt=0.0025 and dt=0.00125")


if __name__ == "__main__":
    main()
