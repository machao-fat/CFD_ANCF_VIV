"""Bounded fixed-cylinder cold-start characterization; never starts FSI."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime" / "generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001" / "cases" / "slice_0000"
RUNTIME = ROOT / "runtime" / "fixed_cylinder_precursor_characterization_v1_run_001"
DT = 0.005
END = 0.1
CONTROL = '''FoamFile { format ascii; class dictionary; object controlDict; }
application pimpleFoam;
startFrom startTime; startTime 0; stopAt endTime; endTime 0.1; deltaT 0.005;
writeControl timeStep; writeInterval 1; purgeWrite 0; writeFormat ascii; writePrecision 12; writeCompression off; timeFormat general; timePrecision 12; runTimeModifiable false;
functions { cylinderForces { type forces; libs ("libforces.so"); writeControl timeStep; writeInterval 1; log yes; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); } }
'''
VECTOR = re.compile(r"\(([^()]+)\)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wsl(path: Path) -> str:
    return f"/mnt/{path.drive.rstrip(':').lower()}/" + path.as_posix().split(":/", 1)[1]


def parse(path: Path) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        vectors = VECTOR.findall(line)
        if len(vectors) < 2:
            raise RuntimeError(f"unrecognised force row: {line}")
        pressure = [float(value) for value in vectors[0].split()]
        viscous = [float(value) for value in vectors[1].split()]
        result.append({"time_s": float(line.split()[0]), "pressure_N": pressure,
                       "viscous_N": viscous,
                       "total_N": [pressure[i] + viscous[i] for i in range(3)]})
    return result


def main() -> None:
    if RUNTIME.exists():
        raise RuntimeError(f"refusing to overwrite runtime {RUNTIME}")
    if not SOURCE.is_dir():
        raise RuntimeError(f"missing immutable source {SOURCE}")
    case = RUNTIME / "case"
    for name in ("0", "constant", "system"):
        shutil.copytree(SOURCE / name, case / name)
    # This is deliberately a static fixed-cylinder characterization branch.
    (case / "constant" / "dynamicMeshDict").unlink()
    (case / "system" / "controlDict").write_text(CONTROL, encoding="utf-8", newline="\n")
    command = "source /opt/openfoam10/etc/bashrc; cd '%s'; pimpleFoam > characterization.stdout 2>&1" % wsl(case)
    completed = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command],
                               text=True, encoding="utf-8", errors="replace", capture_output=True,
                               timeout=180, check=False)
    (case / "characterization.launch.stdout").write_text(completed.stdout or "", encoding="utf-8", newline="\n")
    (case / "characterization.launch.stderr").write_text(completed.stderr or "", encoding="utf-8", newline="\n")
    force_path = case / "postProcessing" / "cylinderForces" / "0" / "forces.dat"
    result = {
        "schema_version": "fixed-cylinder-startup-characterization-v1",
        "kind": "uncoupled_fixed_cylinder_diagnostic_not_precursor_state",
        "dt_s": DT, "duration_s": END, "expected_steps": 20,
        "preCICE": "not_started", "structure_worker": "not_started",
        "source_case": str(SOURCE), "source_mesh_sha256": sha256(SOURCE / "constant" / "polyMesh" / "points"),
        "return_code": completed.returncode, "force_file": str(force_path),
        "forces": parse(force_path) if force_path.is_file() else [],
        "raw_solver_log": str(case / "characterization.stdout"),
    }
    (RUNTIME / "characterization.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
