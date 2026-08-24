"""Stateful production-adapter engine for one continuous D1 or D2 branch."""
from __future__ import annotations

import json
import math
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..multi_slice_driver import MultiSliceConfig, MultiSliceScheduler
from ..multi_slice_driver.scheduler import SchedulerError, SchedulerState
from ..multi_slice_mapping.mapping import (
    LoadRecord,
    MotionRecord,
    atomic_write_json,
    map_integrated_slice_forces,
    sha256_file,
    validate_record_transaction,
)
from ..multi_slice_real_campaign.campaign import OpenFOAMSliceProcess, RealProductionANCFAdapter, stage_restart_case
from ..stage4f_equilibrated_startup_v3.equilibrium import _read_manifest
from ..stage4f_three_slice_short_window_v1_repair2 import runner as r2
from ..stage4f_three_slice_short_window_v1_repair2.contract import D_M, U_MPS
from ..stage4f_three_slice_timestep_diagnostic_v2.contract import SLICE_IDS, START_TIME_S
from ..stage4f_three_slice_timestep_diagnostic_v2.real_runner import normalize_process_record, stamp_process_end

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LIBRARY = PROJECT_ROOT / "runtime" / "stage4f_three_slice_timestep_diagnostic_v3" / "lib" / "libancfFileMotion.so"


def _utc(ns: int | None = None) -> str:
    stamp = time.time_ns() if ns is None else ns
    return datetime.fromtimestamp(stamp / 1e9, timezone.utc).isoformat().replace("+00:00", "Z")


class DiagnosticEngine:
    def __init__(self, plan: Mapping[str, Any]):
        self.plan = dict(plan); self.branch = str(plan["branch"]); self.dt_s = float(plan["dt_s"])
        self.physical_step = int(plan["physical_step"])
        self.current_time_s = float(plan["current_time_s"])
        self.target_time_s = float(plan["target_time_s"])
        self.root = Path(plan["case_root"]); self.parent_checkpoint = Path(plan["source_checkpoint"])
        runtime = Path(__file__).resolve().parents[3] / "runtime" / "stage4f_c_strong_coupling_preflight_v1" / self.root.name
        for key, relative in (("TEMP", "temp"), ("TMP", "temp"), ("TMPDIR", "tmpdir"),
                              ("PREFDIR", "prefdir"), ("MATLAB_PREFDIR", "prefdir"),
                              ("PYTHONPYCACHEPREFIX", "pycache")):
            target = runtime / relative
            target.mkdir(parents=True, exist_ok=True)
            os.environ[key] = str(target)
        if self.root.exists(): raise FileExistsError(self.root)
        self.root.mkdir(parents=True)
        self.manifest = _read_manifest(); self.config = r2._runtime_config(self.manifest, self.dt_s)
        self.parent_payload = json.loads(self.parent_checkpoint.read_text(encoding="utf-8"))
        source_case_root = self.parent_checkpoint.parent.parent / "cases"
        self.cases = r2._prepare_case_skeletons(self.root, dt_s=self.dt_s)
        self.staged_restart = stage_restart_case(checkpoint_path=self.parent_checkpoint, source_case_root=source_case_root, target_case_root=self.root / "cases")
        self.registry: list[dict[str, Any]] = []
        native = r2._native_from_checkpoint(self.parent_checkpoint)
        self.runner = r2.VariableStepRunner(self.root / "matlab", self.manifest, native_resume=native, dt_s=self.dt_s, process_registry=self.registry)
        self.runner.start()
        self._stamp_closed_matlab()
        self.adapter = RealProductionANCFAdapter(runner=self.runner, manifest=self.manifest,
            mesh_nodes=tuple(50.0 * index / 16 for index in range(17)), state_provider=self.runner.state_view,
            reference_positions_m={spec.slice_id: (0.0, 0.0, spec.s_ref_m) for spec in self.manifest.slices})
        self.processes = []
        for spec in self.manifest.slices:
            process = OpenFOAMSliceProcess(slice_id=spec.slice_id, case=self.cases[spec.slice_id], exchange_root=self.root / "exchange",
                manifest=self.manifest, runtime_config=self.config, library=DEFAULT_LIBRARY, run_id=f"stage4f_strong_preflight_step{self.physical_step:02d}")
            process.preflight(format(self.target_time_s, ".12g"))
            process.current_time_s = self.current_time_s
            process.current_clock_step = self.physical_step
            process.last_cfd_time_name = format(self.current_time_s, ".12g")
            self.processes.append(process)
        self.scheduler = MultiSliceScheduler(config=MultiSliceConfig(case_id=self.manifest.case_id, dt_s=self.dt_s,
            timeout_s=self.config.timeout_s, start_time_s=START_TIME_S, manifest=self.manifest), exchange_root=self.root / "exchange",
            structure=self.adapter, slice_processes=self.processes, checkpoint_root=self.root / "checkpoints", case_root=self.root / "cases")
        self.scheduler.previous_slice_forces_N = [[float(v) for v in row] for row in self.parent_payload["previous_slice_forces_N"]]
        self.scheduler.previous_generalized_force = [float(v) for v in self.parent_payload["previous_generalized_force"]]
        self.scheduler.last_committed_step = self.physical_step - 1
        self.expected_step = self.physical_step; self.closed = False; self._known: dict[tuple[int, int], dict[str, Any]] = {}

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
        current = START_TIME_S + step * self.dt_s
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


