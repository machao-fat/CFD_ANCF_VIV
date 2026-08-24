from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence


class Stage4DAuditError(RuntimeError):
    pass


def _finite(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise Stage4DAuditError(f"{name} is NaN/Inf")
    return result


def energy_audit(rows: Sequence[Mapping[str, Any]], *, dt_s: float, epsilon: float = 1.0e-30) -> dict[str, Any]:
    """Compute the Stage 4D coupling-work defect from per-step rows."""
    if dt_s <= 0.0 or not math.isfinite(dt_s):
        raise Stage4DAuditError("dt_s must be positive and finite")
    cfd_values: list[float] = []
    structure_values: list[float] = []
    defects: list[float] = []
    for index, row in enumerate(rows):
        force = row.get("force_N", row.get("integrated_force_N"))
        v_pred = row.get("v_pred_mps", row.get("predicted_velocity_mps"))
        v_corr = row.get("v_corr_mps", row.get("corrected_velocity_mps"))
        if not isinstance(force, Sequence) or not isinstance(v_pred, Sequence) or not isinstance(v_corr, Sequence) or len(force) != len(v_pred) or len(force) != len(v_corr):
            raise Stage4DAuditError(f"row {index} force/velocity dimensions disagree")
        cfd = sum(_finite(force[i], f"rows[{index}].force_N") * _finite(v_pred[i], f"rows[{index}].v_pred_mps") for i in range(len(force))) * dt_s
        structure = sum(_finite(force[i], f"rows[{index}].force_N") * _finite(v_corr[i], f"rows[{index}].v_corr_mps") for i in range(len(force))) * dt_s
        cfd_values.append(cfd)
        structure_values.append(structure)
        defects.append(cfd - structure)
    total_cfd = sum(cfd_values)
    total_structure = sum(structure_values)
    total_defect = sum(defects)
    denominator = max(sum(abs(value) for value in cfd_values), epsilon)
    return {
        "status": "passed",
        "steps": len(rows),
        "dt_s": dt_s,
        "W_CFD_J": cfd_values,
        "W_structure_J": structure_values,
        "delta_W_c_J": defects,
        "sum_W_CFD_J": total_cfd,
        "sum_W_structure_J": total_structure,
        "sum_delta_W_c_J": total_defect,
        "E_c": abs(total_defect) / denominator,
        "threshold_E_c": 0.10,
        "threshold_pass": abs(total_defect) / denominator <= 0.10,
    }


def not_executed_medium_outputs(*, result_root: Path, reason: str, manifest_hash: str, developed_bank_status: str) -> dict[str, Any]:
    result_root.mkdir(parents=True, exist_ok=True)
    base = {
        "status": "not_executed",
        "reason": reason,
        "schema_version": "0.2.1",
        "slice_manifest_sha256": manifest_hash,
        "developed_flow_bank_status": developed_bank_status,
        "steps": 0,
    }
    outputs = {
        "stage4d_100step_summary.json": {**base, "scope": "real_three_slice_medium_stability", "matlab_process_start_count": None},
        "stage4d_restart_comparison.json": {**base, "scope": "10_step_vs_5_plus_5_restart", "errors": None},
        "stage4d_energy_audit.json": {**base, "scope": "coupling_work_audit", "E_c": None},
        "checkpoint_hash_audit.json": {**base, "scope": "unified_checkpoint_hash_audit", "checkpoint_count": 0},
        "stage4d_a_candidate_summary.json": {**base, "status": "blocked", "scope": "Stage4D-A", "long_run_entry_recommendation": "建议不进入", "stage4d_a_gate_recommendation": "建议不通过"},
    }
    for name, value in outputs.items():
        (result_root / name).write_text(__import__("json").dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return outputs
