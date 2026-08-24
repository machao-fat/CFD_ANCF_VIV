"""Settle the v3 equilibrium geometry under exactly zero subsequent motion."""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from ..multi_slice_driver.real_process import materialize_legacy_motion_bridge, parse_force_exact
from ..multi_slice_mapping.mapping import MotionRecord, atomic_write_json, sha256_file
from ..multi_slice_real_campaign.campaign import DEFAULT_LIBRARY, _wsl_path
from ..stage4f_equilibrated_startup_v3.equilibrium import (
    MAX_ABS_CD, PROJECT_ROOT, RECONCILIATION_END_S, _config, _equilibrium_motion, _motion, _read_manifest,
)

SOURCE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_equilibrated_startup_v3" / "reconciliation_20260817"
EQUILIBRIUM_AUDIT = PROJECT_ROOT / "results" / "12_stage4f_equilibrated_startup_v3" / "equilibrium_audit.json"
HOLD_START_S = 0.5
HOLD_END_S = 1.5
HOLD_STEPS = 400


def _copy_state(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(target)
    # OpenFOAM wrote the latest complete state at 0.5 s; its uniform/time
    # field establishes the only permissible source clock for this hold run.
    time_name = f"{HOLD_START_S:.12g}"
    target.mkdir(parents=True)
    shutil.copytree(source / "constant", target / "constant")
    shutil.copytree(source / "system", target / "system")
    shutil.copytree(source / time_name, target / time_name)
    (target / "0").mkdir(); shutil.copy2(source / "0" / "motionScale", target / "0" / "motionScale")
    for relative in ("coupling/motion", "coupling/load", "coupling/consumed", "postProcessing"):
        (target / relative).mkdir(parents=True, exist_ok=True)
    control = target / "system" / "controlDict"; text = control.read_text(encoding="utf-8")
    text = re.sub(r"^startFrom\s+[^;]+;", "startFrom       startTime;", text, flags=re.MULTILINE)
    text = re.sub(r"^startTime\s+[^;]+;", f"startTime       {HOLD_START_S:.12g};", text, flags=re.MULTILINE)
    text = re.sub(r"^endTime\s+[^;]+;", f"endTime         {HOLD_END_S:.12g};", text, flags=re.MULTILINE)
    text = re.sub(r"^writeInterval\s+[^;]+;", f"writeInterval   {HOLD_STEPS};", text, flags=re.MULTILINE)
    control.write_text(text, encoding="utf-8")
    dynamic = target / "constant" / "dynamicMeshDict"; mesh = dynamic.read_text(encoding="utf-8")
    mesh = re.sub(r"^\s*startTime\s+[^;]+;", f"        startTime       {HOLD_START_S:.12g};", mesh, flags=re.MULTILINE)
    dynamic.write_text(mesh, encoding="utf-8")


def run_hold(root: Path) -> dict:
    if root.exists():
        raise FileExistsError(root)
    manifest = _read_manifest(); config = _config(manifest); motion = _equilibrium_motion(EQUILIBRIUM_AUDIT)
    root.mkdir(parents=True); spec = manifest.slices[0]; source = SOURCE_ROOT / "cases" / "slice_0000"; case = root / "case_slice_0000"
    _copy_state(source, case)
    # The held value is exactly the equilibrium position at every CFD time.
    held_alpha = (0.9 * 0.9 * (3.0 - 2.0 * 0.9))
    seed = _motion(manifest, spec, motion, alpha=held_alpha, step=0, time_s=HOLD_START_S)
    snapshot = materialize_legacy_motion_bridge(record=seed.to_dict(), case=case, exchange_dir="coupling", seed=True,
        seed_time_s=HOLD_START_S, bridge_step_offset=1, seed_step_offset=0)
    wcase = _wsl_path(case); wlib = _wsl_path(DEFAULT_LIBRARY.parent); log = case / "log.pimpleFoam_stage4f_b4_hold"
    command = ("source /opt/openfoam10/etc/bashrc; "
        f"export LD_LIBRARY_PATH={wlib}:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/dummy:$LD_LIBRARY_PATH; "
        f"cd '{wcase}'; pimpleFoam > '{log.name}' 2>&1")
    process = subprocess.Popen(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command])
    try:
        for index in range(1, HOLD_STEPS + 1):
            ack = case / "coupling" / "consumed" / f"motion_consumed_{index - 1}.json"; deadline = time.monotonic() + config.timeout_s
            while not ack.is_file() and time.monotonic() < deadline:
                if process.poll() is not None: raise RuntimeError(f"hold solver exited {process.returncode}")
                time.sleep(.01)
            if not ack.is_file(): raise TimeoutError(f"hold bridge timeout {index}")
            target = HOLD_START_S + index * config.dt_s
            record = _motion(manifest, spec, motion, alpha=held_alpha, step=index - 1, time_s=target)
            materialize_legacy_motion_bridge(record=record.to_dict(), case=case, exchange_dir="coupling", bridge_step_offset=1)
        if process.wait(timeout=config.timeout_s) != 0: raise RuntimeError("hold solver failed")
    finally:
        if process.poll() is None: process.terminate(); process.wait(timeout=10)
    text = log.read_text(encoding="utf-8", errors="replace")
    if "End" not in text or "FOAM FATAL" in text: raise RuntimeError("hold log incomplete")
    cfl = [float(x) for x in re.findall(r"Courant Number mean:\s+[^\s]+\s+max:\s+([-+0-9.eE]+)", text)]
    force = parse_force_exact(case / "postProcessing" / "cylinderForces" / f"{HOLD_START_S:.12g}" / "forces.dat", target_time_s=HOLD_END_S)
    if force is None: raise RuntimeError("missing final hold force")
    result = {"status": "passed" if max(cfl) < .8 and abs(force.force_N[0]/500) <= MAX_ABS_CD else "blocked", "start_time_s": HOLD_START_S,
        "end_time_s": HOLD_END_S, "steps": HOLD_STEPS, "held_alpha": held_alpha, "motion": "held_at_equilibrium_zero_increment", "endpoint_force_N": list(force.force_N),
        "endpoint_Cd": force.force_N[0]/500, "max_cfl": max(cfl), "solver_completed": True, "log": str(log),
        "source_reconciliation_log_sha256": sha256_file(SOURCE_ROOT / "cases" / "slice_0000" / "log.pimpleFoam_stage4f_b3_reconciliation")}
    atomic_write_json(root / "held_geometry_audit.json", result)
    return result
