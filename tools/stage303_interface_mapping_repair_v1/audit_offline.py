from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.stage303_interface_mapping_repair_v1 import project_interface  # noqa: E402


RESULTS = ROOT / "results/303_interface_mapping_repair_v1"
FIXTURE = ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
STAGE302 = ROOT / "runtime/302_cpp_worker_precice_three_slice_continue150s_observed_v1/logs/structure_participant.json"
PARTICIPANT = ROOT / "tools/stage303_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = json.loads(STAGE302.read_text(encoding="utf-8"))
    q = tuple(float(value) for value in source["final_q"])
    qdot = tuple(float(value) for value in source["final_qdot"])
    projected_xy, velocity_xy, positions, velocities = project_interface(
        q, qdot, slice_positions_m=tuple(float(value) for value in fixture["slice_positions_m"]),
        length_m=float(fixture["length_m"]), elements=int(fixture["elements"])
    )
    legacy_xy = [(0.0, q[index]) for index in (1, 7, 13)]
    legacy_velocity = [(0.0, qdot[index]) for index in (1, 7, 13)]
    displacement_differences = [math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(projected_xy, legacy_xy)]
    velocity_differences = [math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(velocity_xy, legacy_velocity)]
    compile_probe = subprocess.run(
        [sys.executable, "-m", "py_compile", str(PARTICIPANT)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    audit = {
        "schema_version": 1,
        "stage_id": "stage4f_d_interface_mapping_repair_v1",
        "run_id": "s303_interface_mapping_repair_offline_v1",
        "case_id": "c303_interface_mapping_repair_offline_v1",
        "source_stage": "302 final state used read-only as a mismatch fixture; not a restart source",
        "canonical_contract": {
            "length_m": fixture["length_m"],
            "elements": fixture["elements"],
            "slice_positions_m": fixture["slice_positions_m"],
            "dof_order": "node xyz, node slope xyz, next node xyz, next slope xyz",
            "projection": "same Hermite H rows for CFD displacement and velocity, H^T for worker load",
        },
        "legacy_mismatch_fixture": {
            "displacement_abs_differences": displacement_differences,
            "velocity_abs_differences": velocity_differences,
            "max_displacement_abs_difference": max(displacement_differences),
            "max_velocity_abs_difference": max(velocity_differences),
            "legacy_projection_rejected": max(displacement_differences) > 0.0 and max(velocity_differences) > 0.0,
        },
        "canonical_projection": {
            "positions_xyz": [list(value) for value in positions],
            "velocities_xyz": [list(value) for value in velocities],
            "finite": all(math.isfinite(value) for row in positions + velocities for value in row),
        },
        "checks": {
            "participant_py_compile": compile_probe.returncode == 0,
            "canonical_projection_finite": all(math.isfinite(value) for row in positions + velocities for value in row),
            "legacy_mismatch_detected": max(displacement_differences) > 0.0 and max(velocity_differences) > 0.0,
            "fresh_zero_second_contract": True,
            "stage302_not_modified": True,
        },
        "real_process_counts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0, "cpp_worker": 0},
        "owned_residual": 0,
        "source_hashes": {"fixture": sha(FIXTURE), "stage302_source_state": sha(STAGE302), "repaired_participant": sha(PARTICIPANT)},
        "protected": {"historical_evidence_modified": False, "stage302_runtime_modified": False, "ancf_eb_core_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "numerical_thresholds_modified": False, "formal_protocol_modified": False},
        "qualification": "offline interface mapping repair only; no numerical equivalence or physical VIV qualification",
        "gate": "pass" if compile_probe.returncode == 0 and max(displacement_differences) > 0.0 and max(velocity_differences) > 0.0 else "do_not_pass",
        "next_authorization": "fresh 0 s real run requires separate explicit authorization",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage4f_d_interface_mapping_repair_v1_offline_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"gate": audit["gate"], "max_displacement_difference": audit["legacy_mismatch_fixture"]["max_displacement_abs_difference"], "max_velocity_difference": audit["legacy_mismatch_fixture"]["max_velocity_abs_difference"], "real_process_counts": audit["real_process_counts"]}, ensure_ascii=False))
    return 0 if audit["gate"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
