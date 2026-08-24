"""Prepare an auditable wet-ANCF equilibrium from the v2 dynamic hot-start."""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import scipy.io as sio

from ..multi_slice_driver.real_process import materialize_legacy_motion_bridge, parse_force_exact
from ..multi_slice_mapping.mapping import MotionRecord, SliceManifest, RuntimeConfig, atomic_write_json, sha256_file
from ..multi_slice_real_campaign.campaign import DEFAULT_LIBRARY, _wsl_path
from ..stage4f_dynamic_startup_v2.campaign import HOT_START_S, MAX_ABS_CD, MAX_CFL, _copy_hot_start

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MATLAB = Path(r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
HELPER_ROOT = PROJECT_ROOT / "src" / "structure_ancf_matlab" / "stage4f_b3_equilibrium"
V2_RUN = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_dynamic_startup_v2" / "run_20260817_dynamic_hotstart_v2_attempt6"
HOT_START_AUDIT = V2_RUN / "dynamic_hot_start_audit.json"
SLICE_LENGTH_M = 50.0 / 3.0
RECONCILIATION_END_S = 0.55
RECONCILIATION_STEPS = 200
PROTOCOL = PROJECT_ROOT / "results" / "11_stage4f_lowre_benchmark_design_v2_1" / "three_slice_protocol_0_2_1.json"


def mean_dynamic_hot_start_loads(audit_path: Path = HOT_START_AUDIT) -> list[list[float]]:
    """Convert the real unit-span hot-start force once to three integrated loads."""
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    force = audit["hot_start"]["steps"][-1]["openfoam_force_N"]
    if len(force) != 3 or not all(isinstance(v, (int, float)) for v in force):
        raise ValueError("hot-start force is not a finite 3-vector")
    value = [[float(component) * SLICE_LENGTH_M for component in force] for _ in range(3)]
    if not all(abs(row[0] / force[0] - SLICE_LENGTH_M) <= 1e-12 for row in value):
        raise RuntimeError("slice length would not be applied exactly once")
    return value


def _matlab_matrix(rows: list[list[float]]) -> str:
    return "[" + ";".join(" ".join(format(v, ".17g") for v in row) for row in rows) + "]"


def run_equilibrium(output_dir: Path, audit_path: Path = HOT_START_AUDIT) -> dict[str, Any]:
    """Run the existing static Newton method once in a fresh v3 directory."""
    if output_dir.exists():
        raise FileExistsError(output_dir)
    if not MATLAB.is_file():
        raise FileNotFoundError(MATLAB)
    output_dir.mkdir(parents=True)
    loads = mean_dynamic_hot_start_loads(audit_path)
    mat_path = output_dir / "equilibrated_state.mat"
    log_path = output_dir / "matlab_equilibrium.log"
    helper = str(HELPER_ROOT.resolve()).replace("\\", "/").replace("'", "''")
    target = str(mat_path.resolve()).replace("\\", "/").replace("'", "''")
    script = f"addpath('{helper}'); stage4f_b3_equilibrate('{target}',{_matlab_matrix(loads)});"
    with log_path.open("w", encoding="utf-8") as stream:
        completed = subprocess.run([str(MATLAB), "-batch", script], cwd=str(output_dir), stdout=stream, stderr=subprocess.STDOUT, timeout=240, check=False)
    if completed.returncode != 0 or not mat_path.is_file():
        raise RuntimeError(f"MATLAB equilibrium failed ({completed.returncode}): {log_path}")
    raw = sio.loadmat(mat_path, squeeze_me=True, struct_as_record=False)
    report = raw.get("report")
    if report is None:
        raise RuntimeError("equilibrium MAT has no report")
    static = report.static
    motion = report.slice_motion
    value: dict[str, Any] = {
        "status": str(report.status), "source_hot_start_audit": str(audit_path), "source_hot_start_sha256": sha256_file(audit_path),
        "slice_force_N": loads, "slice_length_m": SLICE_LENGTH_M,
        "static": {"converged": bool(static.converged), "residual_N": float(static.residual_N),
                   "maximum_green_strain": float(static.maximum_green_strain), "minimum_tension_N": float(static.minimum_tension_N),
                   "negative_tension_fraction": float(static.negative_tension_fraction), "passes": bool(static.passes)},
        "slice_motion": {key: [float(v) for v in getattr(motion, key).reshape(-1)] for key in ("x_m", "y_m", "z_m", "vx_mps", "vy_mps", "vz_mps", "ax_mps2", "ay_mps2", "az_mps2")},
        "max_xy_displacement_m": float(report.max_xy_displacement_m), "state_mat_sha256": sha256_file(mat_path), "matlab_log": str(log_path),
    }
    value["dynamic_shape_reconciliation_required"] = value["max_xy_displacement_m"] > 1.0e-12
    value["next_authorized_scope"] = "dynamic_mesh_reconciliation_ramp_only" if value["static"]["passes"] else "none"
    value["equilibrium_sha256"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    atomic_write_json(output_dir / "equilibrium_audit.json", value)
    return value


def smoothstep(alpha: float) -> float:
    """C1 ramp from zero to one; endpoint velocity is zero."""
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be in [0,1]")
    return alpha * alpha * (3.0 - 2.0 * alpha)


def _read_manifest() -> SliceManifest:
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    return SliceManifest.from_mapping(payload["manifest"])


def _config(manifest: SliceManifest) -> RuntimeConfig:
    return RuntimeConfig(schema_version="0.2.1", case_id=manifest.case_id, dt_s=0.0025, timeout_s=90.0,
        start_time_s=HOT_START_S, coupling_iteration=0, coupling_scheme="explicit_weak", slice_manifest_sha256=manifest.slice_manifest_sha256)


def _equilibrium_motion(path: Path) -> dict[str, list[float]]:
    value = json.loads(path.read_text(encoding="utf-8"))["slice_motion"]
    for field in ("x_m", "y_m", "z_m"):
        if len(value[field]) != 3 or not all(math.isfinite(float(x)) for x in value[field]):
            raise ValueError(f"invalid equilibrium {field}")
    return value


def _motion(manifest: SliceManifest, spec, motion: dict[str, list[float]], *, alpha: float, step: int, time_s: float) -> MotionRecord:
    index = spec.slice_id; amount = smoothstep(alpha)
    x, y, z = amount * motion["x_m"][index], amount * motion["y_m"][index], spec.s_ref_m + amount * (motion["z_m"][index] - spec.s_ref_m)
    return MotionRecord(schema_version="0.2.1", case_id=manifest.case_id, step=step, coupling_iteration=0, time_s=time_s,
        slice_id=index, s_ref_m=spec.s_ref_m, slice_length_m=spec.slice_length_m, x_ref_m=0.0, y_ref_m=0.0, z_ref_m=spec.s_ref_m,
        ux_m=x, uy_m=y, uz_m=z-spec.s_ref_m, x_m=x, y_m=y, z_m=z,
        vx_mps=0.0, vy_mps=0.0, vz_mps=0.0, ax_mps2=0.0, ay_mps2=0.0, az_mps2=0.0)


def _rewrite_reconciliation_control(case: Path) -> None:
    path = case / "system" / "controlDict"; text = path.read_text(encoding="utf-8")
    text = re.sub(r"^endTime\s+[^;]+;", f"endTime         {RECONCILIATION_END_S:.12g};", text, flags=re.MULTILINE)
    text = re.sub(r"^writeInterval\s+[^;]+;", f"writeInterval   {RECONCILIATION_STEPS};", text, flags=re.MULTILINE)
    path.write_text(text, encoding="utf-8")


def _run_one_reconciliation(case: Path, manifest: SliceManifest, config: RuntimeConfig, spec, motion: dict[str, list[float]]) -> dict[str, Any]:
    """Run one real pimpleFoam process while publishing each bridge state."""
    _rewrite_reconciliation_control(case)
    seed = _motion(manifest, spec, motion, alpha=0.0, step=0, time_s=HOT_START_S)
    seed_snapshot = materialize_legacy_motion_bridge(record=seed.to_dict(), case=case, exchange_dir="coupling", seed=True,
        seed_time_s=HOT_START_S, bridge_step_offset=1, seed_step_offset=0)
    wcase = _wsl_path(case); wlib = _wsl_path(DEFAULT_LIBRARY.parent)
    log_path = case / "log.pimpleFoam_stage4f_b3_reconciliation"
    command = ("source /opt/openfoam10/etc/bashrc; "
        f"export LD_LIBRARY_PATH={wlib}:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/dummy:$LD_LIBRARY_PATH; "
        f"cd '{wcase}'; pimpleFoam > '{log_path.name}' 2>&1")
    process = subprocess.Popen(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command])
    published = [{"bridge_step": seed_snapshot.bridge_step, "time_s": HOT_START_S, "alpha": 0.0}]
    try:
        for local_step in range(1, RECONCILIATION_STEPS + 1):
            ack = case / "coupling" / "consumed" / f"motion_consumed_{local_step - 1}.json"
            deadline = time.monotonic() + config.timeout_s
            while not ack.is_file() and time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"reconciliation solver exited {process.returncode} before bridge {local_step}")
                time.sleep(0.01)
            if not ack.is_file():
                raise TimeoutError(f"reconciliation bridge acknowledgement timeout at step {local_step - 1}")
            target_time = HOT_START_S + local_step * config.dt_s
            record = _motion(manifest, spec, motion, alpha=local_step / RECONCILIATION_STEPS, step=local_step - 1, time_s=target_time)
            snapshot = materialize_legacy_motion_bridge(record=record.to_dict(), case=case, exchange_dir="coupling", bridge_step_offset=1)
            published.append({"bridge_step": snapshot.bridge_step, "time_s": target_time, "alpha": local_step / RECONCILIATION_STEPS})
        code = process.wait(timeout=config.timeout_s)
        if code != 0:
            raise RuntimeError(f"reconciliation solver exited {code}")
    finally:
        if process.poll() is None:
            process.terminate(); process.wait(timeout=10)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    # OpenFOAM prints an informational line when SIGFPE trapping is enabled;
    # only actual fatal/non-finite diagnostics are stop conditions here.
    if "End" not in text or any(token in text for token in ("FOAM FATAL", "Floating point exception", "nan", "inf")):
        raise RuntimeError("reconciliation log is not finite/completed")
    cfl = [float(x) for x in re.findall(r"Courant Number mean:\s+[^\s]+\s+max:\s+([-+0-9.eE]+)", text)]
    if not cfl or max(cfl) >= MAX_CFL:
        raise RuntimeError(f"reconciliation CFL failed: {max(cfl) if cfl else None}")
    force_path = case / "postProcessing" / "cylinderForces" / f"{HOT_START_S:.12g}" / "forces.dat"
    force = parse_force_exact(force_path, target_time_s=RECONCILIATION_END_S)
    if force is None:
        raise RuntimeError("missing exact reconciliation endpoint force")
    cd = force.force_N[0] / 500.0
    if abs(cd) > MAX_ABS_CD:
        raise RuntimeError(f"reconciliation endpoint force scale failed: Cd={cd}")
    return {"slice_id": spec.slice_id, "endpoint_time_s": RECONCILIATION_END_S, "endpoint_force_N": list(force.force_N),
            "endpoint_Cd": cd, "max_cfl": max(cfl), "bridge_publications": published, "log": str(log_path)}


