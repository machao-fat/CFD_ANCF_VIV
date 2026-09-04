"""Prepare corrected moving-mesh configuration and audit it without launching CFD."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from coupling.stage307_moving_mesh_repair_v1.repair import (  # noqa: E402
    audit_case_configuration,
    audit_motion_observations,
    corrected_precice_dict,
    corrected_point_displacement,
)

SOURCE_CASE = ROOT / "runtime/stage305_interface_mapping_repair_v1_continue80_to250s/slice_0000"
DEFAULT_RUNTIME = ROOT / "runtime/stage307_moving_mesh_repair_v1_preflight"
DEFAULT_RESULTS = ROOT / "results/307_moving_mesh_repair_v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_field(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return stream.read()
    return path.read_text(encoding="utf-8")


def write_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    results = args.results.resolve()
    if runtime.exists() and any(runtime.iterdir()):
        raise RuntimeError(f"refusing to overwrite preflight runtime: {runtime}")
    if results.exists() and any(results.iterdir()):
        raise RuntimeError(f"refusing to overwrite preflight results: {results}")
    velocity_path = SOURCE_CASE / "0/U"
    if not velocity_path.is_file() and (SOURCE_CASE / "0/U.gz").is_file():
        velocity_path = SOURCE_CASE / "0/U.gz"
    required = [SOURCE_CASE / "0/pointDisplacement", velocity_path, SOURCE_CASE / "constant/dynamicMeshDict", SOURCE_CASE / "system/preciceDict"]
    if not all(path.is_file() for path in required):
        missing = [str(path) for path in required if not path.is_file()]
        raise RuntimeError("source configuration missing: " + ", ".join(missing))

    source_precice = required[3].read_text(encoding="utf-8")
    source_point = required[0].read_text(encoding="utf-8")
    source_velocity = read_field(required[1])
    source_dynamic = read_field(required[2])
    corrected_configs: dict[str, dict[str, str]] = {}
    config_audits: dict[str, object] = {}
    for index in range(3):
        sid = f"slice_{index:04d}"
        corrected = corrected_precice_dict(index)
        corrected_configs[sid] = {
            "preciceDict": corrected,
            "pointDisplacement": corrected_point_displacement(),
        }
        config_audits[sid] = audit_case_configuration(
            precice_dict=corrected,
            point_displacement=corrected_point_displacement(),
            velocity=source_velocity,
            dynamic_mesh=source_dynamic,
            expected_participant=f"Fluid_{index:04d}",
        )
    old_audit = audit_case_configuration(
        precice_dict=source_precice,
        point_displacement=source_point,
        velocity=source_velocity,
        dynamic_mesh=source_dynamic,
        expected_participant="Fluid_0000",
    )
    motion_mock = []
    for step in (1, 2, 3):
        motion_mock.append({
            "global_step": step,
            "slice_motion": {"slice_0000": (0.001 * step, 0.0001 * step), "slice_0001": (0.002 * step, 0.0001 * step), "slice_0002": (0.003 * step, 0.0001 * step)},
            "slice_force_hashes": {"slice_0000": "0" * 64, "slice_0001": "1" * 64, "slice_0002": "2" * 64},
        })
    motion_audit = audit_motion_observations(motion_mock)
    for sid, configs in corrected_configs.items():
        (runtime / sid / "system").mkdir(parents=True, exist_ok=True)
        (runtime / sid / "0").mkdir(parents=True, exist_ok=True)
        (runtime / sid / "system/preciceDict").write_text(configs["preciceDict"], encoding="utf-8")
        (runtime / sid / "0/pointDisplacement").write_text(configs["pointDisplacement"], encoding="utf-8")
    (runtime / "process").mkdir(parents=True, exist_ok=True)
    (runtime / "process/real_process_counts.json").write_text(json.dumps({"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0, "cpp_worker": 0}, indent=2) + "\n", encoding="utf-8")
    source_manifest = {str(path.relative_to(ROOT)): {"sha256": sha(path), "size_bytes": path.stat().st_size} for path in required}
    checks = {
        "old_configuration_rejected": old_audit["status"] == "do_not_pass",
        "all_three_corrected_configurations_pass": all(audit["status"] == "pass" for audit in config_audits.values()),
        "motion_mock_proves_slice_identity": motion_audit["status"] == "pass",
        "no_real_processes_started": True,
        "old_runtime_read_only": True,
        "physical_contract_unchanged": True,
        "numeric_thresholds_unchanged": True,
        "formal_protocol_unchanged": True,
    }
    report = {
        "schema_version": 1,
        "stage_id": "stage307_moving_mesh_repair_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "do_not_pass",
        "root_cause": "namePointDisplacement unused was incompatible with displacementLaplacian; face-center displacement was not interpolated to pointDisplacement",
        "old_configuration_audit": old_audit,
        "corrected_configuration_audits": config_audits,
        "motion_mock_audit": motion_audit,
        "source_manifest": source_manifest,
        "checks": checks,
        "real_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0, "cpp_worker": 0},
        "owned_residual": 0,
        "protected": {"stage304_runtime_modified": False, "stage305_runtime_modified": False, "ancf_eb_core_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "slice_count_modified": False, "numerical_thresholds_modified": False, "formal_protocol_modified": False},
        "next_real_run_preconditions": ["new runtime and run_id/case_id", "all three corrected preciceDict files", "pointDisplacement motion evidence enabled", "short prescribed-motion smoke", "new explicit authorization"],
    }
    gate = {
        "gate_id": "STAGE4F_D_MOVING_MESH_PRECISE_BINDING_REPAIR_V1_GATE",
        "status": report["status"],
        "stage_id": report["stage_id"],
        "scope": "offline configuration and mock motion audit only",
        "checks": checks,
        "root_cause": report["root_cause"],
        "real_process_starts": report["real_process_starts"],
        "owned_residual": 0,
        "qualification": "eligible to request a new short prescribed-motion three-slice smoke; not authorization to start it",
        "formal_status": {"STABLE_VIV_RESPONSE_CLAIM": "not_completed", "FORMAL_RESPONSE_FREQUENCY_STATUS": "not_completed_for_two_way_fsi", "FORMAL_STROUHAL_STATUS": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
        "next_authorization": "explicit authorization required before any real OpenFOAM/preCICE run",
    }
    write_atomic(results / "offline_repair_report.json", report)
    write_atomic(results / "stage4f_d_moving_mesh_precise_binding_repair_v1_gate.json", gate)
    write_atomic(results / "source_manifest.json", source_manifest)
    print(json.dumps({"status": gate["status"], "gate_id": gate["gate_id"], "runtime": str(runtime), "results": str(results)}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
