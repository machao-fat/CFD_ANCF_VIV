"""Move each CFD slice to the exact ANCF equilibrium and settle it in place."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from ..multi_slice_driver.real_process import materialize_legacy_motion_bridge
from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from ..multi_slice_real_campaign.campaign import DEFAULT_LIBRARY, _wsl_path
from ..stage4f_dynamic_startup_v2.campaign import HOT_START_S, _copy_hot_start
from ..stage4f_equilibrated_startup_v3.equilibrium import _config, _equilibrium_motion, _motion, _read_manifest, MAX_ABS_CD, MAX_CFL
from .fixed_point import force_window_statistics

MIGRATION_END_S = 0.5
MIGRATION_STEPS = 180
MIGRATION_WRITE_INTERVAL = 20
HOLD_END_S = 1.5
HOLD_STEPS = 400
TERMINAL_START_S = 1.0
TERMINAL_STEPS = 200
TERMINAL_WRITE_INTERVAL = 20
SOURCE = Path(__file__).resolve().parents[3] / "cases" / "openfoam" / "stage4f_lowre_three_slice_dynamic_startup_v2" / "run_20260817_dynamic_hotstart_v2_attempt6" / "dynamic_zero_warmup" / "slice_0000"


def _replace(path: Path, replacements: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = re.sub(rf"^{key}\s+[^;]+;", f"{key:<15}{value};", text, flags=re.MULTILINE)
    path.write_text(text, encoding="utf-8")


def _start_solver(case: Path, label: str) -> tuple[subprocess.Popen, Path]:
    wcase, wlib = _wsl_path(case), _wsl_path(DEFAULT_LIBRARY.parent)
    log = case / f"log.pimpleFoam_{label}"
    command = ("source /opt/openfoam10/etc/bashrc; "
        f"export LD_LIBRARY_PATH={wlib}:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/dummy:$LD_LIBRARY_PATH; "
        f"cd '{wcase}'; pimpleFoam > '{log.name}' 2>&1")
    return subprocess.Popen(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command]), log


def _finish(process: subprocess.Popen, log: Path, timeout_s: float) -> float:
    if process.wait(timeout=timeout_s) != 0:
        raise RuntimeError(f"solver failed: {process.returncode}")
    text = log.read_text(encoding="utf-8", errors="replace")
    if "End" not in text or any(token in text for token in ("FOAM FATAL", "Floating point exception", "nan", "inf")):
        raise RuntimeError("solver did not complete finitely")
    cfl = [float(item) for item in re.findall(r"Courant Number mean:\s+[^\s]+\s+max:\s+([-+0-9.eE]+)", text)]
    if not cfl or max(cfl) >= MAX_CFL:
        raise RuntimeError("CFL hard gate failed")
    return max(cfl)


def _bridge(process: subprocess.Popen, case: Path, *, manifest, spec, motion, start_s: float, steps: int, end_s: float, alpha_at, timeout_s: float) -> None:
    initial = _motion(manifest, spec, motion, alpha=alpha_at(0), step=0, time_s=start_s)
    materialize_legacy_motion_bridge(record=initial.to_dict(), case=case, exchange_dir="coupling", seed=True, seed_time_s=start_s, bridge_step_offset=1, seed_step_offset=0)
    dt = (end_s - start_s) / steps
    for index in range(1, steps + 1):
        ack = case / "coupling" / "consumed" / f"motion_consumed_{index - 1}.json"
        deadline = time.monotonic() + timeout_s
        while not ack.is_file() and time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"solver stopped before bridge {index}")
            time.sleep(.01)
        if not ack.is_file():
            raise TimeoutError(f"bridge acknowledgement {index} timed out")
        target = start_s + index * dt
        record = _motion(manifest, spec, motion, alpha=alpha_at(index), step=index - 1, time_s=target)
        materialize_legacy_motion_bridge(record=record.to_dict(), case=case, exchange_dir="coupling", bridge_step_offset=1)


def _copy_exact_state(source: Path, target: Path, spec_id: int) -> None:
    target.mkdir(parents=True)
    shutil.copytree(source / "constant", target / "constant")
    shutil.copytree(source / "system", target / "system")
    shutil.copytree(source / f"{MIGRATION_END_S:.12g}", target / f"{MIGRATION_END_S:.12g}")
    (target / "0").mkdir(); shutil.copy2(source / "0" / "motionScale", target / "0" / "motionScale")
    for relative in ("coupling/motion", "coupling/load", "coupling/consumed", "postProcessing"):
        (target / relative).mkdir(parents=True, exist_ok=True)
    _replace(target / "system" / "controlDict", {"startFrom": "startTime", "startTime": f"{MIGRATION_END_S:.12g}", "endTime": f"{HOLD_END_S:.12g}", "writeInterval": str(HOLD_STEPS)})
    text = (target / "constant" / "dynamicMeshDict").read_text(encoding="utf-8")
    text = re.sub(r"^\s*startTime\s+[^;]+;", f"        startTime       {MIGRATION_END_S:.12g};", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*sliceId\s+[^;]+;", f"        sliceId         {spec_id};", text, flags=re.MULTILINE)
    (target / "constant" / "dynamicMeshDict").write_text(text, encoding="utf-8")


def run_exact_migration_and_hold(root: Path, equilibrium_audit: Path) -> dict[str, Any]:
    """Run all three exact-geometry migration/hold CFD diagnostics."""
    if root.exists():
        raise FileExistsError(root)
    manifest = _read_manifest(); config = _config(manifest); motion = _equilibrium_motion(equilibrium_audit)
    root.mkdir(parents=True); slices: list[dict[str, Any]] = []
    for spec in manifest.slices:
        migration = root / "migration" / f"slice_{spec.slice_id:04d}"
        _copy_hot_start(source=SOURCE, target=migration, manifest=manifest, config=config, spec=spec)
        # OpenFOAM's inherited time index does not guarantee an endpoint
        # write for a 180-step interval.  Twenty divides this trajectory and
        # materializes the exact alpha=1 endpoint at 0.5 s.
        _replace(migration / "system" / "controlDict", {"startFrom": "startTime", "startTime": f"{HOT_START_S:.12g}", "endTime": f"{MIGRATION_END_S:.12g}", "writeInterval": str(MIGRATION_WRITE_INTERVAL)})
        process, migration_log = _start_solver(migration, "stage4f_b5_exact_migration")
        try:
            _bridge(process, migration, manifest=manifest, spec=spec, motion=motion, start_s=HOT_START_S, steps=MIGRATION_STEPS, end_s=MIGRATION_END_S, alpha_at=lambda index: index / MIGRATION_STEPS, timeout_s=config.timeout_s)
            migration_cfl = _finish(process, migration_log, config.timeout_s)
        finally:
            if process.poll() is None: process.terminate(); process.wait(timeout=10)
        if not (migration / f"{MIGRATION_END_S:.12g}" / "polyMesh" / "points").is_file():
            raise RuntimeError("exact migration did not write a complete endpoint geometry")
        hold = root / "hold" / f"slice_{spec.slice_id:04d}"; _copy_exact_state(migration, hold, spec.slice_id)
        process, hold_log = _start_solver(hold, "stage4f_b5_exact_hold")
        try:
            _bridge(process, hold, manifest=manifest, spec=spec, motion=motion, start_s=MIGRATION_END_S, steps=HOLD_STEPS, end_s=HOLD_END_S, alpha_at=lambda _: 1.0, timeout_s=config.timeout_s)
            hold_cfl = _finish(process, hold_log, config.timeout_s)
        finally:
            if process.poll() is None: process.terminate(); process.wait(timeout=10)
        force_path = hold / "postProcessing" / "cylinderForces" / f"{MIGRATION_END_S:.12g}" / "forces.dat"
        stat = force_window_statistics(force_path, start_s=1.25, end_s=HOLD_END_S)
        if abs(stat["mean_unit_span_force_N"][0] / 500.0) > MAX_ABS_CD:
            raise RuntimeError("held force-scale hard gate failed")
        slices.append({"slice_id": spec.slice_id, "migration_case": str(migration), "hold_case": str(hold), "migration_log": str(migration_log), "hold_log": str(hold_log), "migration_max_cfl": migration_cfl, "hold_max_cfl": hold_cfl, "exact_geometry_points_sha256": sha256_file(migration / f"{MIGRATION_END_S:.12g}" / "polyMesh" / "points"), "held_force": stat})
    result = {"status": "passed", "equilibrium_audit": str(equilibrium_audit), "equilibrium_sha256": sha256_file(equilibrium_audit), "exact_alpha": 1.0, "migration_end_s": MIGRATION_END_S, "hold_end_s": HOLD_END_S, "slices": slices, "max_cfl": max(max(row["migration_max_cfl"], row["hold_max_cfl"]) for row in slices), "formal_fsi_started": False}
    atomic_write_json(root / "exact_geometry_hold_audit.json", result)
    return result


def run_terminal_hold(root: Path, exact_hold_audit: Path, equilibrium_audit: Path) -> dict[str, Any]:
    """Extend a verified exact-geometry hold to a written 1.5 s endpoint."""
    if root.exists():
        raise FileExistsError(root)
    source_audit = json.loads(exact_hold_audit.read_text(encoding="utf-8"))
    if source_audit.get("status") != "passed" or source_audit.get("exact_alpha") != 1.0:
        raise ValueError("terminal hold requires a passed exact-geometry source")
    manifest = _read_manifest(); config = _config(manifest); motion = _equilibrium_motion(equilibrium_audit)
    root.mkdir(parents=True); slices = []
    for item in sorted(source_audit["slices"], key=lambda row: row["slice_id"]):
        spec = manifest.slice(int(item["slice_id"])); source = Path(item["hold_case"])
        if not (source / f"{TERMINAL_START_S:.12g}" / "polyMesh" / "points").is_file():
            raise RuntimeError(f"missing terminal source state for slice {spec.slice_id}")
        target = root / f"slice_{spec.slice_id:04d}"; target.mkdir(parents=True)
        shutil.copytree(source / "constant", target / "constant")
        shutil.copytree(source / "system", target / "system")
        shutil.copytree(source / f"{TERMINAL_START_S:.12g}", target / f"{TERMINAL_START_S:.12g}")
        (target / "0").mkdir(); shutil.copy2(source / "0" / "motionScale", target / "0" / "motionScale")
        for relative in ("coupling/motion", "coupling/load", "coupling/consumed", "postProcessing"):
            (target / relative).mkdir(parents=True, exist_ok=True)
        _replace(target / "system" / "controlDict", {"startFrom": "startTime", "startTime": f"{TERMINAL_START_S:.12g}", "endTime": f"{HOLD_END_S:.12g}", "writeInterval": str(TERMINAL_WRITE_INTERVAL)})
        text = (target / "constant" / "dynamicMeshDict").read_text(encoding="utf-8")
        text = re.sub(r"^\s*startTime\s+[^;]+;", f"        startTime       {TERMINAL_START_S:.12g};", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*sliceId\s+[^;]+;", f"        sliceId         {spec.slice_id};", text, flags=re.MULTILINE)
        (target / "constant" / "dynamicMeshDict").write_text(text, encoding="utf-8")
        process, log = _start_solver(target, "stage4f_b5_terminal_hold")
        try:
            _bridge(process, target, manifest=manifest, spec=spec, motion=motion, start_s=TERMINAL_START_S, steps=TERMINAL_STEPS, end_s=HOLD_END_S, alpha_at=lambda _: 1.0, timeout_s=config.timeout_s)
            max_cfl = _finish(process, log, config.timeout_s)
        finally:
            if process.poll() is None: process.terminate(); process.wait(timeout=10)
        endpoint = target / f"{HOLD_END_S:.12g}"
        if not (endpoint / "polyMesh" / "points").is_file():
            raise RuntimeError("terminal hold did not write complete endpoint geometry")
        force = force_window_statistics(target / "postProcessing" / "cylinderForces" / f"{TERMINAL_START_S:.12g}" / "forces.dat", start_s=1.25, end_s=HOLD_END_S)
        if abs(force["mean_unit_span_force_N"][0] / 500.0) > MAX_ABS_CD:
            raise RuntimeError("terminal force-scale hard gate failed")
        slices.append({"slice_id": spec.slice_id, "case": str(target), "log": str(log), "max_cfl": max_cfl,
            "endpoint_geometry_points_sha256": sha256_file(endpoint / "polyMesh" / "points"), "terminal_force": force})
    value = {"status": "passed", "source_exact_hold_audit": str(exact_hold_audit), "source_exact_hold_sha256": sha256_file(exact_hold_audit),
             "equilibrium_audit": str(equilibrium_audit), "equilibrium_sha256": sha256_file(equilibrium_audit), "start_time_s": TERMINAL_START_S,
             "end_time_s": HOLD_END_S, "exact_alpha": 1.0, "slices": slices, "max_cfl": max(row["max_cfl"] for row in slices), "formal_fsi_started": False}
    atomic_write_json(root / "terminal_hold_audit.json", value)
    return value
