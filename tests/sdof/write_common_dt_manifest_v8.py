"""Record the immutable common 130 s state used by the v8 dt branches."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "results/04_sdof_corrected_campaign/Ur5p2_v6_retry_to130/sdof_checkpoint.json"
OUT = ROOT / "results/04_sdof_corrected_campaign/dt_convergence_v8/common_checkpoint_manifest_v8.json"


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8-sig"))
    if float(source["state"]["time_s"]) != 130.0 or int(source["state"]["step"]) != 52000:
        raise ValueError("source is not the expected common Ur=5.2 state")
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
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
