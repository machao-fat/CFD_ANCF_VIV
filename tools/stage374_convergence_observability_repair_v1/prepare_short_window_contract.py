"""Create and validate an unauthorised short-window observability contract."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.convergence_observability_v3 import validate_observability_contract  # noqa: E402

OUTPUT = ROOT / "results/374_convergence_observability_repair_v1/short_window_observability_contract.json"


def main() -> int:
    contract = {
        "schema_version": 1,
        "stage_id": "stage4f_d_short_window_observability_preflight_v1",
        "run_id": "UNAUTHORIZED_TEMPLATE",
        "case_id": "UNAUTHORIZED_TEMPLATE",
        "source_global_step": None,
        "target_global_step": None,
        "source_time_s": None,
        "target_time_s": None,
        "dt_s": 0.005,
        "slice_ids": ["slice_0000", "slice_0001", "slice_0002"],
        "identity_fields": [
            "run_id", "case_id", "slice_id", "global_step", "case_local_bridge_step",
            "time_s", "integer_tick", "request_id", "transaction_id",
        ],
        "quality_fields": ["time_s", "courant_max", "residual_max", "continuity_global", "iterations_max"],
        "response_fields": ["interface_position_y", "force_y", "force_rms", "force_peak_to_peak"],
        "terminal_quality_required": True,
        "missing_value_policy": "fail_closed_no_interpolation",
        "finite_required": True,
        "preserve_formal_status": True,
        "real_process_allowed": False,
        "retention_policy": "compact_scalar_stream_plus_tail_checkpoint_only",
    }
    audit = validate_observability_contract(contract)
    payload = {"contract": contract, "preflight": audit, "execution_authorized": False}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))
    return 0 if audit["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
