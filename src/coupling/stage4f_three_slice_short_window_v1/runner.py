"""Serial real OpenFOAM--ANCF executor for Stage 4F-C-v1."""
from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import scipy.io as sio

from ..multi_slice_driver import MultiSliceConfig, MultiSliceScheduler
from ..multi_slice_mapping.mapping import LoadRecord, RuntimeConfig, atomic_write_json, map_integrated_slice_forces, motion_from_ancf_state, sha256_file
from ..multi_slice_real_campaign.campaign import DEFAULT_LIBRARY, OpenFOAMSliceProcess, RealProductionANCFAdapter, stage_restart_case
from ..stage4f_equilibrated_startup_v3.equilibrium import _read_manifest
from ..stage4f_three_slice_preflight.campaign import ANCF_SOURCE, MATLAB, LowReStage4FRunner, _matlab_matrix, _matlab_quote
from .contract import D_M, END_TIME_S, PARENT_CASE_ROOT, Q_INF_PA, START_TIME_S, THRESHOLDS, TOTAL_SPAN_M, U_MPS, scaled_relative

REQUIRED_TIME_FIELDS = ("U", "p", "phi", "Uf", "meshPhi", "polyMesh/points", "uniform/time")
FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
NONFINITE_RE = re.compile(r"FOAM FATAL|Floating point exception|negative volume|\bnan\b|\binf\b", re.IGNORECASE)


class VariableStepRunner(LowReStage4FRunner):
    """Use the accepted native state while making the requested dt explicit."""

    def __init__(self, work_dir: Path, manifest, *, native_resume: Path, dt_s: float, process_registry: list[dict[str, Any]]):
        super().__init__(work_dir, manifest, native_resume=native_resume)
        self.dt_s = float(dt_s)
        self.process_registry = process_registry

    def _run(self, script: str, label: str) -> None:
        if not MATLAB.is_file():
            raise RuntimeError(f"MATLAB R2021b is missing: {MATLAB}")
        log = self.work_dir / f"matlab_{self.index:03d}_{label}.log"
        self.index += 1
        self.logs.append(str(log))
        started_ns = time.time_ns()
        with log.open("w", encoding="utf-8") as stream:
            process = subprocess.Popen([str(MATLAB), "-batch", script], cwd=str(self.work_dir), stdout=stream, stderr=subprocess.STDOUT)
            record = {"kind": "matlab", "label": label, "pid": process.pid, "started_ns": started_ns, "closed": False, "return_code": None}
            self.process_registry.append(record)
            try:
                code = process.wait(timeout=240)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=10)
                record.update({"closed": True, "return_code": process.returncode, "close_method": "terminate_or_kill_after_timeout"})
                raise TimeoutError(f"MATLAB {label} timed out")
            record.update({"closed": True, "return_code": code, "close_method": "natural_exit"})
        if code != 0:
            text = log.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise RuntimeError(f"MATLAB {label} failed with code {code}: {text}")

    def _advance(self, source: Path, target: Path, forces: Sequence[Sequence[float]], label: str) -> None:
        s, t = _matlab_quote(source), _matlab_quote(target)
        script = (
            f"addpath(genpath('{_matlab_quote(ANCF_SOURCE)}')); "
            f"S=load('{s}','state'); state=S.state; state.model.time.dt={self.dt_s:.17g}; "
            f"state=ancf_advance_step(state,{_matlab_matrix(forces)},{self.dt_s:.17g}); "
            f"save('{t}','state','-v7');"
        )
        self._run(script, label)

    def predict(self, step: int, time_s: float, previous_slice_forces: Sequence[Sequence[float]]):
        result = super().predict(step, time_s, previous_slice_forces)
        history = self.work_dir / "prediction_history"
        history.mkdir(exist_ok=True)
        shutil.copy2(self.prediction_path, history / f"prediction_step{step:08d}.mat")
        return result


