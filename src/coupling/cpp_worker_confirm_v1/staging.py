"""Read-only staging audit for the C++ worker bounded confirm.

This module never creates a solver case and never launches MATLAB, WSL or
OpenFOAM.  It only proves that a future authorized run has fresh destinations,
an immutable accepted source, and deployable inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable, Mapping


class StagingAuditError(ValueError):
    """A staging input violates a fail-closed precondition."""


REQUIRED_CASE_FILES = (
    Path("constant/dynamicMeshDict"),
    Path("system/controlDict"),
    Path("system/fvSolution"),
    Path("multi_slice_case_config.json"),
)

EXPECTED_PHYSICS = {
    "length_m": 50.0,
    "outer_diameter_m": 1.0,
    "inner_diameter_m": 0.9,
    "youngs_modulus_pa": 3_227_125_779.2218256,
    "top_tension_n": 2_179_104.0029808935,
    "fluid_density_kgpm3": 1000.0,
    "kinematic_viscosity_m2ps": 0.01,
    "delta_t_s": 0.00125,
}
EXPECTED_SLICE_POSITIONS_M = (8.333333333333334, 25.0, 41.666666666666664)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fresh(path: Path) -> bool:
    return not path.exists() or (path.is_dir() and not any(path.iterdir()))


def _source_audit(source: Path, expected_sha256: str | None) -> dict[str, Any]:
    if not source.is_file():
        raise StagingAuditError(f"accepted source checkpoint is missing: {source}")
    digest = sha256(source)
    if expected_sha256 is not None and digest != expected_sha256:
        raise StagingAuditError("accepted source checkpoint SHA-256 mismatch")
    try:
        value = json.loads(source.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StagingAuditError("accepted source checkpoint is not valid UTF-8 JSON") from exc
    if (value.get("status") != "committed" or int(value.get("step", -1)) != 559 or
            abs(float(value.get("time_s", float("nan"))) - 2.2075) > 1e-12 or
            int(value.get("time_tick", -1)) != 2_207_500_000):
        raise StagingAuditError("accepted source identity is not step 559/time 2.2075/tick 2207500000")
    structure = value.get("structure")
    if not isinstance(structure, Mapping) or not {"q", "qdot", "qddot"}.issubset(structure):
        raise StagingAuditError("accepted source structure state is incomplete")
    return {"path": str(source), "sha256": digest, "step": 559, "time_s": 2.2075,
            "integer_tick": 2_207_500_000, "read_only": True,
            "state_dimensions": {key: len(structure[key]) for key in ("q", "qdot", "qddot")}}


def _baseline_audit(manifest_path: Path, expected_manifest_sha256: str | None) -> dict[str, Any]:
    if not manifest_path.is_file():
        raise StagingAuditError(f"MATLAB baseline manifest is missing: {manifest_path}")
    digest = sha256(manifest_path)
    if expected_manifest_sha256 is not None and digest != expected_manifest_sha256:
        raise StagingAuditError("MATLAB baseline manifest SHA-256 mismatch")
    value = json.loads(manifest_path.read_bytes().decode("utf-8"))
    root = manifest_path.parent
    missing: list[str] = []
    mismatches: list[str] = []
    for item in value.get("files", []):
        relative = str(item["path"])
        path = root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        if sha256(path) != str(item["sha256"]) or path.stat().st_size != int(item["size_bytes"]):
            mismatches.append(relative)
    return {"manifest": str(manifest_path), "manifest_sha256": digest,
            "expected_file_count": int(value.get("file_count", -1)),
            "verified_file_count": len(value.get("files", [])), "missing": missing,
            "hash_or_size_mismatch": mismatches, "protected": True,
            "status": "pass" if not missing and not mismatches else "do_not_pass"}


def _case_audit(template_cases: Iterable[Path], destination_root: Path) -> dict[str, Any]:
    templates = [Path(item).resolve() for item in template_cases]
    if len(templates) != 3:
        raise StagingAuditError("exactly three read-only template cases are required")
    rows: list[dict[str, Any]] = []
    metadata_warnings: list[str] = []
    for index, template in enumerate(templates):
        if not template.is_dir():
            raise StagingAuditError(f"slice template is missing: {template}")
        missing = [str(item) for item in REQUIRED_CASE_FILES if not (template / item).is_file()]
        if missing:
            raise StagingAuditError(f"slice {index} template is incomplete: {','.join(missing)}")
        motion_dict = (template / "constant/dynamicMeshDict").read_text(encoding="utf-8")
        match = re.search(r"(?m)^\s*sliceId\s+(\d+)\s*;", motion_dict)
        if match is None or int(match.group(1)) != index:
            raise StagingAuditError(f"slice {index} dynamicMeshDict sliceId is inconsistent")
        try:
            config = json.loads((template / "multi_slice_case_config.json").read_bytes().decode("utf-8"))
            actual = {
                "length_m": float(config["ancf"]["length_m"]),
                "outer_diameter_m": float(config["ancf"]["outer_diameter_m"]),
                "inner_diameter_m": float(config["ancf"]["inner_diameter_m"]),
                "youngs_modulus_pa": float(config["ancf"]["youngs_modulus_pa"]),
                "top_tension_n": float(config["ancf"]["top_tension_n"]),
                "fluid_density_kgpm3": float(config["cfd"]["rho_kgpm3"]),
                "kinematic_viscosity_m2ps": float(config["cfd"]["nu_m2ps"]),
                "delta_t_s": float(config["delta_t_s"]),
            }
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise StagingAuditError(f"slice {index} physical config is invalid") from exc
        mismatches = [key for key, expected in EXPECTED_PHYSICS.items()
                      if abs(actual[key] - expected) > 1e-12 * max(1.0, abs(expected))]
        if mismatches:
            raise StagingAuditError(f"slice {index} physical contract mismatch: {','.join(mismatches)}")
        if int(config.get("slice_id", -1)) != index:
            metadata_warnings.append(f"slice {index}: config slice_id must be regenerated")
        if abs(float(config.get("s_ref_m", float("nan"))) - EXPECTED_SLICE_POSITIONS_M[index]) > 1e-12:
            metadata_warnings.append(f"slice {index}: config s_ref_m must be regenerated")
        destination = (destination_root / f"slice_{index:04d}").resolve()
        destination_issues: list[str] = []
        destination_staged = False
        if destination.is_dir():
            missing_destination = [str(item) for item in REQUIRED_CASE_FILES if not (destination / item).is_file()]
            if missing_destination:
                destination_issues.append(f"slice {index}: staged case missing {','.join(missing_destination)}")
            else:
                try:
                    destination_motion = (destination / "constant/dynamicMeshDict").read_text(encoding="utf-8")
                    destination_match = re.search(r"(?m)^\s*sliceId\s+(\d+)\s*;", destination_motion)
                    destination_config = json.loads((destination / "multi_slice_case_config.json").read_bytes().decode("utf-8"))
                    destination_actual = {
                        "length_m": float(destination_config["ancf"]["length_m"]),
                        "outer_diameter_m": float(destination_config["ancf"]["outer_diameter_m"]),
                        "inner_diameter_m": float(destination_config["ancf"]["inner_diameter_m"]),
                        "youngs_modulus_pa": float(destination_config["ancf"]["youngs_modulus_pa"]),
                        "top_tension_n": float(destination_config["ancf"]["top_tension_n"]),
                        "fluid_density_kgpm3": float(destination_config["cfd"]["rho_kgpm3"]),
                        "kinematic_viscosity_m2ps": float(destination_config["cfd"]["nu_m2ps"]),
                        "delta_t_s": float(destination_config["delta_t_s"]),
                    }
                    destination_mismatch = [key for key, expected in EXPECTED_PHYSICS.items()
                                            if abs(destination_actual[key] - expected) > 1e-12 * max(1.0, abs(expected))]
                    if destination_match is None or int(destination_match.group(1)) != index:
                        destination_issues.append(f"slice {index}: staged dynamicMeshDict sliceId mismatch")
                    if int(destination_config.get("slice_id", -1)) != index:
                        destination_issues.append(f"slice {index}: staged config slice_id mismatch")
                    if abs(float(destination_config.get("s_ref_m", float("nan"))) - EXPECTED_SLICE_POSITIONS_M[index]) > 1e-12:
                        destination_issues.append(f"slice {index}: staged config s_ref_m mismatch")
                    if destination_mismatch:
                        destination_issues.append(f"slice {index}: staged physical contract mismatch")
                    forbidden = []
                    for path in destination.rglob("*"):
                        if not path.is_file():
                            continue
                        relative = path.relative_to(destination)
                        if relative.parts[0] in {"coupling", "postProcessing", "checkpoints"}:
                            forbidden.append(str(relative))
                        if path.name.startswith("log.") or path.name.endswith(".log"):
                            forbidden.append(str(relative))
                    if forbidden:
                        destination_issues.append(f"slice {index}: staged case contains runtime artifacts")
                    destination_staged = not destination_issues
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                    destination_issues.append(f"slice {index}: staged case metadata is invalid")
        rows.append({"slice_id": index, "template": str(template), "template_read_only": True,
                     "destination": str(destination), "destination_fresh": _fresh(destination),
                     "destination_staged": destination_staged, "destination_issues": destination_issues,
                     "required_files": [str(item).replace("\\", "/") for item in REQUIRED_CASE_FILES],
                     "physical_contract": actual})
    destination_blockers = [issue for item in rows for issue in item["destination_issues"]]
    return {"count": 3, "slices": rows, "metadata_warnings": metadata_warnings,
            "destination_blockers": destination_blockers,
            "status": "pass" if all(item["destination_fresh"] or item["destination_staged"] for item in rows) else "do_not_pass"}


def audit_staging(*, project_root: Path, source_checkpoint: Path,
                  source_sha256: str | None, baseline_manifest: Path,
                  baseline_manifest_sha256: str | None, template_cases: Iterable[Path],
                  destination_cases: Path, runtime: Path, results: Path,
                  worker_executable: Path, deployable_library_candidates: Iterable[Path],
                  real_authorization_present: bool = False) -> dict[str, Any]:
    root = project_root.resolve()
    paths = {"runtime": runtime.resolve(), "results": results.resolve(),
             "destination_cases": destination_cases.resolve()}
    for name, path in paths.items():
        if root not in path.parents:
            raise StagingAuditError(f"{name} escaped project root")
    source = _source_audit(source_checkpoint.resolve(), source_sha256)
    baseline = _baseline_audit(baseline_manifest.resolve(), baseline_manifest_sha256)
    cases = _case_audit(template_cases, destination_cases)
    candidates = [Path(item).resolve() for item in deployable_library_candidates]
    libraries = [str(item) for item in candidates if item.is_file() and item.suffix.lower() == ".so"]
    blockers: list[str] = []
    if not real_authorization_present:
        blockers.append("explicit OpenFOAM/WSL/CFD authorization is absent")
    if not libraries:
        blockers.append("deployable libancfFileMotion.so is not available on the D-drive")
    if not worker_executable.is_file():
        blockers.append("C++ worker Release executable is missing")
    if not cases["status"] == "pass":
        blockers.append("one or more new case destinations are neither fresh nor audited staged cases")
    blockers.extend(cases.get("destination_blockers", []))
    if not _fresh(paths["runtime"]):
        blockers.append("confirm runtime is not fresh")
    if not _fresh(paths["results"]):
        blockers.append("confirm results directory is not fresh")
    return {
        "stage_id": "stage4f_d_cpp_worker_persistent_ipc_staging_audit_v1",
        "run_id": "cpp_worker_persistent_ipc_staging_001",
        "case_id": "cpp_worker_persistent_ipc_staging_case_001",
        "scope": {"global_steps": 40, "segment_duration_s": 0.05, "global_dt_s": 0.00125,
                  "slice_count": 3, "source_global_step": 559, "target_final_step": 599,
                  "target_final_time_s": 2.2575, "target_final_tick": 2_257_500_000},
        "source": source, "matlab_baseline": baseline, "cases": cases,
        "worker_executable": {"path": str(worker_executable.resolve()), "exists": worker_executable.is_file()},
        "deployable_library_candidates": [str(item) for item in candidates],
        "deployable_libraries": libraries,
        "planned_external_commands": {
            "openfoam_per_slice": 1, "wsl_per_slice": 1,
            "command_shape": ["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", "pimpleFoam"]},
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "blockers": blockers,
        "status": "pass" if not blockers else "do_not_pass",
        "launch_performed": False,
        "old_evidence_modified": False,
    }


def main() -> int:
    # staging.py lives under src/coupling/cpp_worker_confirm_v1.
    project = Path(__file__).resolve().parents[3]
    stage_root = project / "results/101_cpp_worker_confirm_staging_v1"
    runtime = project / "runtime/cpp_worker_persistent_ipc_v1/real_confirm_001"
    results = stage_root / "confirm_results"
    case_root = project / "cases/openfoam/cpp_worker_persistent_ipc_v1/real_confirm_001"
    source = project / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
    baseline = project / "runtime/cpp_worker_persistent_ipc_v1/matlab_worker_baseline_v1/matlab_worker_baseline_manifest.json"
    templates = [project / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/cases" / f"slice_{index:04d}" for index in range(3)]
    worker = project / "runtime/cpp_worker_persistent_ipc_v1/build-release/cfd_ancf_ancf_kernel_worker.exe"
    libraries = [project / "src/openfoam/ancfFileMotion/ancfFileMotion.C",
                 project / "runtime/stage4f_three_slice_bridge_precision_repair_v1/ancfFileMotion_stage4f_c_v1/libancfFileMotion.so"]
    audit = audit_staging(
        project_root=project, source_checkpoint=source,
        source_sha256="341b9ccf21e0436791456333a6c3baccfde69c3735f717763d576952dba0a226",
        baseline_manifest=baseline,
        baseline_manifest_sha256="9b6fcbf48277d07043818cad1e7c2c8cdbc37a80ec71f4c27bd7ab4c8f8331cb",
        template_cases=templates, destination_cases=case_root, runtime=runtime, results=results,
        worker_executable=worker, deployable_library_candidates=libraries,
        real_authorization_present=False,
    )
    stage_root.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(audit, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    temporary = stage_root / "staging_audit.json.tmp"
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(stage_root / "staging_audit.json")
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_STAGING_V1_GATE: " + ("pass" if audit["status"] == "pass" else "do_not_pass"),
        "status": audit["status"], "blockers": audit["blockers"],
        "real_process_starts": audit["real_process_starts"], "owned_residual": 0,
        "launch_performed": False, "old_evidence_modified": False,
        "next_action": "obtain explicit OpenFOAM/WSL/CFD authorization and deploy libancfFileMotion.so" if audit["blockers"] else "eligible for one bounded confirm",
    }
    (stage_root / "stage4f_d_cpp_worker_persistent_ipc_staging_v1_gate.json").write_text(
        json.dumps(gate, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(gate, ensure_ascii=True, indent=2))
    return 0 if audit["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
