"""Run a bounded one-case OpenFOAM latest-time restart smoke.

This is deliberately an independent prescribed-motion smoke, not the claimed
two-slice CFD--ANCF loop. It verifies that ``0/motionScale`` remains usable
when the solver restarts from an existing nonzero time directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path


def atomic_text(path: Path, text: str) -> None:
    import tempfile
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    case = args.case.resolve()
    coupling = case / "coupling"
    atomic_text(coupling / "motion.csv", "schema_version,step,coupling_iteration,time_s,slice_id,s_ref_m,x_m,y_m,z_m,vx_mps,vy_mps,vz_mps,ax_mps2,ay_mps2,az_mps2\n0.1.0,1,0,0.0025,0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0\n")
    atomic_text(coupling / "motion_ready", json.dumps({"kind": "motion_ready", "payload": "motion.csv", "step": 1, "time_s": 0.0025}) + "\n")
    wcase, wlib = wsl_path(case), wsl_path(args.library.resolve())
    command = (
        "source /opt/openfoam10/etc/bashrc; "
        f"export LD_LIBRARY_PATH=/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/dummy:/opt/openfoam10/platforms/linux64GccDPInt32Opt/lib/openmpi-system:{wlib}; "
        f"cd '{wcase}'; /opt/openfoam10/platforms/linux64GccDPInt32Opt/bin/pimpleFoam > log.pimpleFoam_restart_v2 2>&1"
    )
    process = subprocess.Popen(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command])
    consumed = coupling / "consumed" / "motion_consumed_1.json"
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline and not consumed.is_file():
        if process.poll() is not None:
            break
        time.sleep(0.05)
    if consumed.is_file():
        atomic_text(coupling / "motion.csv", "schema_version,step,coupling_iteration,time_s,slice_id,s_ref_m,x_m,y_m,z_m,vx_mps,vy_mps,vz_mps,ax_mps2,ay_mps2,az_mps2\n0.1.0,2,0,0.005,0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0\n")
        atomic_text(coupling / "motion_ready", json.dumps({"kind": "motion_ready", "payload": "motion.csv", "step": 2, "time_s": 0.005}) + "\n")
    try:
        return_code = process.wait(timeout=90.0)
    except subprocess.TimeoutExpired:
        process.terminate()
        return_code = process.wait(timeout=15.0)
    log = case / "log.pimpleFoam_restart_v2"
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    cfl = [float(value) for value in re.findall(r"Courant Number mean:\s+[^\s]+\s+max:\s+([-+0-9.eE]+)", text)]
    output = {
        "schema_version": "stage4b_v2_static_motionScale_restart_smoke",
        "status": "passed" if return_code == 0 and (case / "0.005").is_dir() else "blocked",
        "openfoam_version": "OpenFOAM-10",
        "case": str(case), "library": str(args.library.resolve()),
        "start_from": "latestTime", "restart_time_s": 0.0025, "end_time_s": 0.005,
        "return_code": return_code, "process_count_max": 1,
        "motionScale_path": str(case / "0" / "motionScale"),
        "motionScale_sha256": __import__("hashlib").sha256((case / "0" / "motionScale").read_bytes()).hexdigest() if (case / "0" / "motionScale").is_file() else None,
        "time_directory": str(case / "0.005"),
        "max_cfl": max(cfl) if cfl else None,
        "log": str(log),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0 if output["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