def _replace_dictionary(path: Path, replacements: Mapping[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        updated = re.sub(rf"^\s*{re.escape(key)}\s+[^;]+;", f"{key:<15}{value};", text, flags=re.MULTILINE)
        if updated == text:
            raise RuntimeError(f"dictionary key not found: {key} in {path}")
        text = updated
    path.write_text(text, encoding="utf-8")


def _prepare_case_skeletons(root: Path, *, dt_s: float) -> dict[int, Path]:
    cases: dict[int, Path] = {}
    for sid in range(3):
        source = PARENT_CASE_ROOT / f"slice_{sid:04d}"
        target = root / "cases" / f"slice_{sid:04d}"
        target.mkdir(parents=True, exist_ok=False)
        shutil.copytree(source / "constant", target / "constant")
        shutil.copytree(source / "system", target / "system")
        shutil.copy2(source / "multi_slice_case_config.json", target / "multi_slice_case_config.json")
        for relative in ("0", "coupling/motion", "coupling/load", "coupling/consumed", "postProcessing"):
            (target / relative).mkdir(parents=True, exist_ok=True)
        _replace_dictionary(target / "system/controlDict", {
            "startFrom": "startTime", "startTime": f"{START_TIME_S:.12g}",
            "endTime": f"{START_TIME_S + dt_s:.12g}", "deltaT": f"{dt_s:.12g}",
            "writeInterval": "1",
        })
        _replace_dictionary(target / "constant/dynamicMeshDict", {
            "sliceId": str(sid), "stepOffset": "0", "startTime": f"{START_TIME_S:.12g}",
            "couplingDeltaT": f"{dt_s:.12g}",
        })
        metadata = json.loads((target / "multi_slice_case_config.json").read_text(encoding="utf-8"))
        metadata.update({"delta_t_s": dt_s, "start_time_s": START_TIME_S, "run_id": root.name})
        atomic_write_json(target / "multi_slice_case_config.json", metadata)
        cases[sid] = target
    return cases


def _runtime_config(manifest, dt_s: float) -> RuntimeConfig:
    return RuntimeConfig(schema_version="0.2.1", case_id=manifest.case_id, dt_s=dt_s,
        timeout_s=90.0, start_time_s=START_TIME_S, coupling_iteration=0,
        coupling_scheme="explicit_weak", slice_manifest_sha256=manifest.slice_manifest_sha256)


def _native_from_checkpoint(checkpoint_path: Path) -> Path:
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    path = checkpoint_path.parent / str(payload["structure"]["runner_checkpoint_relative_path"])
    if not path.is_file() or sha256_file(path) != str(payload["structure"]["runner_checkpoint_sha256"]):
        raise RuntimeError("native ANCF checkpoint identity failed")
    return path


def _seed_records(manifest, adapter, runner, *, step: int, time_s: float) -> list[dict[str, Any]]:
    state = runner.state_view()
    return [motion_from_ancf_state(manifest, spec.slice_id, adapter.H_by_slice_id[spec.slice_id],
        state["q"], state["qdot"], state["qddot"], step=step, time_s=time_s,
        reference_position_m=(0.0, 0.0, spec.s_ref_m)).to_dict() for spec in manifest.slices]


def _motion_csv(path: Path) -> dict[str, Any]:
    with path.open("r", newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise RuntimeError(f"motion payload row count is not one: {path}")
    return rows[0]


def _foam_points(path: Path) -> list[tuple[float, float, float]]:
    text = path.read_text(encoding="utf-8", errors="strict")
    start, end = text.find("\n(", text.find("FoamFile")), text.rfind("\n)")
    if start < 0 or end <= start:
        raise RuntimeError(f"cannot parse OpenFOAM points: {path}")
    rows = [tuple(map(float, match)) for match in re.findall(rf"\(\s*({FLOAT})\s+({FLOAT})\s+({FLOAT})\s*\)", text[start:end])]
    if not rows or not all(math.isfinite(value) for row in rows for value in row):
        raise RuntimeError(f"OpenFOAM points are empty/non-finite: {path}")
    return rows


def _foam_faces(path: Path) -> list[list[int]]:
    text = path.read_text(encoding="utf-8", errors="strict")
    start, end = text.find("\n(", text.find("FoamFile")), text.rfind("\n)")
    rows = [list(map(int, item.split())) for item in re.findall(r"\d+\(([^()]*)\)", text[start:end])]
    if not rows:
        raise RuntimeError(f"cannot parse OpenFOAM faces: {path}")
    return rows


def _cylinder_patch_range(boundary: Path) -> tuple[int, int]:
    text = boundary.read_text(encoding="utf-8")
    match = re.search(r"\bcylinder\s*\{(.*?)\}", text, flags=re.DOTALL)
    if not match:
        raise RuntimeError("cylinder patch missing")
    block = match.group(1)
    count = re.search(r"nFaces\s+(\d+)\s*;", block)
    start = re.search(r"startFace\s+(\d+)\s*;", block)
    if not count or not start:
        raise RuntimeError("cylinder patch range missing")
    return int(start.group(1)), int(count.group(1))


def cylinder_center(case: Path, time_name: str) -> list[float]:
    points = _foam_points(case / time_name / "polyMesh/points")
    faces = _foam_faces(case / "constant/polyMesh/faces")
    start, count = _cylinder_patch_range(case / "constant/polyMesh/boundary")
    indices = sorted({index for face in faces[start:start + count] for index in face})
    if not indices:
        raise RuntimeError("cylinder patch has no points")
    return [sum(points[index][axis] for index in indices) / len(indices) for axis in range(3)]


def _state_motion(manifest, adapter, state: Mapping[str, Sequence[float]], sid: int, *, step: int, time_s: float) -> dict[str, Any]:
    spec = manifest.slice(sid)
    return motion_from_ancf_state(manifest, sid, adapter.H_by_slice_id[sid], state["q"], state["qdot"], state["qddot"],
        step=step, time_s=time_s, reference_position_m=(0.0, 0.0, spec.s_ref_m)).to_dict()


def _relative(actual: float, expected: float) -> float:
    return abs(actual - expected) / max(1.0, abs(actual), abs(expected))


def _force_audit(load: Mapping[str, Any]) -> dict[str, Any]:
    openfoam = [float(load[f"openfoam_force_{axis}_N"]) for axis in "xyz"]
    unit = [float(load[f"force_2d_{axis}_Npm"]) for axis in "xyz"]
    integrated = [float(load[f"force_{axis}_N"]) for axis in "xyz"]
    unit_span, length = float(load["unit_span_m"]), float(load["slice_length_m"])
    per_unit_span_scale_Npm = Q_INF_PA * D_M
    integrated_scale_N = Q_INF_PA * D_M * TOTAL_SPAN_M
    errors = []
    for axis in range(3):
        errors.append({"axis": axis, "conversion": "raw_to_unit_span",
            "relative_error": scaled_relative(unit[axis], openfoam[axis] / unit_span, per_unit_span_scale_Npm),
            "frozen_absolute_scale": per_unit_span_scale_Npm})
        errors.append({"axis": axis, "conversion": "unit_span_to_integrated_slice",
            "relative_error": scaled_relative(integrated[axis], unit[axis] * length, integrated_scale_N),
            "frozen_absolute_scale": integrated_scale_N})
    max_error = max(item["relative_error"] for item in errors)
    cd = openfoam[0] / (Q_INF_PA * D_M * unit_span)
    return {"openfoam_force_N": openfoam, "unit_span_force_Npm": unit, "integrated_slice_force_N": integrated,
        "unit_span_m": unit_span, "slice_length_m": length, "Cd": cd,
        "conversion_errors": errors, "max_relative_error": max_error,
        "passed": max_error <= THRESHOLDS["force_conversion_relative_error_max"] and abs(cd) <= THRESHOLDS["abs_cd_max"]}


def _log_audit(paths: Sequence[str]) -> dict[str, Any]:
    max_cfl = 0.0
    rows = []
    for item in paths:
        path = Path(item)
        text = path.read_text(encoding="utf-8", errors="replace")
        cfl = [float(value) for value in re.findall(r"Courant Number mean:\s+[^\s]+\s+max:\s+([-+0-9.eE]+)", text)]
        bad = NONFINITE_RE.search(text)
        row = {"path": str(path), "sha256": sha256_file(path), "has_End": "End" in text, "max_cfl": max(cfl) if cfl else None, "fatal_token": bad.group(0) if bad else None}
        row["passed"] = bool(row["has_End"] and row["max_cfl"] is not None and row["max_cfl"] < THRESHOLDS["cfl_strict_upper"] and bad is None)
        rows.append(row)
        max_cfl = max(max_cfl, max(cfl) if cfl else math.inf)
    return {"logs": rows, "max_cfl": max_cfl, "passed": bool(rows) and all(row["passed"] for row in rows)}


def _record_openfoam_processes(processes: Sequence[OpenFOAMSliceProcess], registry: list[dict[str, Any]], known: set[tuple[int, int]]) -> None:
    for process in processes:
        if process.process is None:
            continue
        key = (int(process.process.pid), int(process.process_start_ns))
        if key in known:
            for row in registry:
                if row.get("kind") == "openfoam_wsl_launcher" and (int(row["pid"]), int(row["started_ns"])) == key:
                    if process.process.poll() is not None:
                        row.update({"closed": True, "return_code": process.process.poll(), "close_method": row.get("close_method") or "natural_exit"})
                    break
            continue
        known.add(key)
        registry.append({"kind": "openfoam_wsl_launcher", "slice_id": process.slice_id, "pid": key[0], "started_ns": key[1],
            "closed": process.process.poll() is not None, "return_code": process.process.poll(), "close_method": "natural_exit" if process.process.poll() is not None else None})


def _close_processes(processes: Sequence[OpenFOAMSliceProcess], registry: list[dict[str, Any]], known: set[tuple[int, int]]) -> None:
    _record_openfoam_processes(processes, registry, known)
    for process in processes:
        process.stop()
    _record_openfoam_processes(processes, registry, known)
    by_key = {(int(row["pid"]), int(row["started_ns"])): row for row in registry if row["kind"] == "openfoam_wsl_launcher"}
    for process in processes:
        if process.process is None:
            continue
        row = by_key.get((int(process.process.pid), int(process.process_start_ns)))
        if row is not None:
            row.update({"closed": process.process.poll() is not None, "return_code": process.process.poll(), "close_method": row.get("close_method") or "stop"})


def _tension(native_path: Path) -> dict[str, float]:
    state = sio.loadmat(native_path, squeeze_me=True, struct_as_record=False)["state"]
    values = [float(value) for value in state.output.tension_N.reshape(-1)]
    if not values or not all(math.isfinite(value) for value in values):
        raise RuntimeError("ANCF tension is empty/non-finite")
    return {"minimum_N": min(values), "maximum_N": max(values)}


def run_segment(*, root: Path, branch: str, dt_s: float, first_step: int, step_count: int,
        source_checkpoint: Path, source_case_root: Path, restore_scheduler: bool,
        process_registry: list[dict[str, Any]]) -> dict[str, Any]:
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    manifest = _read_manifest()
    config = _runtime_config(manifest, dt_s)
    source_payload = json.loads(source_checkpoint.read_text(encoding="utf-8"))
    cases = _prepare_case_skeletons(root, dt_s=dt_s)
    staged = stage_restart_case(checkpoint_path=source_checkpoint, source_case_root=source_case_root, target_case_root=root / "cases")
    native = _native_from_checkpoint(source_checkpoint)
    runner = VariableStepRunner(root / "matlab", manifest, native_resume=native, dt_s=dt_s, process_registry=process_registry)
    processes: list[OpenFOAMSliceProcess] = []
    known_processes: set[tuple[int, int]] = set()
    scheduler = None
    steps: list[dict[str, Any]] = []
    error = None
    initial_state_error = None
    try:
        runner.start()
        adapter = RealProductionANCFAdapter(runner=runner, manifest=manifest,
            mesh_nodes=tuple(50.0 * index / 16 for index in range(17)), state_provider=runner.state_view,
            reference_positions_m={spec.slice_id: (0.0, 0.0, spec.s_ref_m) for spec in manifest.slices})
        actual = runner.state_view()
        expected = source_payload["structure"]
        initial_state_error = max(_relative(float(a), float(b)) for key in ("q", "qdot", "qddot") for a, b in zip(actual[key], expected[key]))
        if initial_state_error > THRESHOLDS["restart_structure_relative_error_max"]:
            raise RuntimeError(f"initial ANCF state identity failed: {initial_state_error}")
        for spec in manifest.slices:
            process = OpenFOAMSliceProcess(slice_id=spec.slice_id, case=cases[spec.slice_id], exchange_root=root / "exchange",
                manifest=manifest, runtime_config=config, library=DEFAULT_LIBRARY, run_id=f"stage4f_c_v1_{branch.lower()}")
            process.preflight(format(START_TIME_S + (first_step + 1) * dt_s, ".12g"))
            processes.append(process)
        scheduler = MultiSliceScheduler(config=MultiSliceConfig(case_id=manifest.case_id, dt_s=dt_s,
            timeout_s=config.timeout_s, start_time_s=START_TIME_S, manifest=manifest), exchange_root=root / "exchange",
            structure=adapter, slice_processes=processes, checkpoint_root=root / "checkpoints", case_root=root / "cases")
        if restore_scheduler:
            scheduler.restore_from_checkpoint(source_checkpoint)
        else:
            scheduler.previous_slice_forces_N = [[float(value) for value in row] for row in source_payload["previous_slice_forces_N"]]
            scheduler.previous_generalized_force = [float(value) for value in source_payload["previous_generalized_force"]]
        for step in range(first_step, first_step + step_count):
            current = START_TIME_S + step * dt_s
            target = START_TIME_S + (step + 1) * dt_s
            seeds = _seed_records(manifest, adapter, runner, step=step, time_s=current)
            for process, seed in zip(processes, seeds):
                process.begin_step(seed, seed_step=step)
            result = scheduler.run_step(step=step, time_s=target)
            _record_openfoam_processes(processes, process_registry, known_processes)
            for process in processes:
                process.finish_step(step, target)
            _record_openfoam_processes(processes, process_registry, known_processes)
            checkpoint = json.loads(result.checkpoint_path.read_text(encoding="utf-8"))
            checkpoint_native = result.checkpoint_path.parent / str(checkpoint["structure"]["runner_checkpoint_relative_path"])
            committed = {key: checkpoint["structure"][key] for key in ("q", "qdot", "qddot")}
            load_records = {spec.slice_id: LoadRecord.from_mapping(row, manifest.R_GL) for spec, row in zip(manifest.slices, result.integrated_slice_forces)}
            delta_q = [math.sin(index + 1) for index in range(len(checkpoint["structure"]["q"]))]
            mapping = map_integrated_slice_forces(manifest, adapter.H_by_slice_id, load_records, delta_q=delta_q, random_seed=20260817)
            virtual_work = mapping.virtual_work.to_dict() if mapping.virtual_work else {}
            force_rows = [_force_audit(row) for row in result.integrated_slice_forces]
            geometry_rows = []
            for spec, process in zip(manifest.slices, processes):
                motion = _motion_csv(root / "exchange" / f"slice_{spec.slice_id:04d}" / "motion" / f"motion_step{step:08d}_iter0000.csv")
                center = cylinder_center(process.case, format(target, ".12g"))
                mesh_error = max(abs(center[0] - float(motion["x_m"])), abs(center[1] - float(motion["y_m"])))
                corrected_motion = _state_motion(manifest, adapter, committed, spec.slice_id, step=step, time_s=target)
                position_gap = math.hypot(float(motion["x_m"]) - corrected_motion["x_m"], float(motion["y_m"]) - corrected_motion["y_m"]) / D_M
                velocity_gap = math.hypot(float(motion["vx_mps"]) - corrected_motion["vx_mps"], float(motion["vy_mps"]) - corrected_motion["vy_mps"]) / U_MPS
                geometry_rows.append({"slice_id": spec.slice_id, "cylinder_center_m": center, "target_motion_xy_m": [float(motion["x_m"]), float(motion["y_m"])],
                    "mesh_center_motion_error_m": mesh_error, "committed_predictor_position_gap_over_D": position_gap,
                    "committed_predictor_velocity_gap_over_U": velocity_gap,
                    "passed": mesh_error <= THRESHOLDS["mesh_center_motion_absolute_error_m_max"] and position_gap <= THRESHOLDS["committed_predictor_position_gap_over_D_max"] and velocity_gap <= THRESHOLDS["committed_predictor_velocity_gap_over_U_max"]})
            new_logs = [process.log_paths[-1] for process in processes]
            log_audit = _log_audit(new_logs)
            row = {"step": step, "time_s": target, "checkpoint": str(result.checkpoint_path), "checkpoint_sha256": sha256_file(result.checkpoint_path),
                "checkpoint_native": str(checkpoint_native), "integrated_slice_forces_N": [[float(item[f"force_{axis}_N"]) for axis in "xyz"] for item in result.integrated_slice_forces],
                "force_audit": force_rows, "virtual_work": virtual_work, "geometry_audit": geometry_rows,
                "log_audit": log_audit, "tension_N": _tension(checkpoint_native)}
            passed = (all(item["passed"] for item in force_rows) and all(item["passed"] for item in geometry_rows)
                and log_audit["passed"] and float(virtual_work.get("error_rel", math.inf)) <= THRESHOLDS["virtual_work_relative_error_max"])
            row["passed"] = passed
            steps.append(row)
            if not passed:
                raise RuntimeError(f"frozen hard gate failed at branch {branch} step {step}")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        _close_processes(processes, process_registry, known_processes)
        runner.shutdown()
    checkpoints = []
    if scheduler is not None:
        for path in sorted((root / "checkpoints").glob("checkpoint_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                scheduler.checkpoint_manager._validate_manifest(payload, require_status="committed", verify_files=True)
                checkpoints.append({"path": str(path), "step": int(payload["step"]), "time_s": float(payload["time_s"]), "valid": True})
            except Exception as exc:
                checkpoints.append({"path": str(path), "valid": False, "error": str(exc)})
    expected_count = step_count
    passed = error is None and len(steps) == expected_count and len(checkpoints) == expected_count and all(item["valid"] for item in checkpoints)
    summary = {"status": "passed" if passed else "blocked", "branch": branch, "dt_s": dt_s, "first_step": first_step,
        "steps_requested": step_count, "steps_completed": len(steps), "start_time_s": START_TIME_S + first_step * dt_s,
        "end_time_s": START_TIME_S + (first_step + step_count) * dt_s, "source_checkpoint": str(source_checkpoint),
        "source_checkpoint_sha256": sha256_file(source_checkpoint), "staged_restart": staged, "restored_scheduler": restore_scheduler,
        "initial_state_max_relative_error": initial_state_error, "runtime_config": config.to_dict(), "steps": steps,
        "checkpoint_audit": checkpoints, "error": error}
    atomic_write_json(root / "segment_summary.json", summary)
    return summary


def combine_branch(branch_root: Path, branch: str, segments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    steps = [row for segment in segments for row in segment["steps"]]
    checkpoints = [row for segment in segments for row in segment["checkpoint_audit"]]
    expected = 20 if branch in {"A", "B"} else 40
    passed = len(steps) == expected and len(checkpoints) == expected and all(segment["status"] == "passed" for segment in segments)
    value = {"status": "passed" if passed else "blocked", "branch": branch, "steps_completed": len(steps), "steps_requested": expected,
        "time_range_s": [START_TIME_S, END_TIME_S], "segments": [{key: segment[key] for key in ("status", "start_time_s", "end_time_s", "steps_completed", "source_checkpoint", "error")} for segment in segments],
        "steps": steps, "checkpoint_count": len(checkpoints), "checkpoint_audit": checkpoints,
        "max_cfl": max((row["log_audit"]["max_cfl"] for row in steps), default=None),
        "max_abs_Cd": max((abs(force["Cd"]) for row in steps for force in row["force_audit"]), default=None),
        "max_virtual_work_relative_error": max((float(row["virtual_work"]["error_rel"]) for row in steps), default=None),
        "max_force_conversion_relative_error": max((force["max_relative_error"] for row in steps for force in row["force_audit"]), default=None),
        "max_mesh_center_motion_error_m": max((geo["mesh_center_motion_error_m"] for row in steps for geo in row["geometry_audit"]), default=None),
        "max_committed_predictor_position_gap_over_D": max((geo["committed_predictor_position_gap_over_D"] for row in steps for geo in row["geometry_audit"]), default=None),
        "max_committed_predictor_velocity_gap_over_U": max((geo["committed_predictor_velocity_gap_over_U"] for row in steps for geo in row["geometry_audit"]), default=None)}
    atomic_write_json(branch_root / "branch_summary.json", value)
    return value
