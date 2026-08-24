"""Attempt the bounded two-slice 0.2.1 CFD--ANCF weak-coupling smoke.

The OpenFOAM library remains the existing production copy.  The only bridge
inside this smoke is the explicit 0.1.0 materialized view required by the
unchanged stage-three ancfFileMotion reader; immutable 0.2.1 payloads and all
global checkpoint files are still handled by the new scheduler.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np
import scipy.io as sio

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.coupling.multi_slice_driver import (
    LoadRecord,
    MotionRecord,
    MultiSliceConfig,
    MultiSliceScheduler,
    ProductionANCFAdapter,
    RuntimeConfig,
    SliceExchangePaths,
    SliceManifest,
    SliceSpec,
)
from src.coupling.multi_slice_driver.protocol import publish_payload, publish_consumed
from src.coupling.multi_slice_driver.real_process import (
    BridgeSnapshot,
    ExactForce,
    FileFingerprint,
    RealProcessFreshnessError,
    assert_fresh_case,
    bridge_seed,
    force_file_audit,
    fingerprint,
    materialize_legacy_motion_bridge,
    parse_force_exact,
    time_close,
    validate_bridge_ack,
    validate_initial_state,
)
from src.coupling.multi_slice_mapping.mapping import (
    SCHEMA_VERSION,
    atomic_write_json,
    build_H_for_manifest,
    interpolate_ancf_state,
    motion_from_ancf_state,
    sha256_file,
)
from src.coupling.structure_runners.persistent_matlab_runner import PersistentMatlabRunner


MOTION_FIELDS = ("schema_version", "step", "coupling_iteration", "time_s", "slice_id", "s_ref_m", "x_m", "y_m", "z_m", "vx_mps", "vy_mps", "vz_mps", "ax_mps2", "ay_mps2", "az_mps2")


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        temporary_path.write_text(text, encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def wsl_path(path: Path) -> str:
    absolute = str(path.resolve()).replace("\\", "/")
    drive, rest = absolute.split(":", 1)
    return f"/mnt/{drive.lower()}{rest}"


class MatlabStateProvider:
    def __init__(self, runner: PersistentMatlabRunner) -> None:
        self.runner = runner
        self.path = Path(tempfile.mktemp(prefix="stage4b_mat_state_", suffix=".mat"))

    def __call__(self):
        self.runner.save_checkpoint(self.path)
        data = sio.loadmat(self.path, squeeze_me=True, struct_as_record=False)
        pending = data.get("pending_prediction")
        state = pending.state if hasattr(pending, "state") else data["runner_state"]
        return {
            "q": np.asarray(state.q, dtype=float).reshape(-1).tolist(),
            "qdot": np.asarray(state.qd, dtype=float).reshape(-1).tolist(),
            "qddot": np.asarray(state.qdd, dtype=float).reshape(-1).tolist(),
        }


class RealSliceProcess:
    def __init__(self, *, slice_id: int, case: Path, exchange_root: Path, manifest: SliceManifest, runtime_config: RuntimeConfig, library: Path, run_id: str, force_start_time_s: float | None = None, bridge_seed_step: int = 0) -> None:
        self.slice_id = slice_id
        self.case = case
        self.case_root = case.parent
        self.exchange_root = exchange_root
        self.manifest = manifest
        self.runtime_config = runtime_config
        self.library = library
        self.run_id = run_id
        self.bridge_seed_step = int(bridge_seed_step)
        self.process: subprocess.Popen[bytes] | None = None
        self.process_start_ns = 0
        self.last_cfd_time_name: str | None = None
        self.last_load: LoadRecord | None = None
        self.last_force: ExactForce | None = None
        self.last_force_fingerprint: FileFingerprint | None = None
        self.consumed_force_steps: set[int] = set()
        self.last_bridge: BridgeSnapshot | None = None
        self.last_motion_record: MotionRecord | None = None
        self.bridge_publications: list[dict[str, object]] = []
        self.seed_snapshot: BridgeSnapshot | None = None
        start_time_name = format(runtime_config.start_time_s if force_start_time_s is None else force_start_time_s, ".12g")
        self.force_path = self.case / "postProcessing" / "cylinderForces" / start_time_name / "forces.dat"
        self.log_path = self.case / f"log.pimpleFoam_{run_id}_slice_{slice_id:04d}"
        self.force_audits: list[dict[str, object]] = []

    @property
    def spec(self):
        return self.manifest.slice(self.slice_id)

    def preflight(self, target_time_name: str) -> dict[str, object]:
        return assert_fresh_case(self.case, target_time_name=target_time_name)

    def start(self) -> None:
        wcase, wlib_dir = wsl_path(self.case), wsl_path(self.library.parent)
        command = (
            "source /opt/openfoam10/etc/bashrc; "
            f"export LD_LIBRARY_PATH=/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/dummy:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/openmpi-system:{wlib_dir}:$LD_LIBRARY_PATH; "
            f"cd '{wcase}'; /opt/openfoam10/platforms/linux64GccDPInt32Opt/bin/pimpleFoam > '{self.log_path.name}' 2>&1"
        )
        self.process_start_ns = time.time_ns()
        self.process = subprocess.Popen(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command])

    def publish_seed(self, record: MotionRecord, *, start_time_s: float) -> BridgeSnapshot:
        snapshot = materialize_legacy_motion_bridge(
            record=record.to_dict(), case=self.case, exchange_dir="coupling",
            seed=True, seed_time_s=start_time_s, bridge_step_offset=1,
            seed_step_offset=self.bridge_seed_step,
        )
        self.seed_snapshot = snapshot
        self.last_motion_record = record
        self.bridge_publications.append({
            "kind": "seed", "global_step": int(record.step),
            "global_time_s": float(record.time_s),
            "bridge_step": snapshot.bridge_step, "bridge_time_s": snapshot.bridge_time_s,
            "published_ns": snapshot.published_ns,
        })
        return snapshot

    def wait_seed_consumed(self, record: MotionRecord, *, timeout_s: float) -> Mapping[str, object]:
        if self.seed_snapshot is None:
            raise RealProcessFreshnessError("seed was not published")
        ack = self.case / "coupling" / "consumed" / f"motion_consumed_{self.seed_snapshot.bridge_step}.json"
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if ack.is_file():
                return validate_bridge_ack(
                    ack_path=ack, snapshot=self.seed_snapshot,
                    record=record.to_dict(), published_ns=self.seed_snapshot.published_ns,
                )
            if self.process is not None and self.process.poll() not in (None, 0):
                raise RuntimeError(f"slice {self.slice_id} exited during seed: {self.process.returncode}")
            time.sleep(0.01)
        raise TimeoutError(f"slice {self.slice_id} seed consumed timeout")

    def publish_motion(self, record, paths: SliceExchangePaths, *, manifest: SliceManifest, runtime_config: RuntimeConfig):
        marker = publish_payload(payload_path=paths.payload("motion", record.step), ready_path=paths.ready("motion", record.step), kind="motion", record=record, manifest=manifest, runtime_config=runtime_config)
        snapshot = materialize_legacy_motion_bridge(
            record=record.to_dict(), case=self.case, exchange_dir="coupling",
            # Formal global step g always maps to bridge step g+1.  The
            # case-local stepOffset affects only the initial seed snapshot.
            bridge_step_offset=1,
        )
        self.last_motion_record = record if isinstance(record, MotionRecord) else MotionRecord.from_mapping(record)
        self.last_bridge = snapshot
        self.bridge_publications.append({
            "kind": "target", "global_step": int(record.step),
            "global_time_s": float(record.time_s),
            "bridge_step": snapshot.bridge_step, "bridge_time_s": snapshot.bridge_time_s,
            "published_ns": snapshot.published_ns,
            "formal_payload": str(paths.payload("motion", record.step)),
            "formal_ready": str(paths.ready("motion", record.step)),
        })
        return marker

    def wait_motion_consumed(self, step, time_s, *, paths, manifest, runtime_config):
        if self.last_bridge is None:
            raise RealProcessFreshnessError("target motion bridge has not been published")
        old_ack = self.case / "coupling" / "consumed" / f"motion_consumed_{self.last_bridge.bridge_step}.json"
        deadline = time.monotonic() + runtime_config.timeout_s
        while time.monotonic() < deadline and not old_ack.is_file():
            if self.process is not None and self.process.poll() not in (None, 0):
                raise RuntimeError(f"slice {self.slice_id} OpenFOAM exited {self.process.returncode}")
            time.sleep(0.01)
        if not old_ack.is_file():
            raise TimeoutError(f"slice {self.slice_id} motion bridge consumed timeout")
        if self.last_motion_record is None:
            raise RealProcessFreshnessError("formal motion record is not available for bridge ack validation")
        record = self.last_motion_record.to_dict()
        validate_bridge_ack(
            ack_path=old_ack, snapshot=self.last_bridge, record=record,
            published_ns=self.last_bridge.published_ns,
        )
        return publish_consumed(paths=paths, kind="motion", step=step, time_s=time_s, manifest=manifest, runtime_config=runtime_config, consumer="openfoam-ancfFileMotion-bridge")

    def advance_one_step(self, step, time_s):
        return None

    def wait_load_ready(self, step, time_s, *, paths, manifest, runtime_config):
        target = time_s
        if step in self.consumed_force_steps:
            raise RealProcessFreshnessError(f"slice {self.slice_id} force target was already consumed")
        deadline = time.monotonic() + runtime_config.timeout_s
        force = None
        while time.monotonic() < deadline:
            force = parse_force_exact(
                self.force_path, target_time_s=target,
                minimum_mtime_ns=self.process_start_ns,
                previous=self.last_force_fingerprint,
            )
            if force is not None:
                break
            if self.process is not None and self.process.poll() not in (None, 0):
                raise RuntimeError(f"slice {self.slice_id} OpenFOAM exited {self.process.returncode}")
            if self.process is not None and self.process.poll() == 0 and not self.force_path.is_file():
                raise RuntimeError(f"slice {self.slice_id} exited before force output at {target}")
            time.sleep(0.02)
        if force is None:
            raise TimeoutError(f"slice {self.slice_id} force output timeout at {target}")
        record = LoadRecord.from_conversion(
            case_id=manifest.case_id, step=step, time_s=time_s,
            slice_definition=self.spec, unit_span_m=self.spec.unit_span_m,
            openfoam_force_N=force.force_N, cfd_time_step_s=runtime_config.dt_s,
            R_GL=manifest.R_GL,
        )
        self.last_load = record
        self.last_force = force
        self.last_force_fingerprint = fingerprint(self.force_path)
        self.consumed_force_steps.add(step)
        self.last_cfd_time_name = format(target, ".12g")
        marker = publish_payload(payload_path=paths.payload("load", step), ready_path=paths.ready("load", step), kind="load", record=record, manifest=manifest, runtime_config=runtime_config)
        return marker

    def read_load(self, step, time_s):
        if self.last_load is None or self.last_load.step != step or not time_close(self.last_load.time_s, time_s):
            raise RuntimeError("load was not prepared")
        return self.last_load

    def publish_load_consumed(self, step, time_s, *, paths, manifest, runtime_config):
        return publish_consumed(paths=paths, kind="load", step=step, time_s=time_s, manifest=manifest, runtime_config=runtime_config, consumer="multi-slice-driver-v2")

    @property
    def case_relative_path(self) -> str:
        return self.case.name

    def checkpoint_files(self, step, time_s):
        if self.last_cfd_time_name is None or self.last_force is None:
            raise RuntimeError("no CFD time output for checkpoint")
        if not time_close(self.last_force.time_s, time_s):
            raise RuntimeError("checkpoint force target does not match transaction time")
        self.force_audits.append(force_file_audit(self.force_path, expected=self.last_force))
        time_dir = self.case / self.last_cfd_time_name
        return {
            "openfoam_time_name": self.last_cfd_time_name,
            "case_relative_path": self.case_relative_path,
            "static_files": {"motionScale": self.case / "0" / "motionScale"},
            "time_files": {name: time_dir / name for name in ("U", "p", "phi", "Uf", "meshPhi", "polyMesh/points", "uniform/time")},
        }

    def restore_checkpoint(self, entry):
        time_name = str(entry.get("openfoam_time_name", ""))
        if not time_name:
            raise RuntimeError(f"slice {self.slice_id}: restart time directory is missing")
        self.last_cfd_time_name = time_name

    def post_run_force_audit(self) -> list[dict[str, object]]:
        audits = []
        for expected in (self.last_force,) if self.last_force is not None else ():
            audits.append(force_file_audit(self.force_path, expected=expected))
        return audits


def parameter_consistency(manifest: SliceManifest, *, dt_s: float) -> dict[str, object]:
    """Return the complete Gate-4A interface parameter ledger."""

    cfd = {"D_m": 1.0, "U_mps": 1.0, "rho_kgpm3": 1000.0, "nu_m2ps": 0.01, "unit_span_m": 1.0}
    ancf = {
        "L_m": 10.0, "D_m": 1.0, "d_inner_m": 0.9, "E_Pa": 2.07e11,
        "top_tension_N": 1.0e7, "nElem": 2,
    }
    area = math.pi * (ancf["D_m"] ** 2 - ancf["d_inner_m"] ** 2) / 4.0
    EA = ancf["E_Pa"] * area
    mass_per_length = 7850.0 * area
    re_value = cfd["U_mps"] * cfd["D_m"] / cfd["nu_m2ps"]
    values = {
        "cfd": cfd, "ancf": ancf, "cross_section_area_m2": area,
        "EA_N": EA, "T_over_EA": ancf["top_tension_N"] / EA,
        "unit_length_mass_kgpm": mass_per_length,
        "diameter_ratio_cfd_over_ancf": cfd["D_m"] / ancf["D_m"],
        "length_ratio_cfd_slice_reference_m": [cfd["D_m"] / item.slice_length_m for item in manifest.slices],
        "slice_lengths_sum_m": sum(item.slice_length_m for item in manifest.slices),
        "reference_length_m": manifest.reference_length_m,
        "Re": re_value, "dt_s": dt_s,
    }
    if not time_close(values["diameter_ratio_cfd_over_ancf"], 1.0):
        raise RuntimeError("CFD/ANCF diameter mismatch")
    if values["T_over_EA"] >= 0.01:
        raise RuntimeError("T/(EA) is not below 1%")
    if not time_close(values["slice_lengths_sum_m"], manifest.represented_length_m):
        raise RuntimeError("slice length sum does not match represented length")
    if not time_close(re_value, 100.0):
        raise RuntimeError("Re is not 100")
    return values


def _state_from_provider(provider: MatlabStateProvider) -> dict[str, list[float]]:
    state = provider()
    for key in ("q", "qdot", "qddot"):
        if not state[key] or any(not math.isfinite(float(value)) for value in state[key]):
            raise RuntimeError(f"initial ANCF state {key} is not finite")
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--case0", type=Path, required=True)
    parser.add_argument("--case1", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--start-time", type=float, default=0.0)
    parser.add_argument("--dt", type=float, default=0.0025)
    parser.add_argument("--steps", type=int, default=2)
    args = parser.parse_args()
    root = args.output_root.resolve(); root.mkdir(parents=True, exist_ok=True)
    run_id = f"stage4b_v3_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{uuid.uuid4().hex[:8]}"
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = SliceManifest.from_mapping(json.loads((PROJECT_ROOT / "tests/multi_slice_mapping/fixtures/golden_manifest_0.2.1.json").read_text(encoding="utf-8")))
    config = MultiSliceConfig(case_id=manifest.case_id, dt_s=args.dt, timeout_s=30.0, start_time_s=args.start_time, manifest=manifest)
    parameters = parameter_consistency(manifest, dt_s=args.dt)
    runner_config = {"L": 10.0, "D": 1.0, "dInner": 0.9, "nElem": 2, "nSlices": 2, "s_ref_m": [2.5, 7.5], "topTension_N": 1.0e7, "youngs_modulus_Pa": 2.07e11, "dt": args.dt, "newton_tolerance": 1.0e-8, "max_newton": 40}
    runner = PersistentMatlabRunner(branch="ancf", config=runner_config, matlab_exe=r"D:\Matlab\bin\matlab.exe", request_dir=run_dir / "matlab_runner", timeout_s=120.0)
    processes = [
        RealSliceProcess(slice_id=0, case=args.case0.resolve(), exchange_root=run_dir / "exchange", manifest=manifest, runtime_config=config.runtime_config, library=args.library.resolve(), run_id=run_id),
        RealSliceProcess(slice_id=1, case=args.case1.resolve(), exchange_root=run_dir / "exchange", manifest=manifest, runtime_config=config.runtime_config, library=args.library.resolve(), run_id=run_id),
    ]
    scheduler = None
    status = "blocked"
    error = None
    step_results = []
    seed_records = []
    initial_state = None
    reference_positions = {}
    freshness = []
    try:
        if args.steps < 1:
            raise ValueError("--steps must be positive")
        target_time = args.start_time + args.steps * args.dt
        target_time_name = format(target_time, ".12g")
        freshness = [process.preflight(target_time_name) for process in processes]
        runner.start()
        provider = MatlabStateProvider(runner)
        initial_state = _state_from_provider(provider)
        adapter = ProductionANCFAdapter(
            runner=runner, manifest=manifest, mesh_nodes=(0.0, 5.0, 10.0),
            state_provider=provider, runner_step_offset=1,
            runner_time_offset_s=-args.start_time,
        )
        for item in manifest.slices:
            position, _, _ = interpolate_ancf_state(
                adapter.H_by_slice_id[item.slice_id], initial_state["q"],
                initial_state["qdot"], initial_state["qddot"],
            )
            reference_positions[item.slice_id] = position
        scheduler = MultiSliceScheduler(config=config, exchange_root=run_dir / "exchange", structure=adapter, slice_processes=processes, checkpoint_root=run_dir / "checkpoints", case_root=processes[0].case_root)
        for item in manifest.slices:
            seed = motion_from_ancf_state(
                manifest, item.slice_id, adapter.H_by_slice_id[item.slice_id],
                initial_state["q"], initial_state["qdot"], initial_state["qddot"],
                step=0, time_s=args.start_time,
                reference_position_m=reference_positions[item.slice_id],
            )
            seed_records.append(seed)
            processes[item.slice_id].publish_seed(seed, start_time_s=args.start_time)
        initial_audit = validate_initial_state(reference_positions=reference_positions, seed_records=[item.to_dict() for item in seed_records])
        for process in processes:
            process.start()
        for item, process in zip(seed_records, processes):
            process.wait_seed_consumed(item, timeout_s=config.timeout_s)
        for global_step in range(args.steps):
            result = scheduler.run_step(step=global_step, time_s=args.start_time + (global_step + 1) * args.dt)
            step_results.append({
                "step": result.step, "time_s": result.time_s,
                "checkpoint": str(result.checkpoint_path),
                "integrated_slice_forces_N": [
                    [row["force_x_N"], row["force_y_N"], row["force_z_N"]]
                    for row in result.integrated_slice_forces
                ],
                "generalized_force": result.audit.get("generalized_force_from_A_Ht", []),
                "q": json.loads(result.checkpoint_path.read_text(encoding="utf-8"))["structure"]["q"],
                "qdot": json.loads(result.checkpoint_path.read_text(encoding="utf-8"))["structure"]["qdot"],
                "qddot": json.loads(result.checkpoint_path.read_text(encoding="utf-8"))["structure"]["qddot"],
                "state": result.state.value,
            })
        status = "completed"
    except Exception as exc:
        error = str(exc)
    finally:
        for process in processes:
            if process.process is not None:
                try:
                    process.process.wait(timeout=30.0)
                except subprocess.TimeoutExpired:
                    process.process.terminate()
        runner.shutdown()
    logs = []
    max_cfl = 0.0
    return_codes = []
    for process in processes:
        log = process.log_path
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        values = [float(value) for value in re.findall(r"Courant Number mean:\s+[^\s]+\s+max:\s+([-+0-9.eE]+)", text)]
        max_cfl = max(max_cfl, max(values) if values else 0.0)
        return_codes.append(process.process.returncode if process.process is not None else None)
        logs.append(str(log))
    force_audits = []
    audit_error = None
    try:
        for process in processes:
            force_audits.extend(process.post_run_force_audit())
    except Exception as exc:
        audit_error = str(exc)
    checkpoints = [path for path in sorted((run_dir / "checkpoints").glob("checkpoint_*.json"))]
    checkpoint_hash_audit = []
    if scheduler is not None:
        for path in checkpoints:
            try:
                manifest_payload = json.loads(path.read_text(encoding="utf-8"))
                scheduler.checkpoint_manager._validate_manifest(
                    manifest_payload, require_status="committed", verify_files=True,
                )
                checkpoint_hash_audit.append({
                    "path": str(path), "step": manifest_payload["step"], "valid": True,
                })
            except Exception as exc:
                checkpoint_hash_audit.append({
                    "path": str(path), "valid": False, "error": str(exc),
                })
    hash_audit_error = next(
        (item.get("error") for item in checkpoint_hash_audit if not item.get("valid")),
        None,
    )
    summary = {
        "schema_version": "stage4b_v3_real_two_slice_closed_loop",
        "run_id": run_id,
        "status": status if error is None and audit_error is None and hash_audit_error is None and max_cfl <= 0.8 and all(code == 0 for code in return_codes) else "blocked",
        "error": error,
        "protocol_version": SCHEMA_VERSION,
        "slice_manifest_sha256": manifest.slice_manifest_sha256,
        "config_sha256": config.config_sha256,
        "start_time_s": args.start_time,
        "dt_s": args.dt,
        "scheduler_returned_steps": [item["step"] for item in step_results],
        "committed_manifest_count": len(checkpoints),
        "valid_committed_steps_after_final_hash_audit": [item["step"] for item in checkpoint_hash_audit if item.get("valid")],
        "OpenFOAM_exact_force_steps": sorted({step for process in processes for step in process.consumed_force_steps}),
        "closed_loop_steps": [item["step"] for item in step_results],
        "restart_steps": [],
        "steps_completed": len(step_results),
        "global_times_s": [item["time_s"] for item in step_results],
        "checkpoint_paths": [str(path) for path in checkpoints],
        "case_paths": [str(args.case0.resolve()), str(args.case1.resolve())],
        "logs": logs, "return_codes": return_codes, "process_count_max": 2,
        "max_cfl": max_cfl, "motionScale_paths": [str(p.case / "0" / "motionScale") for p in processes],
        "freshness": freshness, "bridge_publications": [p.bridge_publications for p in processes],
        "initial_state": initial_state, "initial_reference_positions_m": reference_positions,
        "initial_seed_audit": locals().get("initial_audit"),
        "parameters": parameters,
        "step_results": step_results,
        "force_audits": force_audits, "post_run_hash_audit_error": audit_error,
        "checkpoint_final_hash_audit": checkpoint_hash_audit,
        "checkpoint_final_hash_audit_error": hash_audit_error,
        "free_viv_claim": False,
    }
    atomic_write_json(run_dir / "real_two_slice_closed_loop_summary.json", summary)
    atomic_write_json(root / "real_two_slice_closed_loop_summary.json", summary)
    atomic_write_json(root / "checkpoint_final_hash_audit.json", {
        "schema_version": "stage4b-v3-checkpoint-final-hash-audit",
        "run_id": run_id, "valid": hash_audit_error is None,
        "entries": checkpoint_hash_audit, "error": hash_audit_error,
    })
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
