"""Real, bounded repair for the Stage 4F three-slice dynamic startup.

The v1 preflight supplied a statically warmed field directly to a dynamic
mesh.  This module establishes a zero-motion dynamic state at 0.05 s first,
then materializes that exact state into fresh three-slice cases.  It neither
changes the formal mapping/checkpoint implementation nor mutates v1 evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from ..multi_slice_driver import MultiSliceConfig, MultiSliceScheduler, ProductionANCFAdapter
from ..multi_slice_driver.contract import RuntimeConfig, SliceExchangePaths
from ..multi_slice_mapping.mapping import MotionRecord, SliceManifest, atomic_write_json, motion_from_ancf_state, sha256_file
from ..multi_slice_real_campaign.campaign import (
    ANCF_SOURCE, DEFAULT_LIBRARY, OpenFOAMSliceProcess, RealProductionANCFAdapter,
    _matlab_matrix, _matlab_quote, _run_checked, _wsl_path,
)
from ..stage4f_three_slice_preflight.campaign import LowReStage4FRunner, _load_identity

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = PROJECT_ROOT / "cases" / "openfoam" / "multi_slice_template" / "generate_case.py"
REFERENCE_CASE = PROJECT_ROOT / "cases" / "openfoam" / "single_slice_ancf_fsi"
MATLAB = Path(r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")

STATIC_END_S = 0.045
HOT_START_S = 0.05
DT_S = 0.0025
MAX_CFL = 0.8
MAX_ABS_CD = 10.0
REQUIRED_DYNAMIC_TIME_FILES = (
    "U", "p", "phi", "Uf", "meshPhi", "polyMesh/points", "uniform/time",
)
PHYSICS = {
    "D_m": 1.0, "L_m": 50.0, "U_mps": 1.0, "rho_kgpm3": 1000.0, "nu_m2ps": 0.01, "Re": 100.0,
    "m_star": 5.0, "beta": 0.01, "top_tension_N": 2179104.0029808935,
    "E_Pa": 3227125779.2218256, "nElem": 16, "nSlices": 3,
}


def _time_name(value: float) -> str:
    return format(value, ".12g")


def _json_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _case_metadata(*, manifest: SliceManifest, config: RuntimeConfig, spec, source: Path | None, role: str) -> dict[str, Any]:
    value = {
        "schema_version": "stage4f-dynamic-startup-v2", "role": role, "source_hot_start_case": None if source is None else str(source),
        "protocol_version": "0.2.1", "case_id": manifest.case_id, "slice_id": spec.slice_id,
        "s_ref_m": spec.s_ref_m, "slice_length_m": spec.slice_length_m, "unit_span_m": spec.unit_span_m,
        "runtime_config_sha256": config.config_sha256, "slice_manifest_sha256": manifest.slice_manifest_sha256,
        "physics": dict(PHYSICS),
        # Compatibility views consumed by the unchanged OpenFOAM process
        # adapter.  They repeat, rather than replace, the v2 identity above.
        "cfd": {"diameter_m": 1.0, "freestream_mps": 1.0, "rho_kgpm3": 1000.0, "nu_m2ps": 0.01},
        "ancf": {"length_m": 50.0, "outer_diameter_m": 1.0, "inner_diameter_m": 0.9,
                 "youngs_modulus_pa": PHYSICS["E_Pa"], "top_tension_n": PHYSICS["top_tension_N"],
                 "mass_ratio": 5.0, "beta": 0.01, "nElem": 16},
    }
    value["metadata_sha256"] = _json_hash(value)
    return value


def _run_generator(*, output: Path, reference: Path, initial_time: float, start_time: float, end_time: float,
                   manifest: SliceManifest, config: RuntimeConfig, spec, role: str, static_mesh: bool = False) -> None:
    command = [
        sys.executable, str(TEMPLATE), "--output", str(output), "--reference-case", str(reference),
        "--case-id", manifest.case_id, "--slice-id", str(spec.slice_id), "--s-ref-m", format(spec.s_ref_m, ".17g"),
        "--slice-length-m", format(spec.slice_length_m, ".17g"), "--unit-span-m", format(spec.unit_span_m, ".17g"),
        "--start-time", format(start_time, ".17g"), "--end-time", format(end_time, ".17g"), "--delta-t", format(DT_S, ".17g"),
        "--initial-time", _time_name(initial_time), "--slice-manifest-sha256", manifest.slice_manifest_sha256,
        "--config-sha256", config.config_sha256, "--freestream-mps", "1", "--cfd-diameter-m", "1",
        "--fluid-density-kgpm3", "1000", "--kinematic-viscosity-m2ps", "0.01",
        "--ancf-length-m", "50", "--ancf-diameter-m", "1", "--ancf-inner-diameter-m", "0.9",
        "--youngs-modulus-pa", format(PHYSICS["E_Pa"], ".17g"), "--top-tension-n", format(PHYSICS["top_tension_N"], ".17g"),
        "--run-id", f"stage4f_dynamic_startup_v2_{role}",
    ]
    if static_mesh:
        command.append("--static-mesh")
    _run_checked(command, log_path=output.parent / f"generate_{role}.log", timeout_s=180)
    atomic_write_json(output / "stage4f_v2_metadata.json", _case_metadata(manifest=manifest, config=config, spec=spec, source=reference, role=role))


def _patch_speed(case: Path) -> None:
    path = case / "0" / "U"
    text = path.read_text(encoding="utf-8")
    path.write_text(re.sub(r"\(\s*1(?:\.0*)?\s+0\s+0\s*\)", "(1 0 0)", text), encoding="utf-8")


def _check_mesh_and_run_static(case: Path, run_id: str) -> None:
    wcase = _wsl_path(case)
    _run_checked(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", f"source /opt/openfoam10/etc/bashrc; cd '{wcase}'; checkMesh"], log_path=case / f"log.checkMesh_{run_id}", timeout_s=180)
    _run_checked(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", f"source /opt/openfoam10/etc/bashrc; cd '{wcase}'; pimpleFoam"], log_path=case / f"log.pimpleFoam_static_{run_id}", timeout_s=600)


def _zero_record(manifest: SliceManifest, spec, *, step: int, time_s: float) -> MotionRecord:
    return MotionRecord(schema_version="0.2.1", case_id=manifest.case_id, step=step, coupling_iteration=0,
            time_s=time_s, slice_id=spec.slice_id, s_ref_m=spec.s_ref_m, slice_length_m=spec.slice_length_m,
            x_ref_m=0.0, y_ref_m=0.0, z_ref_m=spec.s_ref_m, ux_m=0.0, uy_m=0.0, uz_m=0.0,
            x_m=0.0, y_m=0.0, z_m=spec.s_ref_m, vx_mps=0.0, vy_mps=0.0, vz_mps=0.0,
            ax_mps2=0.0, ay_mps2=0.0, az_mps2=0.0)


def _run_zero_dynamic_hot_start(case: Path, manifest: SliceManifest, config: RuntimeConfig, spec) -> dict[str, Any]:
    """Run actual dynamic mesh steps from 0.045 to 0.05 under zero x/y motion."""
    process = OpenFOAMSliceProcess(slice_id=spec.slice_id, case=case, exchange_root=case / "formal_warmup_exchange",
                                   manifest=manifest, runtime_config=config, library=DEFAULT_LIBRARY, run_id="stage4f_v2_zero_hot_start")
    paths = SliceExchangePaths(case / "formal_warmup_exchange", manifest.slice(spec.slice_id)); paths.ensure()
    rows: list[dict[str, Any]] = []
    try:
        for step in range(2):
            current = STATIC_END_S + step * DT_S; target = current + DT_S
            process.begin_step(_zero_record(manifest, spec, step=step, time_s=current).to_dict(), seed_step=step)
            process.publish_motion(_zero_record(manifest, spec, step=step, time_s=target), paths, manifest=manifest, runtime_config=config)
            process.wait_motion_consumed(step, target, paths=paths, manifest=manifest, runtime_config=config)
            process.wait_load_ready(step, target, paths=paths, manifest=manifest, runtime_config=config)
            process.publish_load_consumed(step, target, paths=paths, manifest=manifest, runtime_config=config)
            process.finish_step(step, target)
            force = process.last_load
            rows.append({"step": step, "time_s": target, "openfoam_force_N": list(force.openfoam_force_N),
                         "Cd": force.openfoam_force_N[0] / 500.0, "motion_xy_zero": True})
    finally:
        process.stop()
    metrics = process.log_metrics()
    if not rows or abs(rows[-1]["Cd"]) > MAX_ABS_CD:
        raise RuntimeError(f"dynamic zero-motion force scale failed: {rows[-1] if rows else 'no force'}")
    if metrics["max_cfl"] is None or metrics["max_cfl"] >= MAX_CFL:
        raise RuntimeError(f"dynamic zero-motion CFL failed: {metrics['max_cfl']}")
    return {"steps": rows, "max_cfl": metrics["max_cfl"], "logs": metrics["log_paths"], "final_time_s": HOT_START_S}


def dynamic_state_audit(case: Path, *, time_s: float = HOT_START_S) -> dict[str, Any]:
    time_dir = case / _time_name(time_s)
    files = []
    for relative in REQUIRED_DYNAMIC_TIME_FILES:
        path = time_dir / relative
        if not path.is_file():
            raise FileNotFoundError(f"missing dynamic hot-start field: {path}")
        files.append({"relative_path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    motion = case / "0" / "motionScale"
    if not motion.is_file():
        raise FileNotFoundError(motion)
    return {"time_s": time_s, "time_name": _time_name(time_s), "dynamic_time_files": files,
            "static_motionScale": {"relative_path": "0/motionScale", "bytes": motion.stat().st_size, "sha256": sha256_file(motion)}}


def _copy_hot_start(*, source: Path, target: Path, manifest: SliceManifest, config: RuntimeConfig, spec) -> dict[str, Any]:
    if target.exists():
        raise FileExistsError(target)
    source_audit = dynamic_state_audit(source)
    target.mkdir(parents=True)
    shutil.copytree(source / "constant", target / "constant")
    shutil.copytree(source / "system", target / "system")
    shutil.copytree(source / _time_name(HOT_START_S), target / _time_name(HOT_START_S))
    (target / "0").mkdir()
    shutil.copy2(source / "0" / "motionScale", target / "0" / "motionScale")
    for rel in ("coupling/motion", "coupling/load", "coupling/consumed", "postProcessing"):
        (target / rel).mkdir(parents=True, exist_ok=True)
    control = target / "system" / "controlDict"
    text = control.read_text(encoding="utf-8")
    text = re.sub(r"^startFrom\s+[^;]+;", "startFrom       startTime;", text, flags=re.MULTILINE)
    text = re.sub(r"^startTime\s+[^;]+;", f"startTime       {_time_name(HOT_START_S)};", text, flags=re.MULTILINE)
    text = re.sub(r"^endTime\s+[^;]+;", f"endTime         {_time_name(HOT_START_S + DT_S)};", text, flags=re.MULTILINE)
    control.write_text(text, encoding="utf-8")
    dynamic_mesh = target / "constant" / "dynamicMeshDict"
    mesh_text = dynamic_mesh.read_text(encoding="utf-8")
    mesh_text = re.sub(r"^\s*startTime\s+[^;]+;", f"        startTime       {_time_name(HOT_START_S)};", mesh_text, flags=re.MULTILINE)
    mesh_text = re.sub(r"^\s*sliceId\s+[^;]+;", f"        sliceId         {spec.slice_id};", mesh_text, flags=re.MULTILINE)
    dynamic_mesh.write_text(mesh_text, encoding="utf-8")
    atomic_write_json(target / "multi_slice_case_config.json", _case_metadata(manifest=manifest, config=config, spec=spec, source=source, role="formal_coupling_hot_start"))
    target_audit = dynamic_state_audit(target)
    if target_audit["dynamic_time_files"] != source_audit["dynamic_time_files"] or target_audit["static_motionScale"] != source_audit["static_motionScale"]:
        raise RuntimeError("hot-start materialization hash mismatch")
    return {"source": str(source), "target": str(target), "state": target_audit}


class HotStartANCFRunner(LowReStage4FRunner):
    """Use the already-tested Stage 4F model, but state time starts at 0.05 s."""
    def start(self) -> None:
        sref = ";".join(format(x.s_ref_m, ".17g") for x in self.manifest.slices)
        source, design, target = map(_matlab_quote, (ANCF_SOURCE, PROJECT_ROOT / "src" / "structure_ancf_matlab" / "stage4f_design_v2", self.committed_path))
        script = (f"addpath(genpath('{source}')); addpath('{design}'); c=stage4f_v2_contract(); "
                  "[state,~,~]=stage4f_v2_build_ancf(c,5,0.01,2179104.0029808935,16,3); "
                  "state.model.time.dt=0.0025; state.model.time.max_newton=50; "
                  f"state.model.coupling.s_ref_m=[{sref}].'; state.t={HOT_START_S:.17g}; save('{target}','state','-v7');")
        self._run(script, "initialize_hot_start")


def _seed_records(manifest: SliceManifest, adapter: ProductionANCFAdapter, runner: HotStartANCFRunner, step: int, time_s: float):
    state = runner.state_view()
    return [motion_from_ancf_state(manifest, x.slice_id, adapter.H_by_slice_id[x.slice_id], state["q"], state["qdot"], state["qddot"],
            step=step, time_s=time_s, reference_position_m=(0.0, 0.0, x.s_ref_m)).to_dict() for x in manifest.slices]


def run_dynamic_startup_preflight(root: Path, protocol_path: Path, *, steps: int = 3) -> dict[str, Any]:
    if steps < 1 or steps > 3:
        raise ValueError("Stage 4F-B-v2 permits only one to three coupling steps")
    parent_manifest, parent_config = _load_identity(protocol_path)
    config = RuntimeConfig(schema_version="0.2.1", case_id=parent_manifest.case_id, dt_s=DT_S, timeout_s=60.0,
                           start_time_s=HOT_START_S, coupling_iteration=0, coupling_scheme="explicit_weak",
                           slice_manifest_sha256=parent_manifest.slice_manifest_sha256)
    hot_config = RuntimeConfig(schema_version="0.2.1", case_id=parent_manifest.case_id, dt_s=DT_S, timeout_s=60.0,
                               start_time_s=STATIC_END_S, coupling_iteration=0, coupling_scheme="explicit_weak",
                               slice_manifest_sha256=parent_manifest.slice_manifest_sha256)
    root.mkdir(parents=True, exist_ok=False)
    identity = {"parent_runtime_config_sha256": parent_config.config_sha256, "dynamic_warmup_runtime_config": hot_config.to_dict(),
                "hot_start_runtime_config": config.to_dict(),
                "manifest": parent_manifest.to_dict(), "physics": PHYSICS, "hot_start_time_s": HOT_START_S,
                "claim_boundary": "three_step_preflight_only_no_free_viv_no_lock_in_no_experimental_validation"}
    identity["identity_sha256"] = _json_hash(identity)
    atomic_write_json(root / "v2_identity.json", identity)
    spec0 = parent_manifest.slices[0]
    static_case = root / "static_warmup" / "slice_0000"
    _run_generator(output=static_case, reference=REFERENCE_CASE, initial_time=0.0, start_time=0.0, end_time=STATIC_END_S,
                   manifest=parent_manifest, config=config, spec=spec0, role="static_045", static_mesh=True)
    _patch_speed(static_case); _check_mesh_and_run_static(static_case, "stage4f_v2")
    dynamic_case = root / "dynamic_zero_warmup" / "slice_0000"
    _run_generator(output=dynamic_case, reference=static_case, initial_time=STATIC_END_S, start_time=STATIC_END_S, end_time=HOT_START_S,
                   manifest=parent_manifest, config=hot_config, spec=spec0, role="dynamic_zero_050")
    hot_start = _run_zero_dynamic_hot_start(dynamic_case, parent_manifest, hot_config, spec0)
    state_audit = dynamic_state_audit(dynamic_case)
    atomic_write_json(root / "dynamic_hot_start_audit.json", {"hot_start": hot_start, "state": state_audit, "abs_cd_limit": MAX_ABS_CD,
                      "force_scale_passed": abs(hot_start["steps"][-1]["Cd"]) <= MAX_ABS_CD})
    cases = {spec.slice_id: root / "cases" / f"slice_{spec.slice_id:04d}" for spec in parent_manifest.slices}
    materials = [_copy_hot_start(source=dynamic_case, target=cases[spec.slice_id], manifest=parent_manifest, config=config, spec=spec) for spec in parent_manifest.slices]
    atomic_write_json(root / "hot_start_materialization.json", {"items": materials})
    runner = HotStartANCFRunner(root / "matlab", parent_manifest)
    processes: list[OpenFOAMSliceProcess] = []; results: list[dict[str, Any]] = []; error: str | None = None; scheduler = None
    try:
        runner.start()
        adapter = RealProductionANCFAdapter(runner=runner, manifest=parent_manifest, mesh_nodes=tuple(50*i/16 for i in range(17)),
                    state_provider=runner.state_view, reference_positions_m={x.slice_id:(0.0,0.0,x.s_ref_m) for x in parent_manifest.slices})
        for spec in parent_manifest.slices:
            process=OpenFOAMSliceProcess(slice_id=spec.slice_id, case=cases[spec.slice_id], exchange_root=root / "exchange", manifest=parent_manifest,
                runtime_config=config, library=DEFAULT_LIBRARY, run_id="stage4f_dynamic_startup_v2"); processes.append(process)
        scheduler=MultiSliceScheduler(config=MultiSliceConfig(case_id=parent_manifest.case_id, dt_s=DT_S, timeout_s=config.timeout_s,
            start_time_s=HOT_START_S, manifest=parent_manifest), exchange_root=root / "exchange", structure=adapter, slice_processes=processes,
            checkpoint_root=root / "checkpoints", case_root=root / "cases")
        for step in range(steps):
            current=HOT_START_S+step*DT_S; target=current+DT_S
            for process, seed in zip(processes, _seed_records(parent_manifest, adapter, runner, step, current)): process.begin_step(seed, seed_step=step)
            result=scheduler.run_step(step=step, time_s=target)
            for process in processes: process.finish_step(step, target)
            forces=[[x["force_x_N"],x["force_y_N"],x["force_z_N"]] for x in result.integrated_slice_forces]
            if any(abs(row[0]) / (500.0 * (50.0/3.0)) > MAX_ABS_CD for row in forces): raise RuntimeError("coupled force scale exceeded Cd limit")
            results.append({"step":step,"time_s":target,"checkpoint":str(result.checkpoint_path),"forces_N":forces,"state":"committed"})
        if max(p.log_metrics()["max_cfl"] or 0.0 for p in processes) >= MAX_CFL: raise RuntimeError("coupled CFL limit")
    except Exception as exc:
        error=str(exc)
    finally:
        for process in processes: process.stop()
        runner.shutdown()
    checkpoints=[]
    if scheduler:
        for path in sorted((root / "checkpoints").glob("checkpoint_*.json")):
            try:
                value=json.loads(path.read_text(encoding="utf-8")); scheduler.checkpoint_manager._validate_manifest(value, require_status="committed", verify_files=True)
                checkpoints.append({"path":str(path),"step":value["step"],"valid":True})
            except Exception as exc: checkpoints.append({"path":str(path),"valid":False,"error":str(exc)})
    cfl=[p.log_metrics()["max_cfl"] for p in processes if p.log_metrics()["max_cfl"] is not None]
    summary={"status":"completed" if error is None and len(results)==steps and all(x["valid"] for x in checkpoints) else "blocked", "error":error,
             "steps_completed":len(results),"steps_requested":steps,"results":results,"checkpoint_audit":checkpoints,"max_cfl":max(cfl) if cfl else None,
             "logs":[x for p in processes for x in p.log_metrics()["log_paths"]],"matlab_logs":runner.logs,"identity":identity,
             "dynamic_hot_start_passed":True,"free_viv_claim":False,"no_lock_in_claim":True,"no_experimental_validation_claim":True}
    atomic_write_json(root / "real_run_summary.json", summary)
    return summary
