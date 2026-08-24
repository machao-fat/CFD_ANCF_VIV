#!/usr/bin/env python3
"""Run the bounded Stage 4C-B real three-slice campaign.

The command creates a unique result directory under the authorized
Stage-4C-B result root.  It never writes any previous Stage 4A/4B result
directory and never modifies the frozen manifest.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.coupling.multi_slice_mapping.mapping import atomic_write_json, sha256_file
from src.coupling.multi_slice_real_campaign.campaign import (
    DEFAULT_LIBRARY,
    FROZEN_MANIFEST_HASH,
    build_physics_manifest,
    build_runtime_config,
    generate_dynamic_case,
    generate_preprocessed_case,
    load_frozen_manifest,
    prepare_condition_cases,
    run_real_condition,
    stage_restart_case,
    _now_run_id,
)


def _fields_by_slice(warmups: list[dict[str, object]]) -> dict[int, dict[str, object]]:
    result = {}
    for item in warmups:
        result[int(item["case"].split("slice_")[-1])] = {
            "case": item["case"],
            "time_name": format(float(item["end_time_s"]), ".12g"),
            "field_files": item["field_files"],
            "preprocessed_independently": True,
        }
    return result


def _copy_summary(source: dict[str, object], target: Path) -> None:
    atomic_write_json(target, source)


_FLOAT_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _numeric_values(path: Path) -> list[float]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [float(item) for item in _FLOAT_RE.findall(text)]


def _relative_numeric_error(left: Path, right: Path) -> float:
    left_values = _numeric_values(left)
    right_values = _numeric_values(right)
    if len(left_values) != len(right_values):
        return math.inf
    scale = max(1.0, *(abs(item) for item in left_values), *(abs(item) for item in right_values))
    return max((abs(a - b) for a, b in zip(left_values, right_values)), default=0.0) / scale


def _absolute_numeric_error(left: Path, right: Path) -> float:
    left_values = _numeric_values(left)
    right_values = _numeric_values(right)
    if len(left_values) != len(right_values):
        return math.inf
    return max((abs(a - b) for a, b in zip(left_values, right_values)), default=0.0)


def _checkpoint_entries(path: Path) -> dict[int, dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(item["slice_id"]): item for item in payload["slices"]}


def _declared_file_map(entries: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    result = {}
    for entry in entries:
        relative = str(entry["relative_path"]).replace("\\", "/")
        result[relative.split("/", 1)[1]] = entry
    return result


def _restart_field_audit(
    *,
    baseline: dict[str, object],
    restart: dict[str, object],
    steps: tuple[int, ...] = (1, 2),
) -> dict[str, object]:
    """Compare files staged through the formal checkpoint manifests.

    The audit deliberately resolves files through each manifest's declared
    relative paths.  It therefore checks the same objects that the formal
    checkpoint validator checked, rather than relying on a case-directory
    glob or on the current OpenFOAM time directory.
    """
    baseline_by_step = {int(item["step"]): item for item in baseline["checkpoint_audit"]}
    restart_by_step = {int(item["step"]): item for item in restart["checkpoint_audit"]}
    fields: dict[str, object] = {}
    motion_hashes: dict[str, bool] = {}
    max_u = 0.0
    max_p = 0.0
    max_points = 0.0
    exact_hash_failures: list[str] = []
    for step in steps:
        baseline_checkpoint = Path(str(baseline_by_step[step]["path"]))
        restart_checkpoint = Path(str(restart_by_step[step]["path"]))
        baseline_entries = _checkpoint_entries(baseline_checkpoint)
        restart_entries = _checkpoint_entries(restart_checkpoint)
        for slice_id in (0, 1, 2):
            baseline_entry = baseline_entries[slice_id]
            restart_entry = restart_entries[slice_id]
            baseline_case = Path(str(baseline["case_paths"][slice_id]))
            restart_case = Path(str(restart["case_paths"][slice_id]))
            baseline_time_files = _declared_file_map(baseline_entry["time_files"])
            restart_time_files = _declared_file_map(restart_entry["time_files"])
            baseline_static_files = _declared_file_map(baseline_entry["static_files"])
            restart_static_files = _declared_file_map(restart_entry["static_files"])
            declared = ["U", "p", "phi", "Uf", "meshPhi", "polyMesh/points", "uniform/time"]
            for name in declared:
                baseline_file_entry = baseline_time_files[name]
                restart_file_entry = restart_time_files[name]
                baseline_file = baseline_case / str(baseline_file_entry["relative_path"])
                restart_file = restart_case / str(restart_file_entry["relative_path"])
                key = f"step{step}/slice{slice_id}/{name}"
                same_hash = sha256_file(baseline_file) == sha256_file(restart_file)
                relative = _relative_numeric_error(baseline_file, restart_file)
                absolute = _absolute_numeric_error(baseline_file, restart_file)
                fields[key] = {
                    "sha256_equal": same_hash,
                    "relative_numeric_error": relative,
                    "absolute_numeric_error": absolute,
                    "baseline_sha256": sha256_file(baseline_file),
                    "restart_sha256": sha256_file(restart_file),
                }
                if name == "U":
                    max_u = max(max_u, relative)
                elif name == "p":
                    max_p = max(max_p, relative)
                elif name == "polyMesh/points":
                    max_points = max(max_points, absolute)
                if name not in {"U", "p"} and not same_hash:
                    exact_hash_failures.append(key)
            baseline_motion = baseline_case / str(baseline_static_files["motionScale"]["relative_path"])
            restart_motion = restart_case / str(restart_static_files["motionScale"]["relative_path"])
            motion_key = f"step{step}/slice{slice_id}/motionScale"
            motion_hashes[motion_key] = sha256_file(baseline_motion) == sha256_file(restart_motion)
            if not motion_hashes[motion_key]:
                exact_hash_failures.append(motion_key)
    return {
        "fields": fields,
        "motionScale_hashes": motion_hashes,
        "motionScale_hash_equal": all(motion_hashes.values()),
        "max_U_relative_error": max_u,
        "max_p_relative_error": max_p,
        "max_points_absolute_error_m": max_points,
        "exact_hash_failures": exact_hash_failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "results" / "05_stage4c_real_three_slice_tests")
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "results" / "05_stage4c_scalability_tests" / "canonical_3slice_manifest_candidate.json")
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--start-time", type=float, default=0.05)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--phase", choices=("all", "uniform", "nonuniform", "restart"), default="all")
    args = parser.parse_args()

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    master_id = _now_run_id("stage4c_b")
    root = output_root / master_id
    root.mkdir(parents=True, exist_ok=False)
    manifest = load_frozen_manifest(args.manifest)
    if manifest.slice_manifest_sha256 != FROZEN_MANIFEST_HASH:
        raise SystemExit("frozen manifest hash check failed")
    runtime = build_runtime_config(manifest, start_time_s=args.start_time, timeout_s=args.timeout)
    atomic_write_json(root / "frozen_manifest.json", manifest.to_dict())
    atomic_write_json(root / "runtime_config.json", runtime.to_dict())

    uniform_summary = None
    nonuniform_summary = None
    segment_summary = None
    restart_summary = None
    restart_comparison = None

    if args.phase in {"all", "uniform"}:
        uniform_root = root / "uniform"
        uniform_root.mkdir()
        warmups, _ = prepare_condition_cases(root=uniform_root, manifest=manifest, runtime_config=runtime, speeds_mps={0: 1.0, 1: 1.0, 2: 1.0}, condition="uniform", run_id=f"{master_id}_uniform")
        physics = build_physics_manifest(manifest=manifest, runtime_config=runtime, condition="uniform", speeds_mps={0: 1.0, 1: 1.0, 2: 1.0}, run_id=f"{master_id}_uniform", initial_fields=_fields_by_slice(warmups), library=args.library)
        atomic_write_json(uniform_root / "stage4c_physics_manifest.json", physics)
        uniform_summary = run_real_condition(root=uniform_root, manifest=manifest, runtime_config=runtime, physics_manifest=physics, speeds_mps={0: 1.0, 1: 1.0, 2: 1.0}, condition="uniform", library=args.library, steps=3, run_id=f"{master_id}_uniform")
        _copy_summary(uniform_summary, output_root / "uniform_three_slice_summary.json")
        if uniform_summary["status"] != "completed":
            raise SystemExit("uniform three-slice real campaign failed; nonuniform/restart paths were not entered")

    if args.phase in {"all", "nonuniform", "restart"}:
        continuous_root = root / "nonuniform_continuous"
        continuous_root.mkdir()
        warmups, _ = prepare_condition_cases(root=continuous_root, manifest=manifest, runtime_config=runtime, speeds_mps={0: 0.8, 1: 1.0, 2: 1.2}, condition="nonuniform", run_id=f"{master_id}_nonuniform_continuous")
        physics = build_physics_manifest(manifest=manifest, runtime_config=runtime, condition="nonuniform", speeds_mps={0: 0.8, 1: 1.0, 2: 1.2}, run_id=f"{master_id}_nonuniform", initial_fields=_fields_by_slice(warmups), library=args.library)
        atomic_write_json(continuous_root / "stage4c_physics_manifest.json", physics)
        if args.phase in {"all", "nonuniform"}:
            nonuniform_summary = run_real_condition(root=continuous_root, manifest=manifest, runtime_config=runtime, physics_manifest=physics, speeds_mps={0: 0.8, 1: 1.0, 2: 1.2}, condition="nonuniform", library=args.library, steps=3, run_id=f"{master_id}_nonuniform_continuous")
            _copy_summary(nonuniform_summary, output_root / "nonuniform_three_slice_summary.json")
            if nonuniform_summary["status"] != "completed":
                raise SystemExit("nonuniform three-slice real campaign failed; restart path was not entered")

        if args.phase in {"all", "restart"}:
            segment_root = root / "nonuniform_segment"
            segment_root.mkdir()
            warmups_seg, _ = prepare_condition_cases(root=segment_root, manifest=manifest, runtime_config=runtime, speeds_mps={0: 0.8, 1: 1.0, 2: 1.2}, condition="nonuniform_segment", run_id=f"{master_id}_nonuniform_segment")
            segment_physics = build_physics_manifest(manifest=manifest, runtime_config=runtime, condition="nonuniform", speeds_mps={0: 0.8, 1: 1.0, 2: 1.2}, run_id=f"{master_id}_nonuniform", initial_fields=_fields_by_slice(warmups_seg), library=args.library)
            atomic_write_json(segment_root / "stage4c_physics_manifest.json", segment_physics)
            segment_summary = run_real_condition(root=segment_root, manifest=manifest, runtime_config=runtime, physics_manifest=segment_physics, speeds_mps={0: 0.8, 1: 1.0, 2: 1.2}, condition="nonuniform_segment", library=args.library, steps=1, run_id=f"{master_id}_nonuniform_segment")
            if segment_summary["status"] != "completed":
                raise SystemExit("nonuniform segment step 0 failed; restart path was not entered")
            checkpoint = Path(str(segment_summary["checkpoint_audit"][0]["path"])).resolve()
            restart_root = root / "nonuniform_restart"
            restart_root.mkdir()
            warmups_restart, _ = prepare_condition_cases(root=restart_root, manifest=manifest, runtime_config=runtime, speeds_mps={0: 0.8, 1: 1.0, 2: 1.2}, condition="nonuniform_restart", run_id=f"{master_id}_nonuniform_restart")
            restart_physics = build_physics_manifest(manifest=manifest, runtime_config=runtime, condition="nonuniform", speeds_mps={0: 0.8, 1: 1.0, 2: 1.2}, run_id=f"{master_id}_nonuniform", initial_fields=_fields_by_slice(warmups_restart), library=args.library)
            atomic_write_json(restart_root / "stage4c_physics_manifest.json", restart_physics)
            stage_audit = stage_restart_case(checkpoint_path=checkpoint, source_case_root=segment_root / "cases", target_case_root=restart_root / "cases")
            atomic_write_json(restart_root / "restart_stage_audit.json", stage_audit)
            checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            native_relative = checkpoint_payload["structure"].get("runner_checkpoint_relative_path")
            resume_native = checkpoint.parent / str(native_relative)
            restart_summary = run_real_condition(root=restart_root, manifest=manifest, runtime_config=runtime, physics_manifest=restart_physics, speeds_mps={0: 0.8, 1: 1.0, 2: 1.2}, condition="nonuniform_restart", library=args.library, steps=2, resume_native=resume_native, restore_checkpoint=checkpoint, run_id=f"{master_id}_nonuniform_restart")
            if restart_summary["status"] != "completed":
                raise SystemExit("nonuniform restart run failed")

    if nonuniform_summary is None and args.phase == "restart":
        nonuniform_summary = json.loads((output_root / "nonuniform_three_slice_summary.json").read_text(encoding="utf-8"))
    if segment_summary is not None and restart_summary is not None:
        baseline = nonuniform_summary or json.loads((output_root / "nonuniform_three_slice_summary.json").read_text(encoding="utf-8"))
        baseline_by_step = {int(item["step"]): item for item in baseline["step_results"]}
        restart_by_step = {int(item["step"]): item for item in restart_summary["step_results"]}
        state_errors = {}
        force_errors = {}
        for step in (1, 2):
            for key in ("q", "qdot", "qddot"):
                left = baseline_by_step[step][key]
                right = restart_by_step[step][key]
                scale = max(1.0, max(abs(float(v)) for v in left), max(abs(float(v)) for v in right))
                state_errors[f"step{step}/{key}"] = max(abs(float(a)-float(b)) for a,b in zip(left,right)) / scale
            left_force = baseline_by_step[step]["integrated_slice_forces_N"]
            right_force = restart_by_step[step]["integrated_slice_forces_N"]
            scale = max(1.0, max(abs(float(v)) for row in left_force for v in row), max(abs(float(v)) for row in right_force for v in row))
            force_errors[f"step{step}"] = max(abs(float(a)-float(b)) for lrow,rrow in zip(left_force,right_force) for a,b in zip(lrow,rrow)) / scale
        field_audit = _restart_field_audit(baseline=baseline, restart=restart_summary)
        time_errors = {str(step): abs(float(baseline_by_step[step]["time_s"])-float(restart_by_step[step]["time_s"])) for step in (1, 2)}
        manifest_hash_equal = baseline["slice_manifest_sha256"] == restart_summary["slice_manifest_sha256"]
        config_hash_equal = baseline["config_sha256"] == restart_summary["config_sha256"]
        physics_hash_equal = baseline["physics_config_sha256"] == restart_summary["physics_config_sha256"]
        checkpoint_valid = all(item.get("valid") and item.get("object_count") == 26 for item in restart_summary["checkpoint_audit"])
        transaction_state_equal = all(
            baseline_by_step[step].get("checkpoint_status") == "committed"
            and restart_by_step[step].get("checkpoint_status") == "committed"
            for step in (1, 2)
        )
        threshold_failures = []
        if any(value > 1e-12 for value in time_errors.values()):
            threshold_failures.append("time")
        if any(value > 1e-10 for value in state_errors.values()):
            threshold_failures.append("ancf_state")
        if any(value > 1e-8 for value in force_errors.values()):
            threshold_failures.append("hydrodynamic_force")
        if field_audit["max_points_absolute_error_m"] > 1e-12:
            threshold_failures.append("points")
        if field_audit["max_U_relative_error"] > 1e-10:
            threshold_failures.append("U")
        if field_audit["max_p_relative_error"] > 1e-10:
            threshold_failures.append("p")
        if not field_audit["motionScale_hash_equal"]:
            threshold_failures.append("motionScale")
        if not (manifest_hash_equal and config_hash_equal and physics_hash_equal):
            threshold_failures.append("identity_hash")
        if not (checkpoint_valid and transaction_state_equal):
            threshold_failures.append("checkpoint_transaction")
        restart_comparison = {
            "schema_version": "stage4c-b-real-three-slice-restart-comparison-1",
            "status": "completed" if not threshold_failures else "blocked",
            "continuous_steps": sorted(baseline_by_step), "restart_steps": sorted(restart_by_step),
            "time_errors_s": time_errors,
            "ancf_state_relative_errors": state_errors, "hydrodynamic_force_relative_errors": force_errors,
            "field_audit": field_audit,
            "motionScale_hash_equal": field_audit["motionScale_hash_equal"],
            "manifest_hash_equal": manifest_hash_equal,
            "config_hash_equal": config_hash_equal,
            "physics_config_sha256_equal": physics_hash_equal,
            "checkpoint_valid": checkpoint_valid,
            "transaction_state_equal": transaction_state_equal,
            "threshold_failures": threshold_failures,
            "thresholds": {"time_s": 1e-12, "ancf": 1e-10, "points_m": 1e-12, "U": 1e-10, "p": 1e-10, "hydrodynamic_force": 1e-8},
            "checkpoint_stage_audit": str(root / "nonuniform_restart" / "restart_stage_audit.json"),
        }
        atomic_write_json(root / "three_slice_restart_comparison.json", restart_comparison)
        _copy_summary(restart_comparison, output_root / "three_slice_restart_comparison.json")

    bundle = {"schema_version": "stage4c-b-physics-bundle-1", "uniform": str(root / "uniform" / "stage4c_physics_manifest.json") if (root / "uniform" / "stage4c_physics_manifest.json").is_file() else None, "nonuniform": str(root / "nonuniform_continuous" / "stage4c_physics_manifest.json") if (root / "nonuniform_continuous" / "stage4c_physics_manifest.json").is_file() else None}
    atomic_write_json(root / "stage4c_physics_manifest.json", bundle)
    atomic_write_json(output_root / "stage4c_physics_manifest.json", bundle)
    print(json.dumps({"status": "completed", "run_id": master_id, "root": str(root), "uniform": uniform_summary, "nonuniform": nonuniform_summary, "segment": segment_summary, "restart": restart_summary, "restart_comparison": restart_comparison}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
