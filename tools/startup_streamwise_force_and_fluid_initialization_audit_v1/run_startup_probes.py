"""Create and execute bounded, uncoupled startup-force diagnostic probes.

Both probes inherit the failed corrected coupled case's mesh, U/p initial
fields, material properties, numerical schemes and fvSolution.  They differ
only in whether the dynamic-mesh dictionary is present.  The script never
opens preCICE, never launches the structure worker, and hard-limits each
solver execution to four 0.005 s time steps.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / "runtime" / "generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001" / "cases" / "slice_0000"
# run_001 stopped before either probe result was written because the Windows
# launcher decoded WSL's mixed console bytes with the host ANSI code page.
# Preserve it as a failed launcher artifact; use a fresh runtime after fixing
# that diagnostic-only wrapper defect.
RUNTIME = PROJECT / "runtime" / "startup_streamwise_force_and_fluid_initialization_audit_v1_run_002"
DT = 0.005
END_TIME = 0.02

CONTROL = r'''FoamFile
{
    format ascii;
    class dictionary;
    object controlDict;
}
application pimpleFoam;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime 0.02;
deltaT 0.005;
writeControl timeStep;
writeInterval 1;
purgeWrite 0;
writeFormat ascii;
writePrecision 12;
writeCompression off;
timeFormat general;
timePrecision 12;
runTimeModifiable false;
functions
{
    cylinderForces
    {
        type forces;
        libs ("libforces.so");
        writeControl timeStep;
        writeInterval 1;
        log yes;
        patches (cylinder);
        rho rhoInf;
        rhoInf 1000;
        CofR (0 0 0);
    }
}
'''

VECTOR = re.compile(r"\(([^()]+)\)")


def wsl_path(path: Path) -> str:
    drive = path.drive.rstrip(":").lower()
    return f"/mnt/{drive}/" + path.as_posix().split(":/", 1)[1]


def make_case(name: str, dynamic: bool) -> Path:
    case = RUNTIME / "cases" / name
    if case.exists():
        raise RuntimeError(f"refusing to overwrite existing probe case: {case}")
    case.mkdir(parents=True)
    for item in ("0", "constant", "system"):
        shutil.copytree(SOURCE / item, case / item)
    (case / "system" / "controlDict").write_text(CONTROL, encoding="utf-8", newline="\n")
    if not dynamic:
        # This is a newly generated diagnostic case only.  The source runtime
        # remains immutable; removing this copied dictionary selects static mesh.
        (case / "constant" / "dynamicMeshDict").unlink()
    return case


def parse_forces(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        nums = VECTOR.findall(line)
        if len(nums) < 4:
            raise RuntimeError(f"unrecognised forces row: {line}")
        def vec(text: str) -> list[float]:
            result = [float(value) for value in text.split()]
            if len(result) != 3:
                raise RuntimeError(f"not a three-vector: {text}")
            return result
        pressure, viscous = vec(nums[0]), vec(nums[1])
        rows.append({
            "time_s": float(line.split()[0]),
            "pressure_N": pressure,
            "viscous_N": viscous,
            "total_N": [pressure[i] + viscous[i] for i in range(3)],
        })
    return rows


def run_case(case: Path) -> dict[str, object]:
    command = (
        "source /opt/openfoam10/etc/bashrc; "
        f"cd '{wsl_path(case)}'; "
        "pimpleFoam > probe.stdout 2>&1"
    )
    completed = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
        check=False,
    )
    (case / "probe.launch.stdout").write_text(completed.stdout or "", encoding="utf-8", newline="\n")
    (case / "probe.launch.stderr").write_text(completed.stderr or "", encoding="utf-8", newline="\n")
    force = case / "postProcessing" / "cylinderForces" / "0" / "forces.dat"
    return {
        "case": str(case),
        "return_code": completed.returncode,
        "force_file": str(force),
        "force_rows": parse_forces(force) if force.is_file() else [],
        "solver_log": str(case / "probe.stdout"),
    }


def main() -> None:
    if not SOURCE.is_dir():
        raise RuntimeError(f"missing immutable source case: {SOURCE}")
    if RUNTIME.exists():
        raise RuntimeError(f"refusing to overwrite runtime: {RUNTIME}")
    fixed = make_case("fixed_cylinder", dynamic=False)
    dynamic = make_case("zero_motion_dynamic_mesh", dynamic=True)
    result = {
        "schema_version": "startup-force-probes-v1",
        "source_case": str(SOURCE),
        "dt_s": DT,
        "end_time_s": END_TIME,
        "number_of_steps": 4,
        "preCICE": "not_started",
        "structure_worker": "not_started",
        "fixed_cylinder": run_case(fixed),
        "zero_motion_dynamic_mesh": run_case(dynamic),
    }
    (RUNTIME / "startup_probe_results.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
