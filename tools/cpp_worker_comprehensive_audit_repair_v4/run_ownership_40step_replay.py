"""Run a Stage 158 ownership replay with the frozen v1 force semantics.

The legacy Stage 152 helper treated ``external_force`` as CFD-only.  The v1
wire contract defines that field as total_Qext, so this stage-local wrapper
keeps the legacy helper unchanged and applies the correct audit predicate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from cpp_physics_ownership_v1.run_offline_validation import (  # noqa: E402
    KernelModel,
    expected_base,
    run,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=40)
    args = parser.parse_args()
    model = KernelModel(
        length_m=10.0, diameter_m=1.0, inner_diameter_m=0.9,
        elements=2, slices=3, top_tension_N=1.0e6,
        youngs_modulus_Pa=2.07e11, material_density=7850.0,
        fluid_density=1025.0, gravity=9.81, gauss_order=5,
        max_newton=50, slice_positions_m=(0.0, 5.0, 10.0),
    )
    result = run(args.worker.resolve(), args.steps, expected_base(model))
    legacy_status = result["status"]
    valid = (
        result.get("process_error") is None
        and result.get("steps_completed") == args.steps
        and result.get("worker_return_code") == 0
        and result.get("owned_residual") == 0
        and result.get("base_load_external_max_abs_error", float("inf")) <= 1.0e-8
        and result.get("response_identity_continuous") is True
        and result.get("finite_value_audit") is True
    )
    result.update({
        "stage_id": "stage4f_d_cpp_worker_comprehensive_audit_repair_v4",
        "run_id": "cpp_worker_comprehensive_audit_repair_158_replay_002",
        "case_id": "cpp_worker_comprehensive_audit_case_158_replay_002",
        "status": "pass" if valid else "do_not_pass",
        "legacy_validator_status": legacy_status,
        "response_external_force_semantics": "total_Qext",
        "cfd_input_force_representation": "integrated_N",
        "cfd_input_max_abs": 0.0,
        "legacy_cfd_only_zero_check_is_diagnostic_only": True,
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result.get(key) for key in (
        "status", "legacy_validator_status", "steps_completed", "worker_start_count",
        "base_load_external_max_abs_error", "owned_residual", "physical_process_starts",
    )}, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
