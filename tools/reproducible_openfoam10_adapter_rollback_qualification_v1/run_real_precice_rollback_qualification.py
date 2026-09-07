"""One-window, prescribed-motion preCICE rollback qualification.

This is deliberately not an ANCF participant and has no structural solver.
It drives one OpenFOAM slice from the frozen precursor state through one
parallel-implicit window solely to exercise the adapter's real checkpoint
callbacks and moving-mesh restoration.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.moving_mesh_openfoam10_case_contract_v1 import ensure_solver_entries, preflight

RUN = "precice_rollback_fixture_configuration_fix_and_qualification_v1_run_001"
RUNTIME, RESULTS = ROOT / "runtime" / RUN, ROOT / "results" / RUN
PRECURSOR = ROOT / "results" / "fixed_cylinder_precursor_initialization_contract_v1_run_002" / "PRECURSOR_STATE_V1"
SOURCE = ROOT / "runtime" / "generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001" / "cases" / "slice_0000"
PYDEPS = ROOT / "runtime" / "284_precice_single_slice_smoke_real_v1" / "python_deps"
DIAG_LIBRARY_WSL = "/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_003/lib"
DIAG_LIBRARY = Path(r"\\wsl$\Ubuntu-22.04") / DIAG_LIBRARY_WSL.lstrip("/").replace("/", "\\")
DIAG_LIBRARY_FILE = DIAG_LIBRARY / "libpreciceAdapterFunctionObject.so"
DT = 0.005
TRIAL_Y_M = (0.002, -0.002)  # frozen: distinct, nonzero, and 0.004 D peak separation


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def wsl(path: Path) -> str:
    if os.name != "nt":
        return str(path.resolve())
    value = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def xml(exchange_dir: Path) -> str:
    return "\n".join((
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">',
        '<data:vector name="Displacement" waveform-degree="0"/><data:vector name="Force" waveform-degree="0"/>',
        '<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>',
        f'<m2n:sockets acceptor="Structure" connector="Fluid" exchange-directory="{wsl(exchange_dir)}"/>',
        '<participant name="Structure"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>',
        '<participant name="Fluid"><receive-mesh name="Structure-Mesh" from="Structure"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>',
        # The bounds are deliberately permissive for a restoration test; this
        # is not a physical coupling-convergence contract. min=2 guarantees a
        # genuine rollback/retry with two distinct prescribed inputs.
        '<coupling-scheme:parallel-implicit><participants first="Structure" second="Fluid"/><time-window-size value="0.005"/><max-time value="0.005"/><min-iterations value="2"/><max-iterations value="8"/><absolute-or-relative-convergence-measure data="Displacement" mesh="Structure-Mesh" abs-limit="1" rel-limit="1"/><absolute-or-relative-convergence-measure data="Force" mesh="Structure-Mesh" abs-limit="10000000" rel-limit="1"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure" to="Fluid" substeps="false"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid" to="Structure" substeps="false"/></coupling-scheme:parallel-implicit>',
        '</precice-configuration>',
    ))


def participant_code() -> str:
    return r'''from __future__ import annotations
import json, math, os, sys
from pathlib import Path
import precice

config, evidence = map(Path, sys.argv[1:3])
vertices=[(0.5*math.cos(2*math.pi*i/40),0.5*math.sin(2*math.pi*i/40)) for i in range(40)]
participant=precice.Participant("Structure",str(config),0,1)
mesh=participant.set_mesh_vertices("Structure-Mesh",vertices)
participant.initialize()
rows=[]; iteration=0; rollback_count=0
while participant.is_coupling_ongoing():
    if participant.requires_writing_checkpoint():
        rows.append({"event":"STRUCTURE_CHECKPOINT_WRITE","iteration":iteration,"physical_time_s":0.0})
    iteration += 1
    y=(0.002,-0.002)[min(iteration-1,1)]
    participant.write_data("Structure-Mesh","Displacement",mesh,[[0.0,y] for _ in vertices])
    participant.advance(0.005)
    force=participant.read_data("Structure-Mesh","Force",mesh,0.0)
    force_sum=[sum(float(row[d]) for row in force) for d in range(2)]
    rows.append({"event":"TRIAL_ADVANCED","iteration":iteration,"trial_displacement_y_m":y,"force_sum_N":force_sum,"physical_time_s":0.005})
    if participant.requires_reading_checkpoint():
        rollback_count += 1
        rows.append({"event":"STRUCTURE_CHECKPOINT_READ","iteration":iteration,"rollback_count":rollback_count,"physical_time_restored_s":0.0})
        continue
    rows.append({"event":"FINAL_COMMIT","iteration":iteration,"physical_time_s":0.005})
    break
participant.finalize()
with evidence.open("w",encoding="utf-8",newline="\n") as stream:
    json.dump({"iterations":iteration,"rollbacks":rollback_count,"rows":rows},stream,indent=2)
    stream.write("\n")
'''


def prepare() -> Path:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to overwrite immutable qualification runtime")
    if not DIAG_LIBRARY_FILE.is_file():
        raise RuntimeError("diagnostic adapter library is absent")
    manifest = json.loads((PRECURSOR / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "pass":
        raise RuntimeError("precursor state is not accepted")
    case = RUNTIME / "case"
    shutil.copytree(SOURCE / "constant", case / "constant")
    shutil.copytree(SOURCE / "system", case / "system")
    (case / "0.1").mkdir(parents=True)
    for field, expected in manifest["field_hashes"].items():
        origin = PRECURSOR / field
        if sha256(origin) != expected:
            raise RuntimeError(f"precursor source hash mismatch: {field}")
        shutil.copy2(origin, case / "0.1" / field)
    for field in ("pointDisplacement", "cellDisplacement"):
        text = (SOURCE / "0" / field).read_text(encoding="utf-8").replace('location "0"', 'location "0.1"')
        write(case / "0.1" / field, text)
    ensure_solver_entries(case / "system" / "fvSolution")
    write(case / "constant" / "dynamicMeshDict", 'FoamFile { format ascii; class dictionary; object dynamicMeshDict; }\nmover { type motionSolver; libs ("libfvMeshMovers.so" "libfvMotionSolvers.so"); motionSolver displacementLaplacian; diffusivity uniform; }\n')
    write(case / "system" / "controlDict", 'FoamFile { format ascii; class dictionary; object controlDict; }\napplication pimpleFoam;\nlibs ("libpreciceAdapterFunctionObject.so");\nstartFrom startTime; startTime 0.1; stopAt endTime; endTime 0.105; deltaT 0.005;\nwriteControl timeStep; writeInterval 1; writeFormat ascii; writePrecision 12; writeCompression off; runTimeModifiable false;\nfunctions { preCICE_Adapter { type preciceAdapterFunctionObject; } cylinderForces { type forces; libs ("libforces.so"); writeControl timeStep; writeInterval 1; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); } }\n')
    RUNTIME.mkdir(parents=True, exist_ok=True)
    exchange = RUNTIME / "precice-sockets"; exchange.mkdir()
    config = case / "precice-config.xml"; write(config, xml(exchange))
    write(case / "system" / "preciceDict", 'FoamFile { format ascii; class dictionary; object preciceDict; }\npreciceConfig "precice-config.xml"; participant Fluid; modules (FSI); FSI { solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1000; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement pointDisplacement; nameCellDisplacement cellDisplacement; nameForce Force; } interfaces { Interface1 { mesh Fluid-Mesh; patches (cylinder); locations faceCenters; readData (Displacement); writeData (Force); } }\n')
    contract = {"schema_version": "reproducible-openfoam10-adapter-rollback-qualification-v1", "run_id": RUN, "dt_s": DT, "physical_windows": 1, "fluid_subcycling": "FORBIDDEN", "source_openfoam_time_s": 0.1, "target_openfoam_time_s": 0.105, "trial_displacement_y_m": list(TRIAL_Y_M), "adapter_library_wsl": DIAG_LIBRARY_WSL, "adapter_library_sha256": sha256(DIAG_LIBRARY_FILE), "precursor_manifest_sha256": sha256(PRECURSOR / "manifest.json"), "convergence_test_only": True}
    write(RUNTIME / "contract.json", json.dumps(contract, indent=2) + "\n")
    state = preflight(case, "0.1")
    if state["MOVING_MESH_CASE_PREFLIGHT"] != "PASS":
        raise RuntimeError("moving-mesh preflight failed")
    return case


def run(case: Path) -> int:
    write(RUNTIME / "participant.py", participant_code())
    log = RUNTIME / "adapter_rollback_trace.jsonl"
    script = "\n".join((
        "set -o pipefail",
        "export ZSH_NAME=",
        "source /opt/openfoam10/etc/bashrc",
        f"export LD_LIBRARY_PATH='{DIAG_LIBRARY_WSL}':$LD_LIBRARY_PATH",
        f"export PYTHONPATH='{wsl(PYDEPS)}'",
        f"export PRECICE_ADAPTER_ROLLBACK_DIAGNOSTICS_PATH='{wsl(log)}'",
        f"export PRECICE_ADAPTER_BUILD_SHA256='{sha256(DIAG_LIBRARY_FILE)}'",
        f"python3 '{wsl(RUNTIME / 'participant.py')}' '{wsl(case / 'precice-config.xml')}' '{wsl(RUNTIME / 'participant_evidence.json')}' > '{wsl(RUNTIME / 'structure.stdout')}' 2> '{wsl(RUNTIME / 'structure.stderr')}' & structure_pid=$!",
        f"(cd '{wsl(case)}' && pimpleFoam > '{wsl(RUNTIME / 'fluid.stdout')}' 2> '{wsl(RUNTIME / 'fluid.stderr')}') & fluid_pid=$!",
        "wait $structure_pid; structure_rc=$?",
        "wait $fluid_pid; fluid_rc=$?",
        f"printf 'structure=%s\\nfluid=%s\\n' \"$structure_rc\" \"$fluid_rc\" > '{wsl(RUNTIME / 'returns.txt')}'",
        "[ $structure_rc -eq 0 ] && [ $fluid_rc -eq 0 ]",
    )) + "\n"
    write(RUNTIME / "launch.sh", script)
    command = (["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(RUNTIME / "launch.sh")]
               if os.name == "nt" else ["bash", wsl(RUNTIME / "launch.sh")])
    done = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=300)
    write(RUNTIME / "launcher.stdout", done.stdout); write(RUNTIME / "launcher.stderr", done.stderr)
    return done.returncode


def main() -> int:
    case = prepare()
    code = run(case)
    trace = [json.loads(line) for line in (RUNTIME / "adapter_rollback_trace.jsonl").read_text(encoding="utf-8").splitlines()] if (RUNTIME / "adapter_rollback_trace.jsonl").is_file() else []
    participant = json.loads((RUNTIME / "participant_evidence.json").read_text(encoding="utf-8")) if (RUNTIME / "participant_evidence.json").is_file() else {}
    output = {"return_code": code, "adapter_trace": trace, "participant": participant, "runtime": str(RUNTIME), "diagnostic_library_sha256": sha256(DIAG_LIBRARY_FILE) if DIAG_LIBRARY_FILE.is_file() else None}
    RESULTS.mkdir(parents=True, exist_ok=True)
    write(RESULTS / "real_rollback_raw.json", json.dumps(output, indent=2) + "\n")
    print(json.dumps({"return_code": code, "trace_events": [x.get("event") for x in trace], "participant": participant.get("iterations")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