class CandidateIterationEngine(DiagnosticEngine):
    """Run exactly one fixed-point *trial* from a committed step parent.

    This is intentionally not a wrapper around :meth:`MultiSliceScheduler.run_step`.
    ``run_step`` implements the frozen 0.2.1 explicit transaction and commits its
    correction.  A strong-coupling candidate has to keep the correction staged so
    a nonselected iterate can be rolled back.  The explicit methods below are a
    faithful copy of the pre-checkpoint portion of that transaction; only
    :meth:`promote` is permitted to invoke ``prepare``, ``commit`` or
    ``finalize_committed``.

    Each engine instance owns a fresh case root and runner restored from one
    parent checkpoint.  Consequently an outer fixed-point coordinator obtains
    rollback identity by constructing one engine per candidate, rather than
    attempting to rewind a solver case in place.
    """

    def __init__(self, plan: Mapping[str, Any]):
        super().__init__(plan)
        self._trial: dict[str, Any] | None = None
        self._trial_discarded = False
        self._promoted_checkpoint: Path | None = None
        self._processes_finished = False

    def _finish_slice_processes(self) -> None:
        """Wait for the exact trial solvers before releasing this candidate."""
        if getattr(self, "_processes_finished", False):
            return
        for process in self.processes:
            process.finish_step(self.physical_step, self.target_time_s)
        self._snapshot_processes()
        self._processes_finished = True

    def _trial_failure(self, exc: Exception) -> None:
        """Retain candidate evidence but never manufacture a checkpoint."""
        try:
            self._finish_slice_processes()
        except Exception as finish_exc:
            exc = SchedulerError(f"{exc}; candidate process finish failed: {finish_exc}")
        try:
            self.adapter.discard_staged()
        except Exception as discard_exc:
            exc = SchedulerError(f"{exc}; discard_staged failed: {discard_exc}")
        self._snapshot_processes()
        self.scheduler.state = SchedulerState.FAILED
        atomic_write_json(self.root / "trial_failure.json", {
            "status": "failed", "phase": "candidate_trial", "step": self.physical_step,
            "time_s": self.target_time_s, "reason": str(exc),
            "formal_checkpoint_created": False,
        })
        self._trial_discarded = True

    def run_trial(
        self, *, previous_slice_forces_N: list[list[float]] | tuple[tuple[float, ...], ...] | None = None,
    ) -> Mapping[str, Any]:
        """Execute predictor/CFD/corrector with a staged structural correction.

        ``previous_slice_forces_N`` is the relaxed force guess owned by the
        outer fixed-point algorithm.  It is used only as the predictor input.
        The returned ``observed_slice_forces_N`` and ``generalized_force_N`` are
        computed from the actual CFD observation and are the only values that
        may be persisted by :meth:`promote`.
        """
        if self.closed or self._trial is not None:
            raise RuntimeError("candidate engine accepts exactly one trial")
        if self.scheduler.state != SchedulerState.INITIALIZED:
            raise RuntimeError("candidate scheduler is not at a fresh parent state")
        if self.scheduler.last_committed_step != self.physical_step - 1:
            raise RuntimeError("candidate parent step identity mismatch")

        if previous_slice_forces_N is not None:
            self.scheduler.previous_slice_forces_N = [
                [float(value) for value in row] for row in previous_slice_forces_N
            ]
        step, target, current = self.physical_step, self.target_time_s, self.current_time_s
        try:
            seeds = r2._seed_records(self.manifest, self.adapter, self.runner, step=step, time_s=current)
            for process, seed in zip(self.processes, seeds):
                process.begin_step(seed, seed_step=step)

            predicted = list(self.adapter.predict_all(step, target, self.scheduler.previous_slice_forces_N))
            motion_records = validate_record_transaction(
                [item if isinstance(item, MotionRecord) else MotionRecord.from_mapping(item) for item in predicted],
                self.manifest, kind="motion", expected_step=step, expected_time_s=target,
            )
            self.scheduler._transition(SchedulerState.PREDICTED, step=step, time_s=target)
            for sid, record in motion_records.items():
                marker = self.scheduler.processes[sid].publish_motion(
                    record, self.scheduler.paths[sid], manifest=self.manifest,
                    runtime_config=self.scheduler.config.runtime_config,
                )
                self.scheduler._append_log(step=step, time_s=target, slice_id=sid,
                    event="trial_motion_ready", payload_sha256=str(marker.get("payload_sha256")),
                    status=SchedulerState.MOTION_PUBLISHED)
            self.scheduler._transition(SchedulerState.MOTION_PUBLISHED, step=step, time_s=target)
            for spec in self.manifest.slices:
                consumed = self.scheduler.processes[spec.slice_id].wait_motion_consumed(
                    step, target, paths=self.scheduler.paths[spec.slice_id], manifest=self.manifest,
                    runtime_config=self.scheduler.config.runtime_config,
                )
                self.scheduler._append_log(step=step, time_s=target, slice_id=spec.slice_id,
                    event="trial_motion_consumed", payload_sha256=str(consumed.get("payload_sha256")),
                    status=SchedulerState.MOTION_CONSUMED)
            self.scheduler._transition(SchedulerState.MOTION_CONSUMED, step=step, time_s=target)
            for spec in self.manifest.slices:
                self.scheduler.processes[spec.slice_id].advance_one_step(step, target)
                self.scheduler._append_log(step=step, time_s=target, slice_id=spec.slice_id,
                    event="trial_cfd_advanced", status=SchedulerState.CFD_ADVANCED)
            self.scheduler._transition(SchedulerState.CFD_ADVANCED, step=step, time_s=target)

            load_records: list[LoadRecord] = []
            for spec in self.manifest.slices:
                process = self.scheduler.processes[spec.slice_id]
                ready = process.wait_load_ready(step, target, paths=self.scheduler.paths[spec.slice_id],
                    manifest=self.manifest, runtime_config=self.scheduler.config.runtime_config)
                raw = process.read_load(step, target)
                load_records.append(raw if isinstance(raw, LoadRecord) else LoadRecord.from_mapping(raw, self.manifest.R_GL))
                self.scheduler._append_log(step=step, time_s=target, slice_id=spec.slice_id,
                    event="trial_load_ready", payload_sha256=str(ready.get("payload_sha256")),
                    status=SchedulerState.LOADS_READY)
            ordered = validate_record_transaction(load_records, self.manifest, kind="load",
                expected_step=step, expected_time_s=target)
            mapping = map_integrated_slice_forces(self.manifest, self.scheduler._h_by_slice_id(), ordered)
            self.scheduler._transition(SchedulerState.LOADS_READY, step=step, time_s=target)
            for spec in self.manifest.slices:
                consumed = self.scheduler.processes[spec.slice_id].publish_load_consumed(
                    step, target, paths=self.scheduler.paths[spec.slice_id], manifest=self.manifest,
                    runtime_config=self.scheduler.config.runtime_config,
                )
                self.scheduler._append_log(step=step, time_s=target, slice_id=spec.slice_id,
                    event="trial_load_consumed", payload_sha256=str(consumed.get("payload_sha256")),
                    status=SchedulerState.LOADS_CONSUMED)
            self.scheduler._transition(SchedulerState.LOADS_CONSUMED, step=step, time_s=target)
            if hasattr(self.adapter, "accept_generalized_force"):
                self.adapter.accept_generalized_force(mapping.generalized_force)
            correction = self.adapter.correct_all(step, target, list(ordered.values()))
            if not isinstance(correction, Mapping) or int(correction.get("step", -1)) != step:
                raise SchedulerError("candidate structure correct returned wrong step")
            if abs(float(correction.get("time_s", math.nan)) - target) > 1.0e-12 * max(1.0, abs(target)):
                raise SchedulerError("candidate structure correct returned wrong time")
            generalized = correction.get("generalized_force", list(mapping.generalized_force))
            if not isinstance(generalized, (list, tuple)) or any(not math.isfinite(float(value)) for value in generalized):
                raise SchedulerError("candidate generalized force is not finite")
            self.scheduler._active_correction = correction
            self.scheduler._transition(SchedulerState.STRUCTURE_CORRECTED, step=step, time_s=target)

            # A candidate is eligible for numerical audit or promotion only
            # after all three solver launchers have exited naturally.
            self._finish_slice_processes()

            # Audits intentionally happen before promotion.  They are evidence
            # for this candidate, not a committed 0.2.1 transaction.
            delta_q = [math.sin(index + 1) for index in range(len(self.adapter.export_staged_checkpoint()["q"]))]
            virtual_work = map_integrated_slice_forces(
                self.manifest, self.adapter.H_by_slice_id, ordered, delta_q=delta_q,
                random_seed=20260817,
            ).virtual_work.to_dict()
            force_rows = [r2._force_audit(row.to_dict()) for row in ordered.values()]
            staged = self.adapter.export_staged_checkpoint()
            geometry: list[dict[str, Any]] = []
            for spec, process in zip(self.manifest.slices, self.processes):
                motion_path = self.root / "exchange" / f"slice_{spec.slice_id:04d}" / "motion" / f"motion_step{step:08d}_iter0000.csv"
                motion = r2._motion_csv(motion_path)
                center = r2.cylinder_center(process.case, format(target, ".12g"))
                corrected = r2._state_motion(self.manifest, self.adapter, staged, spec.slice_id, step=step, time_s=target)
                geometry.append({"slice_id": spec.slice_id,
                    "mesh_error_m": max(abs(center[0] - float(motion["x_m"])), abs(center[1] - float(motion["y_m"]))),
                    "position_gap_over_D": math.hypot(float(motion["x_m"]) - corrected["x_m"], float(motion["y_m"]) - corrected["y_m"]) / D_M,
                    "velocity_gap_over_U": math.hypot(float(motion["vx_mps"]) - corrected["vx_mps"], float(motion["vy_mps"]) - corrected["vy_mps"]) / U_MPS,
                })
            logs = [Path(process.log_paths[-1]) for process in self.processes]
            codes = {str(path): process.return_code() for path, process in zip(logs, self.processes)}
            log_audit = r2._log_audit(logs, codes)
            observed = [[float(row.force_N[0]), float(row.force_N[1]), float(row.force_N[2])] for row in ordered.values()]
            self._trial = {
                "candidate_kind": "strong_coupling_trial", "step": step, "time_s": target,
                "coupling_iteration": 0, "formal_checkpoint_created": False,
                "state_role": "staged_correction", "geometry_state_role": "predictor",
                "observed_slice_forces_N": observed,
                "integrated_slice_forces": [row.to_dict() for row in ordered.values()],
                "generalized_force_N": [float(value) for value in generalized],
                "correction": dict(correction), "force_audit": force_rows, "geometry_audit": geometry,
                "log_audit": log_audit, "virtual_work": virtual_work,
                "max_cfl": log_audit["max_cfl"], "max_abs_Cd": max(abs(row["Cd"]) for row in force_rows),
                "force_conversion_relative_error": max(row["max_relative_error"] for row in force_rows),
                "virtual_work_relative_error": float(virtual_work["error_rel"]),
                "mesh_center_motion_error_m": max(row["mesh_error_m"] for row in geometry),
                "position_difference_over_D": max(row["position_gap_over_D"] for row in geometry),
                "velocity_difference_over_U": max(row["velocity_gap_over_U"] for row in geometry),
                "all_three_slices_complete": len(ordered) == len(self.manifest.slices),
                "logs": [str(path) for path in logs],
                "case_root": str(self.root), "parent_checkpoint": str(self.parent_checkpoint),
                "parent_checkpoint_sha256": sha256_file(self.parent_checkpoint),
            }
            atomic_write_json(self.root / "trial_evidence.json", self._trial)
            self._stamp_closed_matlab(); self._snapshot_processes()
            return dict(self._trial)
        except Exception as exc:
            self._trial_failure(exc)
            raise

    def discard_trial(self) -> None:
        """Explicitly reject the staged correction and retain its trial evidence."""
        if self._trial is None:
            raise RuntimeError("no candidate trial exists")
        if self._promoted_checkpoint is not None:
            raise RuntimeError("promoted candidate cannot be discarded")
        if self._trial_discarded:
            return
        try:
            self._finish_slice_processes()
        finally:
            self.adapter.discard_staged()
            self._snapshot_processes()
        self._trial_discarded = True
        self._trial["staged_correction_discarded"] = True
        atomic_write_json(self.root / "trial_evidence.json", self._trial)

    def promote(self) -> Path:
        """Create the sole formal checkpoint for a converged candidate.

        The force matrix is rebuilt from the observed CFD records.  In
        particular, it cannot be supplied by the outer relaxation iterate.
        """
        if self._trial is None or self._trial_discarded:
            raise RuntimeError("only an undiscarded staged candidate can be promoted")
        if self._promoted_checkpoint is not None:
            raise RuntimeError("candidate has already been promoted")
        if self.scheduler.state != SchedulerState.STRUCTURE_CORRECTED:
            raise RuntimeError("candidate is not at staged-correction state")
        ordered = [LoadRecord.from_mapping(row, self.manifest.R_GL) for row in self._trial["integrated_slice_forces"]]
        observed = [[float(row.force_N[0]), float(row.force_N[1]), float(row.force_N[2])] for row in ordered]
        try:
            prepared = self.scheduler.checkpoint_manager.prepare(
                step=self.physical_step, time_s=self.target_time_s, coupling_iteration=0,
                slice_processes=self.scheduler.processes, structure=self.adapter,
                previous_slice_forces_N=observed,
                previous_generalized_force=[float(value) for value in self._trial["generalized_force_N"]],
            )
            self.scheduler._active_checkpoint = prepared
            self.scheduler._transition(SchedulerState.CHECKPOINT_PREPARED, step=self.physical_step, time_s=self.target_time_s)
            checkpoint = self.scheduler.checkpoint_manager.commit(prepared)
            self.adapter.finalize_committed(prepared.staged_token)
            self.scheduler._transition(SchedulerState.COMMITTED, step=self.physical_step, time_s=self.target_time_s)
            self.scheduler.last_committed_step = self.physical_step
            self.scheduler.last_committed_time_s = self.target_time_s
            self.scheduler.previous_slice_forces_N = observed
            self.scheduler.previous_generalized_force = [float(value) for value in self._trial["generalized_force_N"]]
            self.scheduler._active_correction = None
            self.scheduler._active_checkpoint = None
            self._promoted_checkpoint = checkpoint
            self._finish_slice_processes()
            self._trial.update({"formal_checkpoint_created": True, "checkpoint": str(checkpoint),
                "checkpoint_sha256": sha256_file(checkpoint), "staged_correction_discarded": False,
                "observed_force_persisted": observed == self._trial["observed_slice_forces_N"]})
            atomic_write_json(self.root / "trial_evidence.json", self._trial)
            return checkpoint
        except Exception:
            # Once AtomicCheckpointManager.commit returns, deleting/replacing a
            # checkpoint would violate the evidence contract.  Let the caller
            # classify that recovery-required condition; do not hide it.
            raise


def candidate_factory(plan: Mapping[str, Any]):
    """Factory used by the outer coordinator; one engine equals one rollback."""
    engine = CandidateIterationEngine(plan)
    return engine, engine.shutdown
