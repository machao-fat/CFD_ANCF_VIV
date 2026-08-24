#!/usr/bin/env python3
"""Run at most two independent OpenFOAM 10 slice smoke processes.

The smoke uses the existing stage-three materialized 0.1.0 motion view only;
it is intentionally not a Draft-1 CFD--ANCF closed-loop run.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import time
from pathlib import Path


FIELDS = (
    "schema_version", "step", "coupling_iteration", "time_s", "slice_id", "s_ref_m",
    "x_m", "y_m", "z_m", "vx_mps", "vy_mps", "vz_mps", "ax_mps2", "ay_mps2", "az_mps2",
)
FLOAT_RE = re.compile(r"max:\s*([-+0-9.eE]+)")


def atomic_write(path: Path, text: str) -> None:
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        temporary_path.write_text(text, encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def publish_motion(case: Path, *, slice_id: int, s_ref_m: float, step: int, time_s: float) -> None:
    stream = __import__("io").StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerow({
        "schema_version": "0.1.0", "step": step, "coupling_iteration": 0,
        "time_s": time_s, "slice_id": slice_id, "s_ref_m": s_ref_m,
        "x_m": 0.0, "y_m": 0.0, "z_m": 0.0,
        "vx_mps": 0.0, "vy_mps": 0.0, "vz_mps": 0.0,
        "ax_mps2": 0.0, "ay_mps2": 0.0, "az_mps2": 0.0,
    })
    coupling = case / "coupling"
    atomic_write(coupling / "motion.csv", stream.getvalue())
    atomic_write(coupling / "motion_ready", json.dumps({
        "kind": "motion_ready", "payload": "motion.csv", "step": step, "time_s": time_s,
    }, sort_keys=True) + "\n")


def wsl_path(path: Path, project: Path) -> str:
    del project
    absolute = str(path.resolve()).replace("\\", "/")
    drive, rest = absolute.split(":", 1)
    return f"/mnt/{drive.lower()}{rest}"


def main() -> int:
    project = Path(__file__).resolve().parents[2]
    base = project / "results" / "05_multi_slice_orchestration_tests" / "openfoam_smoke"
    cases = [base / "case_slice_0000_retry3", base / "case_slice_0001_retry3"]
    specs = [(0, 0.0), (1, 0.5)]
    if not all(case.is_dir() for case in cases):
        raise SystemExit("retry smoke cases must be generated before this command")
    for case, (slice_id, s_ref_m) in zip(cases, specs):
        publish_motion(case, slice_id=slice_id, s_ref_m=s_ref_m, step=0, time_s=0.0)
    wsl_lib = "/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/results/05_multi_slice_orchestration_tests/openfoam_smoke/lib"
    processes: list[subprocess.Popen[bytes]] = []
    commands: list[str] = []
    for case in cases:
        wsl_case = wsl_path(case, project)
        command = (
            "source /opt/openfoam10/etc/bashrc; "
            f"export LD_LIBRARY_PATH=/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/dummy:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/openmpi-system:{wsl_lib}; "
            f"cd {wsl_case}; /opt/openfoam10/platforms/linux64GccDPInt32Opt/bin/pimpleFoam > log.pimpleFoam_stage4 2>&1"
        )
        commands.append(command)
        processes.append(subprocess.Popen(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command]))
    deadline = time.monotonic() + 60.0
    consumed = [case / "coupling" / "consumed" / "motion_consumed_0.json" for case in cases]
    while time.monotonic() < deadline and not all(path.is_file() for path in consumed):
        if any(process.poll() is not None and process.returncode != 0 for process in processes):
            break
        time.sleep(0.05)
    if not all(path.is_file() for path in consumed):
        for process in processes:
            if process.poll() is None:
                process.terminate()
        raise SystemExit("OpenFOAM did not consume both step-0 motion snapshots")
    for case, (slice_id, s_ref_m) in zip(cases, specs):
        publish_motion(case, slice_id=slice_id, s_ref_m=s_ref_m, step=1, time_s=0.0025)
    return_codes = []
    for process in processes:
        try:
            return_codes.append(process.wait(timeout=120))
        except subprocess.TimeoutExpired:
            process.terminate()
            return_codes.append(process.wait(timeout=15))
    max_cfl = 0.0
    force_files: list[str] = []
    consumed_files: list[str] = []
    checkpoint_fields: dict[str, list[str]] = {}
    for case in cases:
        log_text = (case / "log.pimpleFoam_stage4").read_text(encoding="utf-8", errors="replace")
        values = [float(match.group(1)) for match in FLOAT_RE.finditer(log_text)]
        if values:
            max_cfl = max(max_cfl, max(values))
        force = case / "postProcessing" / "cylinderForces" / "0" / "forces.dat"
        force_files.append(str(force))
        consumed_files.append(str(case / "coupling" / "consumed" / "motion_consumed_0.json"))
        time_dir = case / "0.0025"
        checkpoint_fields[str(case)] = [
            relative for relative in ("U", "p", "phi", "Uf", "meshPhi", "polyMesh/points", "motionScale", "uniform/time")
            if (time_dir / relative).is_file()
        ]
    required_checkpoint_fields = ["U", "p", "phi", "Uf", "meshPhi", "polyMesh/points", "motionScale", "uniform/time"]
    checkpoint_complete = all(set(required_checkpoint_fields).issubset(set(fields)) for fields in checkpoint_fields.values())
    process_ok = all(code == 0 for code in return_codes) and max_cfl <= 0.5
    summary = {
        "schema_version": "stage4_real_openfoam_smoke_v1",
        "status": "completed" if process_ok and checkpoint_complete else ("blocked_checkpoint_fields" if process_ok else "failed"),
        "checkpoint_complete": checkpoint_complete,
        "checkpoint_required_fields": required_checkpoint_fields,
        "block_reason": None if checkpoint_complete else "motionScale was not written by the real OpenFOAM time directory; no file was fabricated",
        "openfoam_version": "OpenFOAM-10",
        "case_paths": [str(case) for case in cases],
        "start_time_s": 0.0, "physical_end_time_s": 0.0025, "steps": 1,
        "max_cfl": max_cfl, "process_count_max": 2,
        "commands": commands, "return_codes": return_codes,
        "force_files": force_files, "motion_consumed_files": consumed_files,
        "checkpoint_fields": checkpoint_fields,
        "ready_files": [str(case / "coupling" / "motion_ready") for case in cases],
    }
    output = base / "real_smoke_summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
