"""Stateful production-adapter engine for one continuous D1 or D2 branch."""
from __future__ import annotations

import json
import math
import os
import shutil
import time
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..multi_slice_driver import MultiSliceConfig, MultiSliceScheduler
from ..multi_slice_mapping.mapping import LoadRecord, map_integrated_slice_forces, sha256_file
from ..multi_slice_real_campaign.campaign import OpenFOAMSliceProcess, RealProductionANCFAdapter, stage_restart_case
from ..stage4f_equilibrated_startup_v3.equilibrium import _read_manifest
from ..stage4f_three_slice_short_window_v1_repair2 import runner as r2
from ..stage4f_three_slice_short_window_v1_repair2.contract import D_M, U_MPS
from .contract import SLICE_IDS, START_TIME_S
from ..stage4f_three_slice_timestep_diagnostic_v2.real_runner import normalize_process_record, stamp_process_end

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LIBRARY = PROJECT_ROOT / "runtime" / "stage4f_three_slice_timestep_diagnostic_v3" / "lib" / "libancfFileMotion.so"


def _utc(ns: int | None = None) -> str:
    stamp = time.time_ns() if ns is None else ns
    return datetime.fromtimestamp(stamp / 1e9, timezone.utc).isoformat().replace("+00:00", "Z")


class DiagnosticEngine:
    def __init__(self, plan: Mapping[str, Any]):
        self.plan = dict(plan); self.branch = str(plan["branch"]); self.dt_s = float(plan["dt_s"])
        self.run_id = str(plan.get("run_id", ""))
        if not self.run_id or self.run_id == f"stage4f_timestep_diagnostic_v3_{self.branch.lower()}":
            raise ValueError("factory requires a fresh explicit run_id")
        self.root = Path(plan["case_root"]); self.parent_checkpoint = Path(plan["source_checkpoint"])
        runtime = Path(plan.get("runtime_root", Path(__file__).resolve().parents[3] / "runtime" / "stage4f_three_slice_timestep_diagnostic_v3" / f"branch_{self.branch}"))
        self.start_time_s = float(plan.get("start_time_s", START_TIME_S)); self.start_step = int(plan.get("start_step", 0))
        for key, relative in (("TEMP", "temp"), ("TMP", "temp"), ("TMPDIR", "tmpdir"),
                              ("PREFDIR", "prefdir"), ("MATLAB_PREFDIR", "prefdir"),
                              ("PYTHONPYCACHEPREFIX", "pycache")):
            target = runtime / relative
            target.mkdir(parents=True, exist_ok=True)
            os.environ[key] = str(target)
        if self.root.exists(): raise FileExistsError(self.root)
        self.root.mkdir(parents=True)
        self.manifest = _read_manifest(); base_config = r2._runtime_config(self.manifest, self.dt_s)
        self.config = r2.RuntimeConfig(schema_version=base_config.schema_version,
            case_id=base_config.case_id, dt_s=base_config.dt_s,
            timeout_s=base_config.timeout_s, start_time_s=self.start_time_s,
            coupling_iteration=base_config.coupling_iteration,
            coupling_scheme=base_config.coupling_scheme,
            slice_manifest_sha256=base_config.slice_manifest_sha256)
        self.parent_payload = json.loads(self.parent_checkpoint.read_text(encoding="utf-8"))
        source_case_root = self.parent_checkpoint.parent.parent / "cases"
        self.cases = r2._prepare_case_skeletons(self.root, dt_s=self.dt_s, start_time_s=self.start_time_s)
        self.staged_restart = stage_restart_case(checkpoint_path=self.parent_checkpoint, source_case_root=source_case_root, target_case_root=self.root / "cases")
        self.registry: list[dict[str, Any]] = []
        native = r2._native_from_checkpoint(self.parent_checkpoint)
        self.runner = r2.VariableStepRunner(self.root / "matlab", self.manifest, native_resume=native, dt_s=self.dt_s, process_registry=self.registry)
        self.adapter = RealProductionANCFAdapter(runner=self.runner, manifest=self.manifest,
            mesh_nodes=tuple(50.0 * index / 16 for index in range(17)), state_provider=self.runner.state_view,
            reference_positions_m={spec.slice_id: (0.0, 0.0, spec.s_ref_m) for spec in self.manifest.slices})
        self.processes = []
        for spec in self.manifest.slices:
            process = OpenFOAMSliceProcess(slice_id=spec.slice_id, case=self.cases[spec.slice_id], exchange_root=self.root / "exchange",
                manifest=self.manifest, runtime_config=self.config, library=DEFAULT_LIBRARY, run_id=self.run_id)
            process.preflight(format(self.start_time_s + self.dt_s, ".12g")); self.processes.append(process)
        prewarm = any(bool(getattr(process, "prewarm_openfoam_startup", False)) for process in self.processes)
        if prewarm:
            # The source checkpoint is already validated by the coordinator;
            # deriving only the current-time seed here lets OpenFOAM startup
            # overlap MATLAB initialize without allowing target-time motion to
            # bypass the scheduler barrier.
            source_state = self.parent_payload["structure"]
            seeds = [r2.motion_from_ancf_state(self.manifest, spec.slice_id,
                self.adapter.H_by_slice_id[spec.slice_id], source_state["q"], source_state["qdot"],
                source_state["qddot"], step=self.start_step, time_s=self.start_time_s,
                reference_position_m=(0.0, 0.0, spec.s_ref_m)).to_dict() for spec in self.manifest.slices]
            for process, seed in zip(self.processes, seeds):
                process.begin_step(seed, seed_step=self.start_step)
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(self.processes), thread_name_prefix="stage96-openfoam-prewarm")
            futures = [executor.submit(process.prewarm_current_seed, target_time_s=self.start_time_s + self.dt_s)
                       for process in self.processes]
            try:
                self.runner.start()
                for future in futures:
                    future.result()
            except Exception:
                for process in self.processes:
                    try:
                        process.stop()
                    except Exception:
                        pass
                raise
            finally:
                executor.shutdown(wait=True)
        else:
            self.runner.start()
        self._stamp_closed_matlab()
        self.scheduler = MultiSliceScheduler(config=MultiSliceConfig(case_id=self.manifest.case_id, dt_s=self.dt_s,
            timeout_s=self.config.timeout_s, start_time_s=self.start_time_s, manifest=self.manifest), exchange_root=self.root / "exchange",
            structure=self.adapter, slice_processes=self.processes, checkpoint_root=self.root / "checkpoints", case_root=self.root / "cases",
            committed_step=self.start_step - 1, committed_time_s=self.start_time_s,
            committed_time_tick=int(round(self.start_time_s * 1.0e9)))
        self.scheduler.run_id = self.run_id
        if self.start_step > 0:
            source_path = self.parent_checkpoint.resolve()
            if not source_path.is_file():
                raise ValueError("restart source checkpoint is missing")
            self.scheduler._committed_checkpoint_path = source_path
        self.scheduler.previous_slice_forces_N = [[float(v) for v in row] for row in self.parent_payload["previous_slice_forces_N"]]
        self.scheduler.previous_generalized_force = [float(v) for v in self.parent_payload["previous_generalized_force"]]
        self.expected_step = self.start_step; self.closed = False; self._known: dict[tuple[int, int], dict[str, Any]] = {}

    def _stamp_closed_matlab(self) -> None:
        for row in self.registry:
            if row.get("kind") == "matlab" and row.get("closed") and not row.get("end_timestamp"):
                row["start_timestamp"] = row.get("creation_time_utc")
                row["log_path"] = row.get("log")
                row["shutdown_method"] = row.get("close_method", "natural_exit")
                row["ownership_basis"] = "Popen PID plus psutil creation time and observed parent PID"
                row["end_timestamp"] = _utc()

    def _snapshot_processes(self) -> None:
        for process in self.processes:
            popen = process.process
            if popen is None: continue
            started_ns = int(process.process_start_ns); key = (int(popen.pid), started_ns)
            if key not in self._known:
                command = popen.args if isinstance(popen.args, list) else [str(popen.args)]
                row = {"kind": "openfoam_wsl_launcher", "slice_id": process.slice_id, "pid": popen.pid,
                       "creation_time": started_ns / 1e9, "parent_pid": os.getpid(), "executable": command[0],
                       "command_line": command, "cwd": os.getcwd(), "solver_case": str(process.case), "start_timestamp": _utc(started_ns),
                       "end_timestamp": None, "return_code": None, "log_path": str(process.log_paths[-1]) if process.log_paths else str(process.case / "log.pending"),
                       "shutdown_method": None, "ownership_basis": "OpenFOAMSliceProcess Popen PID and process_start_ns"}
                try:
                    import psutil
                    observed = psutil.Process(popen.pid); row.update(creation_time=observed.create_time(), parent_pid=observed.ppid(), executable=observed.exe(), command_line=observed.cmdline())
                except Exception as exc: row["snapshot_error"] = type(exc).__name__
                self.registry.append(row); self._known[key] = row
            row = self._known[key]
            if popen.poll() is not None and row["end_timestamp"] is None: stamp_process_end(row, return_code=popen.returncode, shutdown_method="natural_exit")

    def __call__(self, step: int, target: float) -> Mapping[str, Any]:
        if self.closed or step != self.expected_step: raise RuntimeError("engine step identity is not continuous")
        current = self.start_time_s + (step - self.start_step) * self.dt_s
        seeds = r2._seed_records(self.manifest, self.adapter, self.runner, step=step, time_s=current)
        for process, seed in zip(self.processes, seeds): process.begin_step(seed, seed_step=step)
        result = self.scheduler.run_step(step=step, time_s=target); self._stamp_closed_matlab(); self._snapshot_processes()
        for process in self.processes: process.finish_step(step, target)
        self._snapshot_processes()
        checkpoint = json.loads(result.checkpoint_path.read_text(encoding="utf-8"))
        self.scheduler.checkpoint_manager._validate_manifest(checkpoint, require_status="committed", verify_files=True)
        committed = {key: checkpoint["structure"][key] for key in ("q", "qdot", "qddot")}
        loads = {spec.slice_id: LoadRecord.from_mapping(row, self.manifest.R_GL) for spec, row in zip(self.manifest.slices, result.integrated_slice_forces)}
        delta_q = [math.sin(index + 1) for index in range(len(committed["q"]))]
        vw = map_integrated_slice_forces(self.manifest, self.adapter.H_by_slice_id, loads, delta_q=delta_q, random_seed=20260817).virtual_work.to_dict()
        force_rows = [r2._force_audit(row) for row in result.integrated_slice_forces]
        geometry = []
        for spec, process in zip(self.manifest.slices, self.processes):
            motion = r2._motion_csv(self.root / "exchange" / f"slice_{spec.slice_id:04d}" / "motion" / f"motion_step{step:08d}_iter0000.csv")
            center = r2.cylinder_center(process.case, format(target, ".12g")); corrected = r2._state_motion(self.manifest, self.adapter, committed, spec.slice_id, step=step, time_s=target)
            geometry.append({"slice_id": spec.slice_id, "mesh_error_m": max(abs(center[0]-float(motion["x_m"])),abs(center[1]-float(motion["y_m"]))),
                "position_gap_over_D": math.hypot(float(motion["x_m"])-corrected["x_m"],float(motion["y_m"])-corrected["y_m"])/D_M,
                "velocity_gap_over_U": math.hypot(float(motion["vx_mps"])-corrected["vx_mps"],float(motion["vy_mps"])-corrected["vy_mps"])/U_MPS})
        logs = [process.log_paths[-1] for process in self.processes]; codes = {str(path): process.return_code() for path,process in zip(logs,self.processes)}
        log_audit = r2._log_audit(logs,codes)
        self.expected_step += 1
        return {"step": step, "time_s": target, "slices": [{"slice_id": sid} for sid in SLICE_IDS], "force_observation_unique": len(result.integrated_slice_forces)==3,
            "state_role": "committed", "geometry_state_role": "predictor", "max_cfl": log_audit["max_cfl"],
            "virtual_work_relative_error": float(vw["error_rel"]), "force_conversion_relative_error": max(row["max_relative_error"] for row in force_rows),
            "mesh_center_motion_error_m": max(row["mesh_error_m"] for row in geometry),
            "position_difference_over_D": max(row["position_gap_over_D"] for row in geometry),
            "max_abs_Cd": max(abs(row["Cd"]) for row in force_rows), "velocity_difference_over_U": max(row["velocity_gap_over_U"] for row in geometry),
            "log_passed": log_audit["passed"], "checkpoint_passed": True, "process_evidence_passed": all(process.process is not None for process in self.processes),
            "checkpoint": str(result.checkpoint_path), "checkpoint_sha256": sha256_file(result.checkpoint_path), "force_audit": force_rows,
            "geometry_audit": geometry, "log_audit": log_audit, "virtual_work": vw}

    def shutdown(self) -> None:
        if self.closed: return
        self._snapshot_processes()
        for process in self.processes: process.stop()
        self._snapshot_processes(); self.runner.shutdown(); self._stamp_closed_matlab()
        close_pool = getattr(getattr(self, "scheduler", None), "close_parallel_executor", None)
        if close_pool is not None:
            close_pool()
        for row in self.registry:
            if row.get("end_timestamp") is None and row.get("kind") == "openfoam_wsl_launcher":
                matching = next((p for p in self.processes if p.process is not None and p.process.pid == row["pid"]), None)
                code = -1 if matching is None or matching.process.poll() is None else matching.process.returncode
                stamp_process_end(row, return_code=code, shutdown_method="OpenFOAMSliceProcess.stop")
        normalized = [normalize_process_record(row) for row in self.registry]
        from ..multi_slice_mapping.mapping import atomic_write_json
        atomic_write_json(self.root / "owned_process_registry.json", normalized); self.closed = True


def factory(plan: Mapping[str, Any]):
    engine = DiagnosticEngine(plan)
    return engine, engine.shutdown
