"""Bounded real three-slice OpenFOAM--ANCF Stage 4C-B campaign.

This module deliberately keeps the formal transaction boundary in the
existing ``multi_slice_driver`` and ``checkpoint`` packages.  The only
compatibility view written here is the explicit 0.1.0 motion CSV required by
the unchanged ``ancfFileMotion`` library.  Formal motion/load payloads,
markers, hashes and H/H^T mapping continue to come from the 0.2.1 production
modules.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import scipy.io as sio

from ..checkpoint.atomic_checkpoint import REQUIRED_TIME_FILES
from ..multi_slice_driver import (
    MultiSliceConfig,
    MultiSliceScheduler,
    ProductionANCFAdapter,
    RuntimeConfig,
    SliceExchangePaths,
    SliceManifest,
    SliceSpec,
)
from ..multi_slice_driver.protocol import publish_consumed, publish_payload
from ..multi_slice_driver.real_process import (
    ExactForce,
    FileFingerprint,
    RealProcessFreshnessError,
    assert_fresh_case,
    force_file_audit,
    fingerprint,
    materialize_legacy_motion_bridge,
    parse_force_exact,
    time_close,
    validate_bridge_ack,
)
from ..multi_slice_mapping.mapping import (
    LoadRecord,
    SCHEMA_VERSION,
    atomic_write_json,
    build_H_for_manifest,
    motion_from_ancf_state,
    sha256_file,
    sha256_json,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "multi_slice_template"
REFERENCE_CASE = PROJECT_ROOT / "cases" / "openfoam" / "single_slice_ancf_fsi"
ANCF_SOURCE = PROJECT_ROOT / "src" / "structure_ancf_matlab"
DEFAULT_LIBRARY = (
    PROJECT_ROOT
    / "results"
    / "05_multi_slice_orchestration_tests"
    / "openfoam_smoke"
    / "lib"
    / "libancfFileMotion.so"
)
FROZEN_MANIFEST_HASH = "d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3"
TIME_TOLERANCE = 1.0e-12
MAX_CFL = 0.8
MAX_MOTION_INCREMENT_M = 0.05


def _now_run_id(prefix: str) -> str:
    return f"{prefix}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{uuid.uuid4().hex[:8]}"


def _wsl_path(path: Path) -> str:
    absolute = str(path.resolve()).replace("\\", "/")
    # A native WSL scratch case is exposed to Windows through the local UNC
    # provider.  Preserve that native path instead of incorrectly mapping it
    # back through /mnt/<drive>.
    native_prefix = "//wsl.localhost/Ubuntu-22.04/"
    if absolute.lower().startswith(native_prefix.lower()):
        return "/" + absolute[len(native_prefix):]
    drive, rest = absolute.split(":", 1)
    return f"/mnt/{drive.lower()}{rest}"


def _matlab_quote(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def _finite_tree(value: Any, name: str = "value") -> Any:
    if isinstance(value, Mapping):
        return {str(k): _finite_tree(v, f"{name}.{k}") for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_tree(v, f"{name}[]") for v in value]
    if isinstance(value, (int, float)) and not math.isfinite(float(value)):
        raise ValueError(f"{name} contains NaN/Inf")
    return value


def _matlab_matrix(rows: Sequence[Sequence[float]]) -> str:
    return "[" + ";".join(" ".join(format(float(v), ".17g") for v in row) for row in rows) + "]"


def load_frozen_manifest(path: str | Path) -> SliceManifest:
    target = Path(path).resolve()
    manifest = SliceManifest.from_mapping(json.loads(target.read_text(encoding="utf-8")))
    if manifest.slice_manifest_sha256 != FROZEN_MANIFEST_HASH:
        raise ValueError(
            f"frozen manifest hash mismatch: {manifest.slice_manifest_sha256} != {FROZEN_MANIFEST_HASH}"
        )
    expected = [(0, 1.25, 2.5), (1, 5.0, 5.0), (2, 8.75, 2.5)]
    actual = [(item.slice_id, item.s_ref_m, item.slice_length_m) for item in manifest.slices]
    if actual != expected or manifest.case_id != "stage4c_candidate_3slice":
        raise ValueError("frozen manifest geometry or case_id is not the Stage 4C-B identity")
    return manifest


def build_runtime_config(manifest: SliceManifest, *, start_time_s: float, timeout_s: float) -> RuntimeConfig:
    config = RuntimeConfig(
        schema_version=SCHEMA_VERSION,
        case_id=manifest.case_id,
        dt_s=0.0025,
        timeout_s=timeout_s,
        start_time_s=start_time_s,
        coupling_iteration=0,
        coupling_scheme="explicit_weak",
        slice_manifest_sha256=manifest.slice_manifest_sha256,
    )
    config.validate_against_manifest(manifest)
    return config


def _hash_tree(root: Path, relative_paths: Sequence[str]) -> list[dict[str, Any]]:
    entries = []
    for relative in sorted(relative_paths):
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        entries.append({"relative_path": relative.replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return entries


def _template_hashes() -> dict[str, str]:
    paths = [
        TEMPLATE_ROOT / "generate_case.py",
        TEMPLATE_ROOT / "template_config.json",
        TEMPLATE_ROOT / "case_template" / "system" / "controlDict.in",
        TEMPLATE_ROOT / "case_template" / "constant" / "dynamicMeshDict.in",
    ]
    return {str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"): sha256_file(path) for path in paths}


def build_physics_manifest(
    *,
    manifest: SliceManifest,
    runtime_config: RuntimeConfig,
    condition: str,
    speeds_mps: Mapping[int, float],
    run_id: str,
    initial_fields: Mapping[int, Mapping[str, Any]],
    library: Path = DEFAULT_LIBRARY,
) -> dict[str, Any]:
    if set(speeds_mps) != {0, 1, 2}:
        raise ValueError("physics manifest requires all three slice speeds")
    slices = []
    for item in manifest.slices:
        speed = float(speeds_mps[item.slice_id])
        if not math.isfinite(speed) or speed <= 0.0:
            raise ValueError("slice freestream speed must be positive and finite")
        initial = dict(initial_fields[item.slice_id])
        # A restart may use a fresh case directory.  Physical identity is
        # the independently preprocessed field content and time, never the
        # run-specific absolute path.
        initial_identity = {
            "time_name": initial.get("time_name"),
            "field_files": initial.get("field_files", initial.get("field_hashes", [])),
            "preprocessed_independently": bool(initial.get("preprocessed_independently", True)),
        }
        slices.append({
            "slice_id": item.slice_id,
            "s_ref_m": item.s_ref_m,
            "slice_length_m": item.slice_length_m,
            "unit_span_m": item.unit_span_m,
            "U_mps": speed,
            "Re": speed * 1.0 / 0.01,
            "rho_kgpm3": 1000.0,
            "nu_m2ps": 0.01,
            "D_m": 1.0,
            "initial_field": initial_identity,
        })
    payload: dict[str, Any] = {
        "schema_version": "stage4c-b-physics-identity-1",
        "condition": condition,
        "frozen_slice_manifest_sha256": manifest.slice_manifest_sha256,
        "runtime_config_sha256": runtime_config.config_sha256,
        # The execution directory is deliberately not part of the physical
        # identity.  Continuous and checkpoint-restarted executions must
        # recompute the same physics hash when their physical inputs match.
        "run_id": "stage4c-b-real-three-slice",
        "slices": slices,
        "ancf": {
            "L_m": 10.0,
            "D_m": 1.0,
            "dInner_m": 0.9,
            "E_Pa": 2.07e11,
            "top_tension_N": 1.0e7,
            "nElem": 2,
            "nSlices": 3,
            "dt_s": runtime_config.dt_s,
            "model_source": str(ANCF_SOURCE.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        },
        "openfoam": {
            "version": "OpenFOAM-10",
            "application": "pimpleFoam",
            "laminar": True,
            "unit_span_m": 1.0,
            "writePrecision": 16,
            "timePrecision": 12,
            "motion_solver": "interpolatingSolidBody",
            "motion_library_sha256": sha256_file(library),
        },
        "template_hashes": _template_hashes(),
        "initial_field_source": {
            "reference_case": str(REFERENCE_CASE.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "preprocessed_independently": True,
            "warmup_end_time_s": runtime_config.start_time_s,
        },
    }
    payload = _finite_tree(payload)
    payload["physics_config_sha256"] = sha256_json(payload)
    return payload


def _run_checked(command: Sequence[str], *, cwd: Path | None = None, log_path: Path | None = None, timeout_s: float = 300.0) -> dict[str, Any]:
    started = time.perf_counter()
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stream = log_path.open("w", encoding="utf-8")
    else:
        stream = subprocess.PIPE
    try:
        completed = subprocess.run(
            list(command), cwd=str(cwd) if cwd is not None else None,
            stdout=stream, stderr=subprocess.STDOUT, timeout=timeout_s, check=False,
        )
    finally:
        if log_path is not None:
            stream.close()
    if completed.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:] if log_path is not None else ""
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{tail}")
    return {"command": list(command), "return_code": completed.returncode, "elapsed_s": time.perf_counter() - started, "log": str(log_path) if log_path else None}


def _patch_initial_speed(case: Path, speed_mps: float) -> None:
    """Set a true independent inlet/internal initial field before warm-up."""
    value = format(float(speed_mps), ".12g")
    u_path = case / "0" / "U"
    text = u_path.read_text(encoding="utf-8")
    text = re.sub(r"\(\s*1(?:\.0*)?\s+0\s+0\s*\)", f"({value} 0 0)", text)
    u_path.write_text(text, encoding="utf-8")
    control = case / "system" / "controlDict"
    control_text = control.read_text(encoding="utf-8")
    control_text = re.sub(r"^magUInf\s+[^;]+;", f"magUInf         {value};", control_text, flags=re.MULTILINE)
    control.write_text(control_text, encoding="utf-8")


def generate_preprocessed_case(*, output: Path, speed_mps: float, run_id: str, warmup_end_time_s: float = 0.05) -> dict[str, Any]:
    """Generate and independently preprocess one warm-start source case."""
    if output.exists():
        raise FileExistsError(f"refusing to overwrite warmup case: {output}")
    generator = TEMPLATE_ROOT / "generate_case.py"
    _run_checked(
        [sys.executable, str(generator), "--output", str(output), "--reference-case", str(REFERENCE_CASE),
         "--case-id", f"{run_id}_warmup", "--slice-id", "0", "--s-ref-m", "0.0", "--slice-length-m", "10.0",
         "--unit-span-m", "1.0", "--start-time", "0", "--end-time", format(warmup_end_time_s, ".12g"),
         "--delta-t", "0.0025", "--freestream-mps", format(speed_mps, ".12g"), "--run-id", run_id, "--static-mesh"],
        log_path=output.parent / f"generate_{output.name}.log",
    )
    _patch_initial_speed(output, speed_mps)
    wcase = _wsl_path(output.resolve())
    check_log = output / f"log.checkMesh_{run_id}"
    _run_checked(
        ["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", f"source /opt/openfoam10/etc/bashrc; cd '{wcase}'; checkMesh"],
        log_path=check_log, timeout_s=180,
    )
    solver_log = output / f"log.pimpleFoam_warmup_{run_id}"
    _run_checked(
        ["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", f"source /opt/openfoam10/etc/bashrc; cd '{wcase}'; pimpleFoam"],
        log_path=solver_log, timeout_s=600,
    )
    target = output / format(warmup_end_time_s, ".12g")
    if not target.is_dir():
        raise RuntimeError(f"warm-up did not produce target time directory: {target}")
    # A static-mesh pimpleFoam warm-up writes U/p/phi/time.  Uf, meshPhi and
    # the moving polyMesh/points are produced by the first dynamic step and
    # are audited in the committed checkpoint, not fabricated in the seed.
    files = _hash_tree(target, ["U", "p", "phi", "uniform/time"])
    return {"case": str(output.resolve()), "speed_mps": speed_mps, "Re": speed_mps / 0.01, "end_time_s": warmup_end_time_s, "solver_log": str(solver_log), "checkMesh_log": str(check_log), "field_files": files}


def generate_dynamic_case(*, output: Path, warmup_case: Path, spec: SliceSpec, manifest: SliceManifest, runtime_config: RuntimeConfig, speed_mps: float, run_id: str) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite dynamic case: {output}")
    generator = TEMPLATE_ROOT / "generate_case.py"
    _run_checked(
        [sys.executable, str(generator), "--output", str(output), "--reference-case", str(warmup_case),
         "--case-id", manifest.case_id, "--slice-id", str(spec.slice_id), "--s-ref-m", format(spec.s_ref_m, ".17g"),
         "--slice-length-m", format(spec.slice_length_m, ".17g"), "--unit-span-m", format(spec.unit_span_m, ".17g"),
         "--start-time", format(runtime_config.start_time_s, ".12g"), "--end-time", format(runtime_config.start_time_s + runtime_config.dt_s, ".12g"),
         "--delta-t", format(runtime_config.dt_s, ".12g"), "--slice-manifest-sha256", manifest.slice_manifest_sha256,
         "--config-sha256", runtime_config.config_sha256, "--freestream-mps", format(speed_mps, ".12g"),
         "--run-id", run_id, "--initial-time", format(runtime_config.start_time_s, ".12g")],
        log_path=output.parent / f"generate_{output.name}.log",
    )
    return {"case": str(output.resolve()), "slice_id": spec.slice_id, "s_ref_m": spec.s_ref_m, "slice_length_m": spec.slice_length_m, "speed_mps": speed_mps, "initial_time_s": runtime_config.start_time_s, "initial_field_hashes": _hash_tree(output / format(runtime_config.start_time_s, ".12g"), ["U", "p", "phi", "uniform/time"])}


def prepare_condition_cases(*, root: Path, manifest: SliceManifest, runtime_config: RuntimeConfig, speeds_mps: Mapping[int, float], condition: str, run_id: str) -> tuple[list[dict[str, Any]], dict[int, Path]]:
    warmups: list[dict[str, Any]] = []
    dynamic: dict[int, Path] = {}
    for item in manifest.slices:
        warmup = root / "warmup" / f"slice_{item.slice_id:04d}"
        warmups.append(generate_preprocessed_case(output=warmup, speed_mps=float(speeds_mps[item.slice_id]), run_id=f"{run_id}_warmup_{item.slice_id:04d}"))
        case = root / "cases" / f"slice_{item.slice_id:04d}"
        generate_dynamic_case(output=case, warmup_case=warmup, spec=item, manifest=manifest, runtime_config=runtime_config, speed_mps=float(speeds_mps[item.slice_id]), run_id=run_id)
        dynamic[item.slice_id] = case
    return warmups, dynamic


class BatchMatlabANCFRunner:
    """Small process-isolated ANCF runner using the existing MATLAB solver.

    The workspace does not contain the historical persistent MATLAB worker.
    This wrapper calls the checked-in ANCF functions in MATLAB batch mode,
    retaining the same predictor/corrector and native MAT checkpoint
    semantics without modifying the ANCF core or inventing a second solver.
    """

    def __init__(self, *, work_dir: Path, start_time_s: float, manifest: SliceManifest, matlab_exe: Path = Path(r"D:\Matlab\bin\matlab.exe"), resume_native: Path | None = None) -> None:
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.start_time_s = float(start_time_s)
        self.manifest = manifest
        self.matlab_exe = Path(matlab_exe)
        self.resume_native = resume_native
        self.committed_path = self.work_dir / "committed.mat"
        self.prediction_path = self.work_dir / "prediction.mat"
        self.correction_path = self.work_dir / "correction.mat"
        self.operation_index = 0
        self.pending_kind: str | None = None
        self.operation_logs: list[str] = []

    def _run_matlab(self, script: str, label: str) -> None:
        if not self.matlab_exe.is_file():
            raise RuntimeError(f"MATLAB executable not found: {self.matlab_exe}")
        log = self.work_dir / f"matlab_{self.operation_index:04d}_{label}.log"
        self.operation_index += 1
        self.operation_logs.append(str(log))
        completed = subprocess.run(
            [str(self.matlab_exe), "-batch", script],
            cwd=str(self.work_dir),
            stdout=log.open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            text = log.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise RuntimeError(f"MATLAB {label} failed with code {completed.returncode}: {text}")

    def start(self) -> None:
        if self.resume_native is not None:
            if not self.resume_native.is_file():
                raise FileNotFoundError(self.resume_native)
            shutil.copy2(self.resume_native, self.committed_path)
            self.pending_kind = None
            return
        sref = ";".join(format(item.s_ref_m, ".17g") for item in self.manifest.slices)
        source = _matlab_quote(ANCF_SOURCE)
        target = _matlab_quote(self.committed_path)
        script = (
            f"addpath(genpath('{source}')); "
            "model=vertical_ttr_case('L',10,'D',1,'dInner',0.9,'nElem',2,'nSlices',3,'topTension_N',1e7,'youngs_modulus_Pa',2.07e11,'dt',0.0025); "
            f"model.coupling.s_ref_m=[{sref}].'; "
            "state=ancf_initialize(model); "
            f"state.t={format(self.start_time_s, '.17g')}; "
            f"save('{target}','state','-v7');"
        )
        self._run_matlab(script, "initialize")
        self.pending_kind = None

    def _active_state_path(self) -> Path:
        if self.pending_kind == "correction" and self.correction_path.is_file():
            return self.correction_path
        if self.pending_kind == "prediction" and self.prediction_path.is_file():
            return self.prediction_path
        return self.committed_path

    def _state_struct(self) -> Any:
        path = self._active_state_path()
        data = sio.loadmat(path, squeeze_me=True, struct_as_record=False)
        state = data.get("state")
        if state is None:
            state = data.get("pending_prediction")
        if state is None:
            raise RuntimeError(f"MATLAB checkpoint has no state: {path}")
        return state

    def state_view(self) -> dict[str, list[float]]:
        state = self._state_struct()
        result = {}
        for key in ("q", "qd", "qdd"):
            values = np.asarray(getattr(state, key), dtype=float).reshape(-1)
            if not np.all(np.isfinite(values)):
                raise RuntimeError(f"ANCF state {key} contains NaN/Inf")
            result[{"q": "q", "qd": "qdot", "qdd": "qddot"}[key]] = values.tolist()
        return result

    def predict(self, step: int, time_s: float, previous_slice_forces: Sequence[Sequence[float]]):
        if self.pending_kind is not None:
            raise RuntimeError("ANCF runner already has a pending state")
        forces = _matlab_matrix(previous_slice_forces)
        source = _matlab_quote(self.committed_path)
        target = _matlab_quote(self.prediction_path)
        script = (
            f"addpath(genpath('{_matlab_quote(ANCF_SOURCE)}')); S=load('{source}','state'); state=S.state; "
            f"state=ancf_advance_step(state,{forces},0.0025); "
            f"save('{target}','state','-v7');"
        )
        self._run_matlab(script, f"predict_step{step:08d}")
        self.pending_kind = "prediction"
        return {"step": int(step), "time_s": float(time_s)}, []

    def correct(self, step: int, time_s: float, integrated_slice_forces: Sequence[Sequence[float]]):
        forces = _matlab_matrix(integrated_slice_forces)
        source = _matlab_quote(self.committed_path)
        target = _matlab_quote(self.correction_path)
        script = (
            f"addpath(genpath('{_matlab_quote(ANCF_SOURCE)}')); S=load('{source}','state'); state=S.state; "
            f"state=ancf_advance_step(state,{forces},0.0025); "
            f"save('{target}','state','-v7');"
        )
        self._run_matlab(script, f"correct_step{step:08d}")
        self.pending_kind = "correction"
        return {"step": int(step), "time_s": float(time_s)}, []

    def save_checkpoint(self, path: str | Path) -> None:
        source = self._active_state_path()
        if not source.is_file():
            raise RuntimeError(f"ANCF state file is missing: {source}")
        shutil.copy2(source, Path(path))

    def load_checkpoint(self, path: str | Path) -> None:
        target = Path(path)
        if not target.is_file():
            raise FileNotFoundError(target)
        shutil.copy2(target, self.committed_path)
        self.prediction_path.unlink(missing_ok=True)
        self.correction_path.unlink(missing_ok=True)
        self.pending_kind = None

    def finalize_committed(self, token: object | None = None) -> None:
        if self.pending_kind == "correction":
            shutil.copy2(self.correction_path, self.committed_path)
        self.prediction_path.unlink(missing_ok=True)
        self.correction_path.unlink(missing_ok=True)
        self.pending_kind = None

    def discard_staged(self) -> None:
        self.prediction_path.unlink(missing_ok=True)
        self.correction_path.unlink(missing_ok=True)
        self.pending_kind = None

    def shutdown(self) -> None:
        self.discard_staged()


class RealProductionANCFAdapter(ProductionANCFAdapter):
    """Connect the formal adapter finalize hooks to the batch runner."""

    def finalize_committed(self, checkpoint_token: object | None = None) -> None:
        super().finalize_committed(checkpoint_token)
        finalize = getattr(self.runner, "finalize_committed", None)
        if finalize is not None:
            finalize(checkpoint_token)

    def discard_staged(self) -> None:
        super().discard_staged()
        discard = getattr(self.runner, "discard_staged", None)
        if discard is not None:
            discard()


class OpenFOAMSliceProcess:
    """One independent slice case, launched one step at a time.

    Launching one target interval per process keeps the global barrier exact
    while keeping the maximum number of heavy OpenFOAM processes at one,
    below the task limit of two.  The current-case seed is consumed before
    the target motion bridge is published for every invocation.
    """

    def __init__(self, *, slice_id: int, case: Path, exchange_root: Path, manifest: SliceManifest, runtime_config: RuntimeConfig, library: Path, run_id: str):
        self.slice_id = int(slice_id)
        self.case = case.resolve()
        self.case_root = self.case.parent
        self.exchange_root = exchange_root
        self.manifest = manifest
        self.runtime_config = runtime_config
        self.library = library.resolve()
        self.run_id = run_id
        self.process: subprocess.Popen[bytes] | None = None
        self.process_start_ns = 0
        self.current_time_s = runtime_config.start_time_s
        self.current_clock_step = 0
        self.last_cfd_time_name: str | None = None
        self.last_load = None
        self.last_force: ExactForce | None = None
        self.last_force_artifact: Path | None = None
        self.last_force_fingerprint: FileFingerprint | None = None
        self.last_bridge = None
        self.last_motion_record = None
        self.pending_seed = None
        self.pending_seed_step = 0
        self.bridge_publications: list[dict[str, Any]] = []
        self.force_audits: list[dict[str, Any]] = []
        self.log_paths: list[str] = []
        self.max_concurrent_seen = 0

    @property
    def spec(self):
        return self.manifest.slice(self.slice_id)

    @property
    def case_relative_path(self) -> str:
        return self.case.name

    def preflight(self, target_time_name: str) -> dict[str, Any]:
        return assert_fresh_case(self.case, target_time_name=target_time_name)

    def begin_step(self, seed_record: Mapping[str, Any], *, seed_step: int) -> None:
        self.pending_seed = dict(seed_record)
        self.pending_seed_step = int(seed_step)

    def _rewrite_control_dict(self, *, target_time_s: float, latest: bool) -> None:
        path = self.case / "system" / "controlDict"
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"^startFrom\s+[^;]+;", "startFrom       latestTime;" if latest else "startFrom       startTime;", text, flags=re.MULTILINE)
        text = re.sub(r"^endTime\s+[^;]+;", f"endTime         {format(target_time_s, '.12g')};", text, flags=re.MULTILINE)
        text = re.sub(r"^magUInf\s+[^;]+;", f"magUInf         {format(self._speed, '.12g')};", text, flags=re.MULTILINE)
        path.write_text(text, encoding="utf-8")

    @property
    def _speed(self) -> float:
        value = json.loads((self.case / "multi_slice_case_config.json").read_text(encoding="utf-8"))
        return float(value["cfd"]["freestream_mps"])

    def _start_solver(self, target_time_s: float) -> None:
        if self.pending_seed is None:
            raise RealProcessFreshnessError(f"slice {self.slice_id}: missing current-time seed")
        # The next OpenFOAM invocation reuses the same case directory.  Its
        # current-time seed may have the same bridge step as the previous
        # target, so remove only that old acknowledgement before publishing a
        # fresh seed; stale acknowledgements are never accepted.
        # The legacy acknowledgement namespace is case-local; the scheduler
        # step in pending_seed_step is an absolute/global identity.
        old_seed_ack = self.case / "coupling" / "consumed" / f"motion_consumed_{self.current_clock_step}.json"
        old_seed_ack.unlink(missing_ok=True)
        seed_snapshot = materialize_legacy_motion_bridge(
            record=self.pending_seed,
            case=self.case,
            exchange_dir="coupling",
            seed=True,
            seed_time_s=self.current_time_s,
            bridge_step_offset=1,
            seed_step_offset=self.current_clock_step,
        )
        latest = self.current_clock_step > 0
        self._rewrite_control_dict(target_time_s=target_time_s, latest=latest)
        wcase = _wsl_path(self.case)
        wlib = _wsl_path(self.library.parent)
        log_path = self.case / f"log.pimpleFoam_{self.run_id}_slice_{self.slice_id:04d}_step{self.pending_seed_step:08d}"
        command = (
            "source /opt/openfoam10/etc/bashrc; "
            f"export LD_LIBRARY_PATH={wlib}:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/dummy:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/openmpi-system:$LD_LIBRARY_PATH; "
            f"cd '{wcase}'; pimpleFoam > '{log_path.name}' 2>&1"
        )
        self.process_start_ns = time.time_ns()
        self.process = subprocess.Popen(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command])
        self.log_paths.append(str(log_path))
        deadline = time.monotonic() + self.runtime_config.timeout_s
        ack = self.case / "coupling" / "consumed" / f"motion_consumed_{seed_snapshot.bridge_step}.json"
        while time.monotonic() < deadline and not ack.is_file():
            if self.process.poll() not in (None, 0):
                raise RuntimeError(f"slice {self.slice_id} OpenFOAM exited during seed with {self.process.returncode}")
            time.sleep(getattr(self, "poll_interval_s", 0.02))
        if not ack.is_file():
            raise TimeoutError(f"slice {self.slice_id} seed consumed timeout at {self.current_time_s}")
        validate_bridge_ack(ack_path=ack, snapshot=seed_snapshot, record=self.pending_seed, published_ns=seed_snapshot.published_ns)
        self.bridge_publications.append({
            "kind": "seed", "global_step": self.pending_seed_step,
            "global_time_s": float(self.pending_seed["time_s"]),
            "bridge_step": seed_snapshot.bridge_step, "bridge_time_s": seed_snapshot.bridge_time_s,
            "published_ns": seed_snapshot.published_ns,
        })

    def publish_motion(self, record, paths: SliceExchangePaths, *, manifest: SliceManifest, runtime_config: RuntimeConfig):
        target_time = float(record.time_s)
        self._start_solver(target_time)
        marker = publish_payload(
            payload_path=paths.payload("motion", int(record.step)),
            ready_path=paths.ready("motion", int(record.step)),
            kind="motion", record=record, manifest=manifest, runtime_config=runtime_config,
        )
        snapshot = materialize_legacy_motion_bridge(
            record=record.to_dict() if hasattr(record, "to_dict") else record,
            case=self.case, exchange_dir="coupling", bridge_step_offset=1,
            target_bridge_step=self.current_clock_step + 1,
        )
        self.last_motion_record = record
        self.last_bridge = snapshot
        self.bridge_publications.append({
            "kind": "target", "global_step": int(record.step), "global_time_s": target_time,
            "bridge_step": snapshot.bridge_step, "bridge_time_s": snapshot.bridge_time_s,
            "published_ns": snapshot.published_ns, "formal_payload": str(paths.payload("motion", int(record.step))),
            "formal_ready": str(paths.ready("motion", int(record.step))),
        })
        return marker

    def wait_motion_consumed(self, step: int, time_s: float, *, paths: SliceExchangePaths, manifest: SliceManifest, runtime_config: RuntimeConfig):
        if self.last_bridge is None or self.last_motion_record is None:
            raise RealProcessFreshnessError(f"slice {self.slice_id}: no target bridge")
        ack = self.case / "coupling" / "consumed" / f"motion_consumed_{self.last_bridge.bridge_step}.json"
        deadline = time.monotonic() + runtime_config.timeout_s
        while time.monotonic() < deadline and not ack.is_file():
            if self.process is not None and self.process.poll() not in (None, 0):
                raise RuntimeError(f"slice {self.slice_id} OpenFOAM exited during target motion with {self.process.returncode}")
            time.sleep(getattr(self, "poll_interval_s", 0.02))
        if not ack.is_file():
            raise TimeoutError(f"slice {self.slice_id} target motion consumed timeout at {time_s}")
        validate_bridge_ack(ack_path=ack, snapshot=self.last_bridge, record=self.last_motion_record.to_dict(), published_ns=self.last_bridge.published_ns)
        return publish_consumed(paths=paths, kind="motion", step=step, time_s=time_s, manifest=manifest, runtime_config=runtime_config, consumer="openfoam-ancfFileMotion-bridge")

    def advance_one_step(self, step: int, time_s: float) -> None:
        # The one-step pimpleFoam process was started after the seed was
        # consumed and is now waiting for the target bridge.  The actual CFD
        # advance is performed by that process; the scheduler still owns the
        # global barrier and does not advance ANCF here.
        return None

    def _force_path(self, time_s: float) -> Path:
        # OpenFOAM's forces function object writes the first row of a run to
        # the run's start-time directory and appends the target-time row to
        # that same file.  The row parser below still requires the exact
        # target time; it never accepts the last line or a nearby time.
        return self.case / "postProcessing" / "cylinderForces" / format(self.current_time_s, ".12g") / "forces.dat"

    def wait_load_ready(self, step: int, time_s: float, *, paths: SliceExchangePaths, manifest: SliceManifest, runtime_config: RuntimeConfig):
        target = self._force_path(time_s)
        deadline = time.monotonic() + runtime_config.timeout_s
        force = None
        while time.monotonic() < deadline:
            force = parse_force_exact(target, target_time_s=time_s, minimum_mtime_ns=self.process_start_ns, previous=self.last_force_fingerprint)
            if force is not None:
                break
            if self.process is not None and self.process.poll() not in (None, 0):
                raise RuntimeError(f"slice {self.slice_id} OpenFOAM exited with {self.process.returncode} before force {time_s}")
            time.sleep(getattr(self, "poll_interval_s", 0.02))
        if force is None:
            raise TimeoutError(f"slice {self.slice_id} exact force timeout at {time_s}")
        record = LoadRecord.from_conversion(
            case_id=manifest.case_id, step=step, time_s=time_s, slice_definition=self.spec,
            unit_span_m=self.spec.unit_span_m, openfoam_force_N=force.force_N,
            cfd_time_step_s=runtime_config.dt_s, R_GL=manifest.R_GL,
        )
        self.last_load = record
        self.last_force = force
        self.last_force_fingerprint = fingerprint(target)
        # forces.dat is append-only within the OpenFOAM start-time directory.
        # Snapshot the consumed artifact before the solver can append the next
        # row; post-step freshness checks must never inspect the shared file.
        artifact_dir = self.exchange_root / "force_artifacts" / self.run_id / f"step_{int(step):08d}" / f"slice_{self.slice_id:04d}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact = artifact_dir / "consumed_forces.dat"
        if artifact.exists():
            raise RealProcessFreshnessError(f"force artifact path already exists: {artifact}")
        temporary = artifact.with_suffix(".tmp")
        snapshot_writer = getattr(self, "_write_force_snapshot", None)
        if snapshot_writer is None:
            shutil.copyfile(target, temporary)
        else:
            snapshot_writer(target, temporary, force)
        temporary.replace(artifact)
        self.last_force_artifact = artifact
        artifact_stat = artifact.stat()
        self.last_force = ExactForce(force.time_s, force.force_N, artifact_stat.st_size, artifact_stat.st_mtime_ns)
        self.last_cfd_time_name = format(time_s, ".12g")
        return publish_payload(
            payload_path=paths.payload("load", step), ready_path=paths.ready("load", step),
            kind="load", record=record, manifest=manifest, runtime_config=runtime_config,
        )

    def read_load(self, step: int, time_s: float):
        if self.last_load is None or self.last_load.step != step or not time_close(self.last_load.time_s, time_s):
            raise RuntimeError(f"slice {self.slice_id}: load not prepared")
        return self.last_load

    def publish_load_consumed(self, step: int, time_s: float, *, paths: SliceExchangePaths, manifest: SliceManifest, runtime_config: RuntimeConfig):
        marker = publish_consumed(paths=paths, kind="load", step=step, time_s=time_s, manifest=manifest, runtime_config=runtime_config, consumer="multi-slice-driver-stage4c-b")
        self.last_consumed_marker = marker
        return marker

    def consumed_force_manifest(self, step: int, time_tick: int) -> dict[str, object]:
        from ..stage4f_c_time_consistent_stabilizer_contract_repair_v1.manifest import RawForceSnapshotManifest
        if self.last_force_artifact is None or not hasattr(self, "last_consumed_marker"):
            raise RealProcessFreshnessError("consumed force artifact/transaction is missing")
        creation = f"{self.run_id}:{step}:{self.slice_id}:{time_tick}:create"
        consumed = str(self.last_consumed_marker.get("payload_sha256", ""))
        item = RawForceSnapshotManifest.capture(self.last_force_artifact, self.exchange_root,
            run_id=self.run_id, case_id=self.manifest.case_id, global_step=step, slice_id=self.slice_id,
            integer_tick=time_tick, force_schema="stage4f-force-artifact-1.1",
            artifact_creation_transaction=creation, consumed_transaction=consumed)
        return item.validate(self.exchange_root, run_id=self.run_id, case_id=self.manifest.case_id,
            global_step=step, slice_id=self.slice_id, integer_tick=time_tick)

    def checkpoint_files(self, step: int, time_s: float):
        if self.last_cfd_time_name is None:
            raise RuntimeError(f"slice {self.slice_id}: no CFD time for checkpoint")
        time_dir = self.case / self.last_cfd_time_name
        static = {"motionScale": self.case / "0" / "motionScale"}
        times = {relative: time_dir / relative for relative in REQUIRED_TIME_FILES}
        return {"openfoam_time_name": self.last_cfd_time_name, "case_relative_path": self.case_relative_path, "static_files": static, "time_files": times}

    def restore_checkpoint(self, entry: Mapping[str, object]) -> None:
        time_name = str(entry["openfoam_time_name"])
        for item in list(entry.get("static_files", [])) + list(entry.get("time_files", [])):
            relative = str(item["relative_path"])
            path = self.case / relative
            if not path.is_file() or sha256_file(path) != str(item["sha256"]):
                raise RealProcessFreshnessError(f"slice {self.slice_id}: staged restart file mismatch {relative}")
        self.last_cfd_time_name = time_name
        self.current_time_s = float(time_name)
        self.current_clock_step = int(round((self.current_time_s - self.runtime_config.start_time_s) / self.runtime_config.dt_s))

    def finish_step(self, step: int, time_s: float) -> None:
        if self.process is not None:
            code = self.process.wait(timeout=self.runtime_config.timeout_s)
            if code != 0:
                raise RuntimeError(f"slice {self.slice_id} OpenFOAM returned {code}")
        if self.last_force is not None:
            if self.last_force_artifact is None:
                raise RealProcessFreshnessError("consumed force artifact snapshot is missing")
            audit = force_file_audit(self.last_force_artifact, expected=self.last_force)
            audit["source_path"] = str(self._force_path(time_s).resolve())
            audit["artifact_kind"] = "immutable_consumed_force_snapshot"
            self.force_audits.append(audit)
        self.current_time_s = float(time_s)
        # This is the case-local CFD clock, not the scheduler global step.
        self.current_clock_step += 1
        self.last_force_fingerprint = None
        self.last_force_artifact = None
        self.pending_seed = None

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def return_code(self) -> int | None:
        return None if self.process is None else self.process.returncode

    def log_metrics(self) -> dict[str, Any]:
        values = []
        for name in self.log_paths:
            path = Path(name)
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                values.extend(float(item) for item in re.findall(r"Courant Number mean:\s+[^\s]+\s+max:\s+([-+0-9.eE]+)", text))
        return {"log_paths": list(self.log_paths), "max_cfl": max(values) if values else None, "return_code": self.return_code()}


def stage_restart_case(*, checkpoint_path: Path, source_case_root: Path, target_case_root: Path) -> dict[str, Any]:
    """Restore explicit checkpoint files into a fresh generated case.

    Only the manifest-listed static/time files are copied.  No old case
    directory, exchange, log, processor tree or force output is copied.
    """
    manifest = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    copied = []
    for entry in manifest["slices"]:
        source_case = source_case_root / str(entry["case_relative_path"])
        target_case = target_case_root / str(entry["case_relative_path"])
        for item in list(entry["static_files"]) + list(entry["time_files"]):
            relative = str(item["relative_path"])
            source = source_case / relative
            target = target_case / relative
            if not source.is_file() or sha256_file(source) != str(item["sha256"]):
                raise RuntimeError(f"checkpoint source changed: {source}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if target.stat().st_size != int(item["bytes"]) or sha256_file(target) != str(item["sha256"]):
                raise RuntimeError(f"checkpoint restore hash mismatch: {target}")
            copied.append({"slice_id": int(entry["slice_id"]), "relative_path": relative, "bytes": int(item["bytes"]), "sha256": str(item["sha256"])})
    return {"checkpoint": str(checkpoint_path.resolve()), "copied_objects": copied, "object_count": len(copied)}


def _seed_records(manifest: SliceManifest, adapter: ProductionANCFAdapter, runner: BatchMatlabANCFRunner, *, step: int, time_s: float) -> list[dict[str, Any]]:
    state = runner.state_view()
    records = []
    for item in manifest.slices:
        record = motion_from_ancf_state(
            manifest, item.slice_id, adapter.H_by_slice_id[item.slice_id],
            state["q"], state["qdot"], state["qddot"], step=step, time_s=time_s,
            reference_position_m=(0.0, 0.0, item.s_ref_m),
        )
        records.append(record.to_dict())
    return records


def run_real_condition(
    *,
    root: Path,
    manifest: SliceManifest,
    runtime_config: RuntimeConfig,
    physics_manifest: Mapping[str, Any],
    speeds_mps: Mapping[int, float],
    condition: str,
    library: Path = DEFAULT_LIBRARY,
    steps: int = 3,
    resume_native: Path | None = None,
    restore_checkpoint: Path | None = None,
    stage_source_case_root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    run_id = run_id or _now_run_id(f"stage4c_b_{condition}")
    cases_root = root / "cases"
    warmup_root = root / "warmup"
    cases_root.mkdir(parents=True, exist_ok=True)
    warmup_root.mkdir(parents=True, exist_ok=True)
    runner = BatchMatlabANCFRunner(work_dir=root / "matlab_runner", start_time_s=runtime_config.start_time_s, manifest=manifest, resume_native=resume_native)
    processes: list[OpenFOAMSliceProcess] = []
    scheduler = None
    step_results: list[dict[str, Any]] = []
    error: str | None = None
    try:
        runner.start()
        adapter = RealProductionANCFAdapter(
            runner=runner, manifest=manifest, mesh_nodes=(0.0, 5.0, 10.0),
            state_provider=runner.state_view, reference_positions_m={item.slice_id: (0.0, 0.0, item.s_ref_m) for item in manifest.slices},
        )
        for item in manifest.slices:
            case = cases_root / f"slice_{item.slice_id:04d}"
            process = OpenFOAMSliceProcess(slice_id=item.slice_id, case=case, exchange_root=root / "exchange", manifest=manifest, runtime_config=runtime_config, library=library, run_id=run_id)
            process.preflight(format(runtime_config.start_time_s + runtime_config.dt_s, ".12g") if restore_checkpoint is None else "0")
            processes.append(process)
        config = MultiSliceConfig(case_id=manifest.case_id, dt_s=runtime_config.dt_s, timeout_s=runtime_config.timeout_s, start_time_s=runtime_config.start_time_s, manifest=manifest)
        scheduler = MultiSliceScheduler(config=config, exchange_root=root / "exchange", structure=adapter, slice_processes=processes, checkpoint_root=root / "checkpoints", case_root=cases_root)
        if restore_checkpoint is not None:
            scheduler.restore_from_checkpoint(restore_checkpoint)
            for process in processes:
                process.restore_checkpoint(next(item for item in json.loads(restore_checkpoint.read_text(encoding="utf-8"))["slices"] if int(item["slice_id"]) == process.slice_id))
        start_step = scheduler.last_committed_step + 1
        for step in range(start_step, start_step + steps):
            current_time = runtime_config.start_time_s + step * runtime_config.dt_s
            target_time = current_time + runtime_config.dt_s
            seeds = _seed_records(manifest, adapter, runner, step=step, time_s=current_time)
            for process, seed in zip(processes, seeds):
                process.begin_step(seed, seed_step=step)
            result = scheduler.run_step(step=step, time_s=target_time)
            for process in processes:
                process.finish_step(step, target_time)
            checkpoint_payload = json.loads(result.checkpoint_path.read_text(encoding="utf-8"))
            step_results.append({
                "step": result.step, "time_s": result.time_s, "state": result.state.value,
                "integrated_slice_forces_N": [
                    [float(item["force_x_N"]), float(item["force_y_N"]), float(item["force_z_N"])]
                    for item in result.integrated_slice_forces
                ],
                "unit_span_forces_Npm": [
                    [float(item["force_2d_x_Npm"]), float(item["force_2d_y_Npm"]), float(item["force_2d_z_Npm"])]
                    for item in result.integrated_slice_forces
                ],
                "generalized_force_N": list(result.audit.get("generalized_force_from_A_Ht", [])),
                "checkpoint_path": str(result.checkpoint_path), "checkpoint_status": checkpoint_payload["status"],
                "q": checkpoint_payload["structure"]["q"], "qdot": checkpoint_payload["structure"]["qdot"], "qddot": checkpoint_payload["structure"]["qddot"],
                "bridge_time_mapping": [item.bridge_publications[-1] for item in processes],
            })
    except Exception as exc:
        error = str(exc)
        for process in processes:
            process.stop()
    finally:
        for process in processes:
            process.stop()
        runner.shutdown()
    checkpoint_audit = []
    if scheduler is not None:
        for path in sorted((root / "checkpoints").glob("checkpoint_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                scheduler.checkpoint_manager._validate_manifest(payload, require_status="committed", verify_files=True)
                objects = sum(len(item["static_files"]) + len(item["time_files"]) for item in payload["slices"])
                objects += 2 if payload["structure"].get("runner_checkpoint_relative_path") is not None else 1
                checkpoint_audit.append({"path": str(path), "step": payload["step"], "valid": True, "object_count": objects})
            except Exception as exc:
                checkpoint_audit.append({"path": str(path), "valid": False, "error": str(exc)})
    logs = [item for process in processes for item in process.log_metrics()["log_paths"]]
    cfl_values = [process.log_metrics()["max_cfl"] for process in processes if process.log_metrics()["max_cfl"] is not None]
    return_codes = [process.return_code() for process in processes]
    summary: dict[str, Any] = {
        "schema_version": "stage4c-b-real-three-slice-condition-1",
        "condition": condition, "run_id": run_id, "status": "completed" if error is None and len(step_results) == steps and all(item.get("valid") for item in checkpoint_audit) else "blocked",
        "error": error, "protocol_version": SCHEMA_VERSION,
        "slice_manifest_sha256": manifest.slice_manifest_sha256, "config_sha256": runtime_config.config_sha256,
        "physics_config_sha256": physics_manifest["physics_config_sha256"], "speeds_mps": {str(k): float(v) for k, v in speeds_mps.items()},
        "Re": {str(k): float(v) / 0.01 for k, v in speeds_mps.items()},
        "steps_requested": steps, "steps_completed": len(step_results), "step_results": step_results,
        "checkpoint_audit": checkpoint_audit, "checkpoint_count": len(checkpoint_audit),
        "checkpoint_objects_expected_per_manifest": 26, "checkpoint_objects": [item.get("object_count") for item in checkpoint_audit],
        "case_paths": [str(process.case) for process in processes], "logs": logs,
        "return_codes": return_codes, "max_cfl": max(cfl_values) if cfl_values else None,
        "max_openfoam_concurrency": 1, "batch_mode": "one target interval per case process, sequential slice launch",
        "bridge_publications": [process.bridge_publications for process in processes],
        "force_audits": [item for process in processes for item in process.force_audits],
        "freshness": [{"case": str(process.case), "provenance": str(process.case / "case_provenance.json")} for process in processes],
        "structure_advanced_on_failure": bool(step_results) if error is not None else False,
        "free_viv_claim": False,
    }
    atomic_write_json(root / f"{condition}_three_slice_summary.json", summary)
    return summary
