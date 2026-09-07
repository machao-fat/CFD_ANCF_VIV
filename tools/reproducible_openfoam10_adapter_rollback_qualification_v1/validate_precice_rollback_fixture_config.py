"""Validate the rollback fixture XML with two real preCICE participants.

This performs initialization only: it never launches OpenFOAM and never
advances a physical time window.  Both participants are needed because the
socket transport and mesh/data declarations are validated at initialization.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "reproducible_openfoam10_adapter_rollback_qualification_v1"))
from run_real_precice_rollback_qualification import PYDEPS, wsl, write, xml

RUN = "precice_rollback_fixture_configuration_fix_and_qualification_v1_config_validation_001"
RUNTIME = ROOT / "runtime" / RUN
RESULTS = ROOT / "results" / RUN


def participant_source() -> str:
    return r'''import json, math, sys
from pathlib import Path
import precice

role, config, evidence = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
vertices=[(0.5*math.cos(2*math.pi*i/40),0.5*math.sin(2*math.pi*i/40)) for i in range(40)]
participant=precice.Participant(role,str(config),0,1)
mesh_name = "Structure-Mesh" if role == "Structure" else "Fluid-Mesh"
mesh = participant.set_mesh_vertices(mesh_name,vertices)
participant.initialize()
with evidence.open("w",encoding="utf-8",newline="\n") as stream:
    json.dump({"participant":role,"initialized":True,"mesh":mesh_name,"vertices":len(mesh)},stream,indent=2)
    stream.write("\n")
participant.finalize()
'''


def main() -> int:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to overwrite configuration-validation evidence")
    RUNTIME.mkdir(parents=True)
    exchange = RUNTIME / "precice-sockets"
    exchange.mkdir()
    config = RUNTIME / "precice-config.xml"
    write(config, xml(exchange))
    script = RUNTIME / "participant.py"
    write(script, participant_source())
    launch = "\n".join((
        "set -o pipefail",
        f"export PYTHONPATH='{wsl(PYDEPS)}'",
        f"python3 '{wsl(script)}' Structure '{wsl(config)}' '{wsl(RUNTIME / 'structure.json')}' > '{wsl(RUNTIME / 'structure.stdout')}' 2> '{wsl(RUNTIME / 'structure.stderr')}' & structure_pid=$!",
        f"python3 '{wsl(script)}' Fluid '{wsl(config)}' '{wsl(RUNTIME / 'fluid.json')}' > '{wsl(RUNTIME / 'fluid.stdout')}' 2> '{wsl(RUNTIME / 'fluid.stderr')}' & fluid_pid=$!",
        "wait $structure_pid; structure_rc=$?",
        "wait $fluid_pid; fluid_rc=$?",
        f"printf 'structure=%s\\nfluid=%s\\n' \"$structure_rc\" \"$fluid_rc\" > '{wsl(RUNTIME / 'returns.txt')}'",
        "[ $structure_rc -eq 0 ] && [ $fluid_rc -eq 0 ]",
    )) + "\n"
    write(RUNTIME / "launch.sh", launch)
    completed = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(RUNTIME / "launch.sh")],
        text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=90,
    )
    write(RUNTIME / "launcher.stdout", completed.stdout)
    write(RUNTIME / "launcher.stderr", completed.stderr)
    output = {
        "return_code": completed.returncode,
        "xml_force_substeps_false": 'data="Force" mesh="Structure-Mesh" from="Fluid" to="Structure" substeps="false"' in config.read_text(encoding="utf-8"),
        "xml_displacement_substeps_false": 'data="Displacement" mesh="Structure-Mesh" from="Structure" to="Fluid" substeps="false"' in config.read_text(encoding="utf-8"),
        "structure": json.loads((RUNTIME / "structure.json").read_text(encoding="utf-8")) if (RUNTIME / "structure.json").is_file() else None,
        "fluid": json.loads((RUNTIME / "fluid.json").read_text(encoding="utf-8")) if (RUNTIME / "fluid.json").is_file() else None,
    }
    RESULTS.mkdir(parents=True)
    write(RESULTS / "config_validation.json", json.dumps(output,indent=2)+"\n")
    print(json.dumps(output,sort_keys=True))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
