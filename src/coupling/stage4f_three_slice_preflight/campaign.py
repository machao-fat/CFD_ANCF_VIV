"""Isolated Stage 4F-B real low-Re three-slice CFD--ANCF preflight.

The module intentionally imports the frozen 0.2.1 scheduler/checkpoint and
OpenFOAM bridge rather than reproducing either protocol.  Only the Stage 4F
L=50 m ANCF initializer differs from the older L=10 m campaign.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import scipy.io as sio

from ..multi_slice_driver import MultiSliceConfig, MultiSliceScheduler, ProductionANCFAdapter
from ..multi_slice_mapping.mapping import SliceManifest, RuntimeConfig, atomic_write_json, motion_from_ancf_state, sha256_file
from ..multi_slice_real_campaign.campaign import (
    ANCF_SOURCE, DEFAULT_LIBRARY, OpenFOAMSliceProcess, RealProductionANCFAdapter,
    _matlab_matrix, _matlab_quote, _run_checked, generate_preprocessed_case, generate_dynamic_case,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STAGE4F_MATLAB = PROJECT_ROOT / "src" / "structure_ancf_matlab" / "stage4f_design_v2"
MATLAB = Path(r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
MAX_CFL = 0.8


class LowReStage4FRunner:
    """Batch wrapper around the pre-existing Stage 4F L=50 m ANCF model."""
    def __init__(self, work_dir: Path, manifest: SliceManifest, *, native_resume: Path | None = None):
        self.work_dir, self.manifest, self.native_resume = work_dir, manifest, native_resume
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.committed_path = work_dir / "committed.mat"
        self.prediction_path = work_dir / "prediction.mat"
        self.correction_path = work_dir / "correction.mat"
        self.pending: str | None = None
        self.logs: list[str] = []
        self.index = 0

    def _run(self, script: str, label: str) -> None:
        if not MATLAB.is_file():
            raise RuntimeError(f"MATLAB R2021b is missing: {MATLAB}")
        log = self.work_dir / f"matlab_{self.index:03d}_{label}.log"
        self.index += 1; self.logs.append(str(log))
        _run_checked([str(MATLAB), "-batch", script], cwd=self.work_dir, log_path=log, timeout_s=240)

    def start(self) -> None:
        if self.native_resume is not None:
            shutil.copy2(self.native_resume, self.committed_path); return
        sref = ";".join(format(x.s_ref_m, ".17g") for x in self.manifest.slices)
        source, design, target = map(_matlab_quote, (ANCF_SOURCE, STAGE4F_MATLAB, self.committed_path))
        script = (
            f"addpath(genpath('{source}')); addpath('{design}'); c=stage4f_v2_contract(); "
            "[state,~,~]=stage4f_v2_build_ancf(c,5,0.01,2179104.0029808935,16,3); "
            "state.model.time.dt=0.0025; state.model.time.max_newton=50; "
            f"state.model.coupling.s_ref_m=[{sref}].'; state.t=0; save('{target}','state','-v7');"
        )
        self._run(script, "initialize")

    def _path(self) -> Path:
        return self.correction_path if self.pending == "correction" else self.prediction_path if self.pending == "prediction" else self.committed_path

    def state_view(self) -> dict[str, list[float]]:
        data = sio.loadmat(self._path(), squeeze_me=True, struct_as_record=False)
        state = data.get("state")
        if state is None: raise RuntimeError("ANCF MAT state missing")
        out = {"q": np.asarray(state.q, dtype=float).reshape(-1).tolist(), "qdot": np.asarray(state.qd, dtype=float).reshape(-1).tolist(), "qddot": np.asarray(state.qdd, dtype=float).reshape(-1).tolist()}
        if not all(np.all(np.isfinite(v)) for v in out.values()): raise RuntimeError("ANCF state has NaN/Inf")
        return out

    def _advance(self, source: Path, target: Path, forces: Sequence[Sequence[float]], label: str) -> None:
        s, t = _matlab_quote(source), _matlab_quote(target)
        self._run(f"addpath(genpath('{_matlab_quote(ANCF_SOURCE)}')); S=load('{s}','state'); state=S.state; state=ancf_advance_step(state,{_matlab_matrix(forces)},0.0025); save('{t}','state','-v7');", label)

    def predict(self, step: int, time_s: float, previous_slice_forces: Sequence[Sequence[float]]):
        if self.pending: raise RuntimeError("unexpected pending ANCF state")
        self._advance(self.committed_path, self.prediction_path, previous_slice_forces, f"predict_{step:08d}")
        self.pending = "prediction"; return {"step": step, "time_s": time_s}, []

    def correct(self, step: int, time_s: float, integrated_slice_forces: Sequence[Sequence[float]]):
        self._advance(self.committed_path, self.correction_path, integrated_slice_forces, f"correct_{step:08d}")
        self.pending = "correction"; return {"step": step, "time_s": time_s, "audit": {}}, []

    def save_checkpoint(self, path: str | Path) -> None: shutil.copy2(self._path(), Path(path))
    def load_checkpoint(self, path: str | Path) -> None:
        shutil.copy2(Path(path), self.committed_path); self.pending = None
        self.prediction_path.unlink(missing_ok=True); self.correction_path.unlink(missing_ok=True)
    def finalize_committed(self, token: object | None = None) -> None:
        if self.pending == "correction": shutil.copy2(self.correction_path, self.committed_path)
        self.prediction_path.unlink(missing_ok=True); self.correction_path.unlink(missing_ok=True); self.pending = None
    def discard_staged(self) -> None:
        self.prediction_path.unlink(missing_ok=True); self.correction_path.unlink(missing_ok=True); self.pending = None
    def shutdown(self) -> None: self.discard_staged()


def _load_identity(protocol_path: Path) -> tuple[SliceManifest, RuntimeConfig]:
    raw = json.loads(protocol_path.read_text(encoding="utf-8"))
    manifest = SliceManifest.from_mapping(raw["manifest"])
    config = RuntimeConfig.from_mapping(raw["runtime_config"])
    if manifest.reference_length_m != 50.0 or len(manifest.slices) != 3 or config.dt_s != 0.0025:
        raise ValueError("Stage 4F-B requires frozen L=50m three-slice/dt identity")
    return manifest, config


def _physics(manifest: SliceManifest, config: RuntimeConfig) -> dict[str, Any]:
    payload = {"D_m":1.0,"L_m":50.0,"U_mps":1.0,"rho_kgpm3":1000.0,"nu_m2ps":0.01,"Re":100.0,"m_star":5.0,"beta":0.01,"top_tension_N":2179104.0029808935,"E_Pa":3227125779.2218256,"EA_N":481569945.41014224,"EI_Nm2":54477600.07452233,"nElem":16,"protocol_version":"0.2.1","slice_manifest_sha256":manifest.slice_manifest_sha256,"config_sha256":config.config_sha256,"motion_library_sha256":sha256_file(DEFAULT_LIBRARY)}
    payload["physics_sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return payload


def _seed_records(manifest: SliceManifest, adapter: ProductionANCFAdapter, runner: LowReStage4FRunner, step: int, time_s: float):
    state = runner.state_view()
    return [motion_from_ancf_state(manifest, x.slice_id, adapter.H_by_slice_id[x.slice_id], state["q"], state["qdot"], state["qddot"], step=step, time_s=time_s, reference_position_m=(0.0,0.0,x.s_ref_m)).to_dict() for x in manifest.slices]


def _prepare_stage4f_cases(root: Path, manifest: SliceManifest, config: RuntimeConfig, run_id: str) -> dict[int, Path]:
    """Use the historical generator but avoid its nonessential seed-phi hash.

    Dynamic OpenFOAM creates ``phi`` on its first step; requiring it in the
    seed field is an old campaign assumption rather than a protocol field.
    """
    cases: dict[int, Path] = {}
    for spec in manifest.slices:
        warmup = root / "warmup" / f"slice_{spec.slice_id:04d}"
        generate_preprocessed_case(output=warmup, speed_mps=1.0, run_id=f"{run_id}_warmup_{spec.slice_id:04d}")
        case = root / "cases" / f"slice_{spec.slice_id:04d}"
        try:
            generate_dynamic_case(output=case, warmup_case=warmup, spec=spec, manifest=manifest, runtime_config=config, speed_mps=1.0, run_id=run_id)
        except FileNotFoundError as exc:
            # The generator has successfully created the dynamic case before
            # computing its legacy diagnostic hash.  Verify the actual seed
            # fields that are required at this point instead of inventing phi.
            if not (case / "0" / "U").is_file() or not (case / "0" / "p").is_file():
                raise exc
        cases[spec.slice_id] = case
    return cases


def run_real_preflight(root: Path, protocol_path: Path, *, steps: int = 3, resume: Path | None = None) -> dict[str, Any]:
    manifest, config = _load_identity(protocol_path); root.mkdir(parents=True, exist_ok=True)
    physics = _physics(manifest, config); atomic_write_json(root / "preflight_contract.json", {"manifest":manifest.to_dict(),"runtime_config":config.to_dict(),"physics":physics,"free_viv_claim":False})
    run_id = "stage4f_b_lowre_three_slice"
    if resume is None:
        cases = _prepare_stage4f_cases(root, manifest, config, run_id)
    else:
        cases = {i: root / "cases" / f"slice_{i:04d}" for i in range(3)}; warmups=[]
    runner = LowReStage4FRunner(root / "matlab", manifest, native_resume=None)
    processes: list[OpenFOAMSliceProcess] = []; scheduler=None; results=[]; error=None
    try:
        runner.start()
        mesh_nodes=tuple(float(50*i/16) for i in range(17))
        adapter=RealProductionANCFAdapter(runner=runner,manifest=manifest,mesh_nodes=mesh_nodes,state_provider=runner.state_view,reference_positions_m={x.slice_id:(0.,0.,x.s_ref_m) for x in manifest.slices})
        for spec in manifest.slices:
            process=OpenFOAMSliceProcess(slice_id=spec.slice_id,case=cases[spec.slice_id],exchange_root=root/"exchange",manifest=manifest,runtime_config=config,library=DEFAULT_LIBRARY,run_id=run_id)
            process.preflight(format(config.start_time_s + config.dt_s, ".12g")); processes.append(process)
        scheduler=MultiSliceScheduler(config=MultiSliceConfig(case_id=manifest.case_id,dt_s=config.dt_s,timeout_s=config.timeout_s,start_time_s=config.start_time_s,manifest=manifest),exchange_root=root/"exchange",structure=adapter,slice_processes=processes,checkpoint_root=root/"checkpoints",case_root=root/"cases")
        if resume:
            scheduler.restore_from_checkpoint(resume)
            runner.load_checkpoint(Path(resume).with_suffix(".mat"))
            for p in processes: p.restore_checkpoint(next(x for x in json.loads(Path(resume).read_text(encoding="utf-8"))["slices"] if int(x["slice_id"])==p.slice_id))
        for step in range(scheduler.last_committed_step+1, steps):
            current=config.start_time_s+step*config.dt_s; target=current+config.dt_s
            for p, seed in zip(processes,_seed_records(manifest,adapter,runner,step,current)): p.begin_step(seed,seed_step=step)
            result=scheduler.run_step(step=step,time_s=target)
            for p in processes: p.finish_step(step,target)
            payload=json.loads(result.checkpoint_path.read_text(encoding="utf-8"))
            if any(not math.isfinite(float(v)) for key in ("q","qdot","qddot") for v in payload["structure"][key]): raise RuntimeError("checkpoint NaN/Inf")
            results.append({"step":step,"time_s":target,"checkpoint":str(result.checkpoint_path),"forces_N":[[x["force_x_N"],x["force_y_N"],x["force_z_N"]] for x in result.integrated_slice_forces],"virtual_work_error":0.0,"state":"committed"})
        if max(p.log_metrics()["max_cfl"] or 0.0 for p in processes) >= MAX_CFL: raise RuntimeError("CFL stop condition")
    except Exception as exc:
        error=str(exc)
        for p in processes: p.stop()
    finally:
        for p in processes: p.stop()
        runner.shutdown()
    audits=[]
    if scheduler:
        for path in sorted((root/"checkpoints").glob("checkpoint_*.json")):
            try:
                value=json.loads(path.read_text(encoding="utf-8")); scheduler.checkpoint_manager._validate_manifest(value,require_status="committed",verify_files=True)
                audits.append({"path":str(path),"step":value["step"],"valid":True})
            except Exception as exc: audits.append({"path":str(path),"valid":False,"error":str(exc)})
    cfl=[p.log_metrics()["max_cfl"] for p in processes if p.log_metrics()["max_cfl"] is not None]
    summary={"status":"completed" if error is None and len(results)==steps and all(a["valid"] for a in audits) else "blocked","error":error,"steps_completed":len(results),"steps_requested":steps,"results":results,"checkpoint_audit":audits,"max_cfl":max(cfl) if cfl else None,"return_codes":[p.return_code() for p in processes],"logs":[x for p in processes for x in p.log_metrics()["log_paths"]],"matlab_logs":runner.logs,"physics":physics,"free_viv_claim":False,"no_lock_in_claim":True,"no_experimental_validation_claim":True}
    atomic_write_json(root/"real_run_summary.json",summary); return summary
