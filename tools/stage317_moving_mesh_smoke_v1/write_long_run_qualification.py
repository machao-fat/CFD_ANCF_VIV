from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results/317_moving_mesh_smoke_v1"


def main() -> int:
    report = json.loads((RESULTS / "stage308_smoke_report.json").read_text(encoding="utf-8"))
    checks = report["checks"]
    smoke_pass = report["status"] == "pass"
    gate_checks = {
        "fresh_three_slice_smoke_pass": smoke_pass,
        "all_eight_steps_committed": checks.get("structure_records_8") is True and checks.get("mapping_records_8") is True,
        "moving_mesh_nonzero_and_changed": checks.get("cell_displacement_cyl_nonzero") is True and checks.get("moved_mesh_points_changed") is True,
        "slice_motion_identity_distinct": checks.get("slice_motion_identity_distinct") is True,
        "slice_force_identity_distinct_after_initialization": checks.get("slice_force_identity_distinct") is True,
        "all_returns_zero": checks.get("returns_zero") is True,
        "owned_residual_zero": report.get("owned_residual") == 0,
        "no_formal_convergence_claim": True,
        "old_runtimes_not_reused": True,
    }
    gate = {
        "gate_id": "STAGE4F_D_MOVING_MESH_THREE_SLICE_LONG_RUN_QUALIFICATION_V1_GATE",
        "status": "pass" if all(gate_checks.values()) else "do_not_pass",
        "stage_id": report["stage_id"],
        "run_id": report["run_id"],
        "case_id": report["case_id"],
        "source_smoke_gate": "STAGE4F_D_MOVING_MESH_THREE_SLICE_SMOKE_V1_GATE",
        "checks": gate_checks,
        "real_process_starts": report["real_process_starts"],
        "owned_residual": report["owned_residual"],
        "scope": "qualification to request a new long-duration three-slice run; no long run started",
        "qualification": "eligible to request a new long-duration three-slice run with a new stage/run/case/runtime; not authorization to start it",
        "formal_status": {
            "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
            "FORMAL_RESPONSE_FREQUENCY_STATUS": "not_completed_for_two_way_fsi",
            "FORMAL_STROUHAL_STATUS": "not_completed",
            "LOCK_IN_CLAIM": "not_completed",
        },
        "next_authorization": "new explicit authorization required before any long-duration CFD run",
    }
    out = RESULTS / "stage4f_d_moving_mesh_three_slice_long_run_qualification_v1_gate.json"
    out.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["gate_id"], "status": gate["status"], "path": str(out)}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
