"""The bounded three-step Stage 4F-B-v5 equilibrated CFD--ANCF preflight."""
from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path
from typing import Any

from ..multi_slice_driver import MultiSliceConfig, MultiSliceScheduler
from ..multi_slice_mapping.mapping import LoadRecord, RuntimeConfig, atomic_write_json, map_integrated_slice_forces, motion_from_ancf_state, sha256_file
from ..multi_slice_real_campaign.campaign import DEFAULT_LIBRARY, OpenFOAMSliceProcess, RealProductionANCFAdapter, stage_restart_case
from ..stage4f_equilibrated_startup_v3.equilibrium import _read_manifest
from ..stage4f_three_slice_preflight.campaign import LowReStage4FRunner

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TERMINAL_AUDIT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_fixed_point_v5" / "terminal_iteration2" / "terminal_hold_audit.json"
STATIC_AUDIT = PROJECT_ROOT / "results" / "12_stage4f_fixed_point_v5" / "iteration2_exact_hold" / "fixed_point_static_audit.json"
START_TIME_S = 1.5
DT_S = 0.0025
STEPS = 3
MAX_CFL = .8
MAX_ABS_CD = 10.0
HOTSTART_CASE_METADATA = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_dynamic_startup_v2" / "run_20260817_dynamic_hotstart_v2_attempt6" / "dynamic_zero_warmup" / "slice_0000" / "multi_slice_case_config.json"


class EquilibratedRunner(LowReStage4FRunner):
    def __init__(self, work_dir: Path, manifest, source_state: Path):
        super().__init__(work_dir, manifest, native_resume=source_state)
        self.source_state = source_state

    def start(self) -> None:
        source = str(self.source_state.resolve()).replace("\\", "/").replace("'", "''")
        target = str(self.committed_path.resolve()).replace("\\", "/").replace("'", "''")
        self._run(f"S=load('{source}','state'); state=S.state; state.t={START_TIME_S:.17g}; state.step=0; save('{target}','state','-v7');", "initialize_equilibrated")


