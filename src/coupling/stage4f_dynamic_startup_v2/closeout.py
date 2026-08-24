"""Read-only closeout for a bounded Stage 4F-B-v2 run."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file


def _read_load(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as stream:
        return next(csv.DictReader(stream))


def closeout(run_root: Path, result_root: Path) -> dict[str, Any]:
    """Materialize a transparent gate decision without modifying the run."""
    summary_path = run_root / "real_run_summary.json"
    hot_path = run_root / "dynamic_hot_start_audit.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    hot = json.loads(hot_path.read_text(encoding="utf-8"))
    loads = []
    for path in sorted((run_root / "exchange").glob("slice_*/load/load_step*_iter0000.csv")):
        row = _read_load(path)
        raw_fx = float(row["openfoam_force_x_N"])
        loads.append({"path": str(path), "step": int(row["step"]), "slice_id": int(row["slice_id"]),
                      "time_s": float(row["time_s"]), "raw_force_x_N": raw_fx,
                      "raw_Cd": raw_fx / 500.0, "integrated_force_x_N": float(row["force_x_N"]),
                      "slice_length_m": float(row["slice_length_m"]),
                      "single_length_factor": float(row["force_x_N"]) / raw_fx})
    by_step: dict[int, list[dict[str, Any]]] = {}
    for item in loads:
        by_step.setdefault(item["step"], []).append(item)
    step_summary = [{"step": step, "max_abs_raw_Cd": max(abs(x["raw_Cd"]) for x in items), "slices": items}
                    for step, items in sorted(by_step.items())]
    final = next((item for item in step_summary if item["step"] == 2), None)
    force_limit_passed = final is not None and final["max_abs_raw_Cd"] <= 10.0
    checkpoints = summary.get("checkpoint_audit", [])
    result = {
        "run_root": str(run_root), "run_summary_sha256": sha256_file(summary_path), "dynamic_hot_start_sha256": sha256_file(hot_path),
        "dynamic_hot_start_passed": bool(hot["force_scale_passed"]), "hot_start_final_Cd": hot["hot_start"]["steps"][-1]["Cd"],
        "hot_start_max_cfl": hot["hot_start"]["max_cfl"], "coupled_force_audit": step_summary,
        "checkpoints": checkpoints, "committed_checkpoint_count": len(checkpoints),
        "root_cause": "unbalanced_mean_drag_at_ancf_startup_causes_streamwise_acceleration_and_step2_force_scale_failure",
        "not_root_cause": ["static_to_dynamic_mesh_cold_start", "slice_length_double_application", "H_HT_virtual_work_mapping"],
        "status": "blocked", "force_scale_limit_abs_Cd": 10.0, "final_force_scale_passed": force_limit_passed,
        "restart_authorized": False,
        "next_authorized_scope": "new_stage4f_b_v3_static_or_ramped_hydrodynamic_load_initialization_only",
        "forbidden_scope": ["five_slice", "nine_slice", "long_time_VIV", "lock_in", "experimental_validation"],
    }
    result["finite"] = all(math.isfinite(x["raw_Cd"]) for x in loads)
    result_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(result_root / "stage4f_b_v2_dynamic_startup_gate_candidate.json", result)
    atomic_write_json(result_root / "coupled_force_scale_audit.json", {"steps": step_summary, "single_length_factor_expected": 50.0 / 3.0})
    return result