def run_dynamic_reconciliation(output_dir: Path, equilibrium_path: Path | None = None) -> dict[str, Any]:
    """Create and run three isolated dynamic-mesh shape reconciliation cases."""
    if output_dir.exists():
        raise FileExistsError(output_dir)
    equilibrium_path = equilibrium_path or (PROJECT_ROOT / "results" / "12_stage4f_equilibrated_startup_v3" / "equilibrium_audit.json")
    manifest = _read_manifest(); config = _config(manifest); motion = _equilibrium_motion(equilibrium_path)
    output_dir.mkdir(parents=True)
    source = V2_RUN / "dynamic_zero_warmup" / "slice_0000"
    materialized = []
    for spec in manifest.slices:
        target = output_dir / "cases" / f"slice_{spec.slice_id:04d}"
        materialized.append(_copy_hot_start(source=source, target=target, manifest=manifest, config=config, spec=spec))
    rows = [_run_one_reconciliation(output_dir / "cases" / f"slice_{spec.slice_id:04d}", manifest, config, spec, motion) for spec in manifest.slices]
    value = {"status": "passed", "equilibrium_audit": str(equilibrium_path), "equilibrium_sha256": sha256_file(equilibrium_path),
             "runtime_config": config.to_dict(), "start_time_s": HOT_START_S, "end_time_s": RECONCILIATION_END_S,
             "steps": RECONCILIATION_STEPS, "trajectory": "cubic_smoothstep_zero_to_static_equilibrium", "materialized": materialized,
             "slices": rows, "max_cfl": max(row["max_cfl"] for row in rows), "max_abs_Cd": max(abs(row["endpoint_Cd"]) for row in rows),
             "formal_fsi_started": False, "restart_authorized": False}
    atomic_write_json(output_dir / "dynamic_reconciliation_audit.json", value)
    return value