def _copy_cases(root: Path, terminal: dict[str, Any]) -> dict[int, Path]:
    cases: dict[int, Path] = {}
    for item in terminal["slices"]:
        sid = int(item["slice_id"]); source = Path(item["case"]); target = root / "cases" / f"slice_{sid:04d}"
        target.mkdir(parents=True); shutil.copytree(source / "constant", target / "constant"); shutil.copytree(source / "system", target / "system")
        shutil.copytree(source / f"{START_TIME_S:.12g}", target / f"{START_TIME_S:.12g}")
        (target / "0").mkdir(); shutil.copy2(source / "0" / "motionScale", target / "0" / "motionScale")
        # The terminal hold preserves only physical fields.  The independent
        # original metadata supplies the immutable freestream value consumed
        # by OpenFOAMSliceProcess; it is not a time-state artifact.
        shutil.copy2(HOTSTART_CASE_METADATA, target / "multi_slice_case_config.json")
        for relative in ("coupling/motion", "coupling/load", "coupling/consumed", "postProcessing"):
            (target / relative).mkdir(parents=True, exist_ok=True)
        control = target / "system" / "controlDict"; text = control.read_text(encoding="utf-8")
        for key, value in {"startFrom":"startTime", "startTime":f"{START_TIME_S:.12g}", "endTime":f"{START_TIME_S + DT_S:.12g}", "writeInterval":"1"}.items():
            text = re.sub(rf"^{key}\s+[^;]+;", f"{key:<15}{value};", text, flags=re.MULTILINE)
        control.write_text(text, encoding="utf-8")
        dynamic = target / "constant" / "dynamicMeshDict"; text = dynamic.read_text(encoding="utf-8")
        text = re.sub(r"^\s*startTime\s+[^;]+;", f"        startTime       {START_TIME_S:.12g};", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*sliceId\s+[^;]+;", f"        sliceId         {sid};", text, flags=re.MULTILINE)
        dynamic.write_text(text, encoding="utf-8"); cases[sid] = target
    return cases


def _seeds(manifest, adapter, runner, step: int, time_s: float):
    state = runner.state_view()
    return [motion_from_ancf_state(manifest, spec.slice_id, adapter.H_by_slice_id[spec.slice_id], state["q"], state["qdot"], state["qddot"], step=step, time_s=time_s, reference_position_m=(0., 0., spec.s_ref_m)).to_dict() for spec in manifest.slices]


def run_formal_preflight(root: Path, terminal_audit_path: Path = TERMINAL_AUDIT, static_audit_path: Path = STATIC_AUDIT) -> dict[str, Any]:
    if root.exists(): raise FileExistsError(root)
    terminal = json.loads(terminal_audit_path.read_text(encoding="utf-8")); static = json.loads(static_audit_path.read_text(encoding="utf-8"))
    if terminal.get("status") != "passed" or static.get("status") != "passed" or terminal.get("exact_alpha") != 1.0:
        raise ValueError("formal preflight requires accepted exact-geometry terminal state")
    manifest = _read_manifest(); config = RuntimeConfig(schema_version="0.2.1", case_id=manifest.case_id, dt_s=DT_S, timeout_s=90., start_time_s=START_TIME_S, coupling_iteration=0, coupling_scheme="explicit_weak", slice_manifest_sha256=manifest.slice_manifest_sha256)
    root.mkdir(parents=True); cases = _copy_cases(root, terminal); runner = EquilibratedRunner(root / "matlab", manifest, Path(static["state_mat"])); processes=[]; scheduler=None; results=[]; error=None
    try:
        runner.start(); adapter = RealProductionANCFAdapter(runner=runner, manifest=manifest, mesh_nodes=tuple(50*i/16 for i in range(17)), state_provider=runner.state_view, reference_positions_m={spec.slice_id:(0.,0.,spec.s_ref_m) for spec in manifest.slices})
        initial = _seeds(manifest, adapter, runner, 0, START_TIME_S)
        expected = static["slice_motion"]
        identity_error = max(abs(initial[sid][field] - expected[field][sid]) for sid in range(3) for field in ("x_m","y_m","z_m","vx_mps","vy_mps","vz_mps","ax_mps2","ay_mps2","az_mps2"))
        if identity_error > 1e-12: raise RuntimeError(f"ANCF/CFD initial motion identity failed: {identity_error}")
        for spec in manifest.slices:
            process=OpenFOAMSliceProcess(slice_id=spec.slice_id, case=cases[spec.slice_id], exchange_root=root/"exchange", manifest=manifest, runtime_config=config, library=DEFAULT_LIBRARY, run_id="stage4f_b5")
            process.preflight(format(START_TIME_S + DT_S, ".12g")); processes.append(process)
        scheduler=MultiSliceScheduler(config=MultiSliceConfig(case_id=manifest.case_id,dt_s=DT_S,timeout_s=config.timeout_s,start_time_s=START_TIME_S,manifest=manifest),exchange_root=root/"exchange",structure=adapter,slice_processes=processes,checkpoint_root=root/"checkpoints",case_root=root/"cases")
        scheduler.previous_slice_forces_N = [list(row) for row in static["integrated_slice_force_N"]]
        for step in range(STEPS):
            target = START_TIME_S + (step + 1) * DT_S
            for process, seed in zip(processes, _seeds(manifest, adapter, runner, step, START_TIME_S + step * DT_S)): process.begin_step(seed, seed_step=step)
            result=scheduler.run_step(step=step,time_s=target)
            for process in processes: process.finish_step(step,target)
            forces=[[float(row["force_x_N"]),float(row["force_y_N"]),float(row["force_z_N"])] for row in result.integrated_slice_forces]
            if any(abs(row[0])/(500.*spec.slice_length_m)>MAX_ABS_CD for row,spec in zip(forces,manifest.slices)): raise RuntimeError("force-scale hard gate failed")
            load_records = {spec.slice_id: LoadRecord.from_mapping(row, manifest.R_GL) for spec, row in zip(manifest.slices, result.integrated_slice_forces)}
            mapping=map_integrated_slice_forces(manifest,adapter.H_by_slice_id,load_records,delta_q=[math.sin(index+1) for index in range(len(result.audit["generalized_force_from_A_Ht"]))],random_seed=20260817)
            vw=mapping.virtual_work.to_dict() if mapping.virtual_work else {}
            if vw.get("error_rel", 1.) > 1e-12: raise RuntimeError("H/H^T virtual-work hard gate failed")
            results.append({"step":step,"time_s":target,"integrated_slice_forces_N":forces,"checkpoint":str(result.checkpoint_path),"audit":dict(result.audit),"virtual_work":vw})
        if max(item.log_metrics()["max_cfl"] or 0. for item in processes) >= MAX_CFL: raise RuntimeError("CFL hard gate failed")
    except Exception as exc:
        error=str(exc)
        for item in processes: item.stop()
    finally:
        for item in processes: item.stop()
        runner.shutdown()
    checkpoints=[]
    if scheduler:
        for path in sorted((root/"checkpoints").glob("checkpoint_*.json")):
            try:
                payload=json.loads(path.read_text(encoding="utf-8")); scheduler.checkpoint_manager._validate_manifest(payload,require_status="committed",verify_files=True); checkpoints.append({"path":str(path),"step":payload["step"],"valid":True})
            except Exception as exc: checkpoints.append({"path":str(path),"valid":False,"error":str(exc)})
    max_cfl=max([item.log_metrics()["max_cfl"] or 0. for item in processes],default=None)
    value={"status":"passed" if error is None and len(results)==STEPS and len(checkpoints)==STEPS and all(item["valid"] for item in checkpoints) else "blocked","error":error,"start_time_s":START_TIME_S,"steps":results,"checkpoints":checkpoints,"max_cfl":max_cfl,"initial_motion_identity_error_m":locals().get("identity_error"),"runtime_config":config.to_dict(),"terminal_audit_sha256":sha256_file(terminal_audit_path),"static_audit_sha256":sha256_file(static_audit_path),"restart_authorized":error is None and len(results)==STEPS and len(checkpoints)==STEPS}
    atomic_write_json(root/"formal_preflight_summary.json",value); return value


def run_restart_one_plus_two(root: Path, source_root: Path) -> dict[str, Any]:
    """Restore committed step 0 into fresh cases and execute only steps 1--2."""
    if root.exists(): raise FileExistsError(root)
    source_summary=json.loads((source_root/"formal_preflight_summary.json").read_text(encoding="utf-8"))
    if source_summary.get("status") != "passed" or not source_summary.get("restart_authorized"):
        raise ValueError("source preflight does not authorize restart")
    checkpoint=Path(source_summary["steps"][0]["checkpoint"]); manifest=_read_manifest(); config=RuntimeConfig(schema_version="0.2.1",case_id=manifest.case_id,dt_s=DT_S,timeout_s=90.,start_time_s=START_TIME_S,coupling_iteration=0,coupling_scheme="explicit_weak",slice_manifest_sha256=manifest.slice_manifest_sha256)
    payload=json.loads(checkpoint.read_text(encoding="utf-8")); native=checkpoint.parent / str(payload["structure"]["runner_checkpoint_relative_path"])
    root.mkdir(parents=True); terminal=json.loads(TERMINAL_AUDIT.read_text(encoding="utf-8")); cases=_copy_cases(root,terminal)
    staged=stage_restart_case(checkpoint_path=checkpoint,source_case_root=source_root/"cases",target_case_root=root/"cases")
    runner=LowReStage4FRunner(root/"matlab",manifest,native_resume=native); processes=[]; scheduler=None; rows=[]; error=None
    try:
        runner.start(); adapter=RealProductionANCFAdapter(runner=runner,manifest=manifest,mesh_nodes=tuple(50*i/16 for i in range(17)),state_provider=runner.state_view,reference_positions_m={spec.slice_id:(0.,0.,spec.s_ref_m) for spec in manifest.slices})
        for spec in manifest.slices:
            process=OpenFOAMSliceProcess(slice_id=spec.slice_id,case=cases[spec.slice_id],exchange_root=root/"exchange",manifest=manifest,runtime_config=config,library=DEFAULT_LIBRARY,run_id="stage4f_b5_restart")
            process.preflight("0"); processes.append(process)
        scheduler=MultiSliceScheduler(config=MultiSliceConfig(case_id=manifest.case_id,dt_s=DT_S,timeout_s=config.timeout_s,start_time_s=START_TIME_S,manifest=manifest),exchange_root=root/"exchange",structure=adapter,slice_processes=processes,checkpoint_root=root/"checkpoints",case_root=root/"cases")
        scheduler.restore_from_checkpoint(checkpoint); runner.load_checkpoint(native)
        for process in processes: process.restore_checkpoint(next(item for item in payload["slices"] if int(item["slice_id"]) == process.slice_id))
        for step in (1,2):
            target=START_TIME_S+(step+1)*DT_S
            for process,seed in zip(processes,_seeds(manifest,adapter,runner,step,START_TIME_S+step*DT_S)): process.begin_step(seed,seed_step=step)
            result=scheduler.run_step(step=step,time_s=target)
            for process in processes: process.finish_step(step,target)
            rows.append({"step":step,"checkpoint":str(result.checkpoint_path),"forces_N":[[float(x["force_x_N"]),float(x["force_y_N"]),float(x["force_z_N"])] for x in result.integrated_slice_forces]})
    except Exception as exc:
        error=str(exc)
        for process in processes: process.stop()
    finally:
        for process in processes: process.stop()
        runner.shutdown()
    comparison=[]
    for row in rows:
        original=Path(source_summary["steps"][row["step"]]["checkpoint"]); restarted=Path(row["checkpoint"])
        left=json.loads(original.read_text(encoding="utf-8"))["structure"]; right=json.loads(restarted.read_text(encoding="utf-8"))["structure"]
        error_rel=max(abs(float(a)-float(b))/max(1.,abs(float(a)),abs(float(b))) for key in ("q","qdot","qddot") for a,b in zip(left[key],right[key]))
        comparison.append({"step":row["step"],"state_max_relative_error":error_rel,"passed":error_rel<=1e-10})
    value={"status":"passed" if error is None and len(rows)==2 and all(item["passed"] for item in comparison) else "blocked","error":error,"source_checkpoint":str(checkpoint),"staged_restart":staged,"steps":rows,"state_comparison":comparison,"max_cfl":max([p.log_metrics()["max_cfl"] or 0. for p in processes],default=None)}
    atomic_write_json(root/"restart_one_plus_two_summary.json",value); return value
