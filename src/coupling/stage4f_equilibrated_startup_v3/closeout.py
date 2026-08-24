"""Read-only evidence closeout for the v3 static/dynamic reconciliation gate."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from .equilibrium import MAX_ABS_CD, RECONCILIATION_END_S


def closeout(reconciliation_root: Path, result_root: Path, equilibrium_path: Path) -> dict:
    log = reconciliation_root / "cases" / "slice_0000" / "log.pimpleFoam_stage4f_b3_reconciliation"
    text = log.read_text(encoding="utf-8", errors="replace")
    cd_rows = [float(value) for value in re.findall(r"^\s*Cd\s+=\s+([-+0-9.eE]+)", text, flags=re.MULTILINE)]
    cfl_rows = [float(value) for value in re.findall(r"Courant Number mean:\s+[^\s]+\s+max:\s+([-+0-9.eE]+)", text)]
    equilibrium = json.loads(equilibrium_path.read_text(encoding="utf-8"))
    endpoint_cd = cd_rows[-1] if cd_rows else None
    value = {
        "status": "blocked", "equilibrium_sha256": sha256_file(equilibrium_path), "equilibrium_static_passed": equilibrium["static"]["passes"],
        "dynamic_reconciliation": {"slice_id": 0, "end_time_s": RECONCILIATION_END_S, "solver_completed": "End" in text,
            "log_sha256": sha256_file(log), "endpoint_Cd": endpoint_cd, "max_cfl": max(cfl_rows) if cfl_rows else None},
        "stop_condition": "reconciliation_endpoint_force_scale_exceeded",
        "force_scale_limit_abs_Cd": MAX_ABS_CD, "restart_authorized": False, "formal_three_slice_fsi_started": False,
        "next_authorized_scope": "reconsider_mean_drag_static_equilibrium_contract_or_domain_force_baseline_before_any_new_dynamic_reconciliation",
        "forbidden_scope": ["remaining_reconciliation_slices", "formal_three_slice_fsi", "restart", "five_slice", "nine_slice", "long_time_VIV"],
    }
    value["endpoint_force_scale_passed"] = endpoint_cd is not None and abs(endpoint_cd) <= MAX_ABS_CD
    result_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(result_root / "stage4f_b_v3_equilibrated_startup_gate_candidate.json", value)
    return value

