#!/usr/bin/env python3
"""Bounded, uncoupled mesh-motion sensitivity proof; not a VIV calculation."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.slice_independence_audit_v1.audit import parse_forces, sensitivity_evidence_status, sha256

SOURCE = ROOT / "cases" / "openfoam" / "single_slice_ancf_fsi"
RUNTIME = ROOT / "runtime" / "slice_force_sensitivity_controlled_v6"
RESULTS = ROOT / "results" / "slice_force_sensitivity_controlled_v6"
DT = 0.005
END_TIME = 0.1
OFFSETS_M = (0.0, 0.01, -0.01)

CONTROL = '''FoamFile { format ascii; class dictionary; object controlDict; }
application pimpleFoam;
startFrom startTime; startTime 0; stopAt endTime; endTime 0.1; deltaT 0.005;
writeControl timeStep; writeInterval 1; purgeWrite 0; writeFormat ascii; writePrecision 12; writeCompression off; timeFormat general; timePrecision 12; runTimeModifiable false;
functions { cylinderForces { type forces; libs ("libforces.so"); writeControl timeStep; writeInterval 1; log yes; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); } }
'''
DYNAMIC = '''FoamFile { format ascii; class dictionary; object dynamicMeshDict; }
mover
{
    type motionSolver;
    libs ("libfvMeshMovers.so" "libfvMotionSolvers.so");
    motionSolver displacementLaplacian;
    diffusivity uniform;
}
'''


def wsl(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def point_field(offset_y_m: float) -> str:
    return f'''FoamFile {{ format ascii; class pointVectorField; location "0"; object pointDisplacement; }}
dimensions [0 1 0 0 0 0 0]; internalField uniform (0 0 0);
boundaryField {{ inlet {{ type fixedValue; value uniform (0 0 0); }} outlet {{ type fixedValue; value uniform (0 0 0); }} lower {{ type symmetryPlane; }} upper {{ type symmetryPlane; }} cylinder {{ type fixedValue; value uniform (0 {offset_y_m:.17g} 0); }} front {{ type empty; }} back {{ type empty; }} }}
'''


def ensure_cell_displacement_final(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "cellDisplacementFinal" not in text:
        text = text.replace("\n}\n\nPIMPLE\n{", "\n    cellDisplacementFinal\n    {\n        $cellMotionUx;\n        relTol 0;\n    }\n}\n\nPIMPLE\n{")
        path.write_text(text, encoding="utf-8")


def prepare() -> list[Path]:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to reuse controlled-sensitivity evidence path")
    if not SOURCE.is_dir():
        raise RuntimeError(f"missing source case: {SOURCE}")
    cases: list[Path] = []
    for index, offset in enumerate(OFFSETS_M):
        case = RUNTIME / "cases" / f"offset_{index:04d}"
        for name in ("0", "constant", "system"):
            shutil.copytree(SOURCE / name, case / name)
        (case / "system" / "controlDict").write_text(CONTROL, encoding="utf-8")
        ensure_cell_displacement_final(case / "system" / "fvSolution")
        (case / "constant" / "dynamicMeshDict").write_text(DYNAMIC, encoding="utf-8")
        (case / "0" / "pointDisplacement").write_text(point_field(offset), encoding="utf-8")
        cases.append(case)
    (RUNTIME / "logs").mkdir(parents=True, exist_ok=True)
    (RUNTIME / "contract.json").write_text(json.dumps({"kind": "controlled_prescribed_motion_sensitivity", "coupled": False,
        "dt_s": DT, "duration_s": END_TIME, "offsets_y_m": list(OFFSETS_M), "source": str(SOURCE),
        "purpose": "prove geometry -> field -> force sensitivity after pointDisplacement repair"}, indent=2) + "\n", encoding="utf-8")
    return cases


def run(cases: list[Path]) -> None:
    # Do not use `set -e`: OpenFOAM's environment script can leave a
    # non-zero status in a non-interactive shell although it sets all paths.
    # We collect and evaluate every solver return code explicitly below.
    commands = ["set -o pipefail", "source /opt/openfoam10/etc/bashrc"]
    for index, case in enumerate(cases):
        stdout = wsl(RUNTIME / "logs" / f"offset_{index:04d}.stdout")
        stderr = wsl(RUNTIME / "logs" / f"offset_{index:04d}.stderr")
        commands.append(f"(cd '{wsl(case)}' && pimpleFoam > '{stdout}' 2> '{stderr}') & p{index}=$!")
    commands += ["wait $p0; r0=$?", "wait $p1; r1=$?", "wait $p2; r2=$?", f"printf 'offset_0000_return=%s\\noffset_0001_return=%s\\noffset_0002_return=%s\\n' $r0 $r1 $r2 > '{wsl(RUNTIME / 'logs' / 'returns.txt')}'", "test $r0 -eq 0 -a $r1 -eq 0 -a $r2 -eq 0"]
    launch = RUNTIME / "launch.sh"
    # Bash under WSL treats a CR suffix as part of shell tokens and redirection
    # paths; preserve LF-only evidence scripts.
    with launch.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(commands) + "\n")
    completed = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(launch)], cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace", timeout=180)
    (RUNTIME / "logs" / "launcher.stdout").write_text(completed.stdout, encoding="utf-8")
    (RUNTIME / "logs" / "launcher.stderr").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(f"controlled sensitivity run failed ({completed.returncode})")


def audit(cases: list[Path]) -> dict[str, object]:
    time = "0.1"; fields = {}
    for field in ("U", "p"):
        paths = [case / time / field for case in cases]
        if not all(path.is_file() for path in paths):
            raise RuntimeError(f"missing {field} evidence")
        hashes = [sha256(path) for path in paths]
        fields[field] = {"sha256": hashes, "distinct": len(set(hashes)) == len(hashes)}
    mesh_paths = [case / time / "polyMesh" / "points" for case in cases]
    if not all(path.is_file() for path in mesh_paths):
        raise RuntimeError("actual final mesh point evidence is missing")
    mesh_hashes = [sha256(path) for path in mesh_paths]
    force_paths = [case / "postProcessing" / "cylinderForces" / "0" / "forces.dat" for case in cases]
    if not all(path.is_file() for path in force_paths):
        raise RuntimeError("force evidence is missing")
    forces = [parse_forces(path) for path in force_paths]
    key = round(END_TIME, 9)
    fy = [item[key]["total_N"][1] for item in forces]
    max_delta = max(fy) - min(fy)
    status = sensitivity_evidence_status(geometry_distinct=len(set(mesh_hashes)) == len(mesh_hashes), u_distinct=bool(fields["U"]["distinct"]),
        p_distinct=bool(fields["p"]["distinct"]), fy_difference_N=max_delta)
    result = {"CONTROLLED_PRESCRIBED_MOTION_SENSITIVITY": status.upper(), "kind": "uncoupled; not VIV", "time_s": END_TIME,
        "offsets_y_m": list(OFFSETS_M), "actual_mesh_points_sha256": mesh_hashes, "fields": fields,
        "Fy_at_0p1_s_N": fy, "max_pairwise_Fy_difference_N": max_delta, "force_paths": [str(path) for path in force_paths]}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "controlled_sensitivity_gate.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    cases = prepare(); run(cases); result = audit(cases)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["CONTROLLED_PRESCRIBED_MOTION_SENSITIVITY"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
