"""Exercise preCICE 3.4.1 start/end sampling without OpenFOAM or ANCF.

The test has one implicit window.  Structure writes the frozen sequence
``initial=+A, +A, -A, -A``.  The fluid role records both its window-start and
post-advance end reads, proving that a rollback does not retain a prior trial.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN_ID = os.environ.get("PRECICE_TIME_LAYER_RUN_ID", "precice_time_layer_contract_v1_regression_001")
RUN = ROOT / "runtime" / RUN_ID
RESULTS = ROOT / "results" / RUN_ID
DT = 0.005
A = 0.002


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def wsl(path: Path) -> str:
    return str(path.resolve())


def xml(exchange: Path) -> str:
    return "\n".join((
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">',
        '<data:vector name="Displacement" waveform-degree="0"/><data:vector name="Force" waveform-degree="0"/>',
        '<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>',
        f'<m2n:sockets acceptor="Structure" connector="Fluid" exchange-directory="{wsl(exchange)}"/>',
        '<participant name="Structure"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>',
        '<participant name="Fluid"><receive-mesh name="Structure-Mesh" from="Structure"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>',
        '<coupling-scheme:parallel-implicit><participants first="Structure" second="Fluid"/><time-window-size value="0.005"/><max-time value="0.005"/><min-iterations value="2"/><max-iterations value="8"/><absolute-or-relative-convergence-measure data="Displacement" mesh="Structure-Mesh" abs-limit="0.0001" rel-limit="0.01"/><absolute-or-relative-convergence-measure data="Force" mesh="Structure-Mesh" abs-limit="10000000" rel-limit="1"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure" to="Fluid" initialize="yes" substeps="false"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid" to="Structure" substeps="false"/></coupling-scheme:parallel-implicit>',
        '</precice-configuration>',
    ))


def role_code() -> str:
    return r'''from __future__ import annotations
import json, sys
from pathlib import Path
import precice

role, config_s, output_s = sys.argv[1:4]
config, output = Path(config_s), Path(output_s)
dt=0.005; a=0.002; vertices=[(0.0,0.0)]
p=precice.Participant(role, str(config), 0, 1)
mesh=p.set_mesh_vertices("Structure-Mesh" if role == "Structure" else "Fluid-Mesh", vertices)
mesh_name="Structure-Mesh" if role == "Structure" else "Fluid-Mesh"
rows=[]
if role == "Structure" and p.requires_initial_data():
    p.write_data(mesh_name,"Displacement",mesh,[[0.0,a]])
    rows.append({"event":"WRITE_INITIAL","value":a})
p.initialize()
iteration=0
if role == "Fluid":
    values=p.read_data(mesh_name,"Displacement",mesh,0.0)
    rows.append({"event":"READ_START","relative_read_time":0.0,"value":float(values[0][1])})
    trial=float(values[0][1])
while p.is_coupling_ongoing():
    if p.requires_writing_checkpoint(): rows.append({"event":"CHECKPOINT_WRITE","iteration":iteration})
    if role == "Structure":
        value=(a,-a,-a)[min(iteration,2)]
        p.write_data(mesh_name,"Displacement",mesh,[[0.0,value]])
        rows.append({"event":"WRITE_TRIAL","iteration":iteration+1,"value":value})
    else:
        rows.append({"event":"TRIAL_INPUT","iteration":iteration+1,"value":trial})
        p.write_data(mesh_name,"Force",mesh,[[0.0,0.0]])
    iteration += 1
    p.advance(dt)
    if role == "Structure":
        force=p.read_data(mesh_name,"Force",mesh,0.0)
        rows.append({"event":"READ_FORCE","iteration":iteration,"value":float(force[0][1])})
    elif p.is_coupling_ongoing():
        values=p.read_data(mesh_name,"Displacement",mesh,dt)
        trial=float(values[0][1])
        rows.append({"event":"READ_END","iteration":iteration,"relative_read_time":dt,"value":trial})
    if p.requires_reading_checkpoint(): rows.append({"event":"CHECKPOINT_READ","iteration":iteration})
p.finalize()
output.write_text(json.dumps({"role":role,"iterations":iteration,"rows":rows},indent=2)+"\n",encoding="utf-8")
'''


def main() -> int:
    if RUN.exists() or RESULTS.exists():
        raise RuntimeError("refusing to overwrite immutable time-layer regression")
    RUN.mkdir(parents=True); exchange=RUN / "exchange"; exchange.mkdir()
    config=RUN / "precice-config.xml"; write(config, xml(exchange)); code=RUN / "role.py"; write(code, role_code())
    commands=[]
    for role in ("Structure", "Fluid"):
        commands.append(f"python3 '{wsl(code)}' {role} '{wsl(config)}' '{wsl(RUN / (role.lower()+'.json'))}' > '{wsl(RUN / (role.lower()+'.stdout'))}' 2> '{wsl(RUN / (role.lower()+'.stderr'))}' & {role.lower()}_pid=$!")
    commands += ["wait $structure_pid; structure_rc=$?", "wait $fluid_pid; fluid_rc=$?", "exit $((structure_rc || fluid_rc))"]
    launcher=RUN / "launch.sh"; write(launcher, "set -e\n"+"\n".join(commands)+"\n")
    done=subprocess.run(["bash",str(launcher)],text=True,capture_output=True,timeout=120)
    write(RUN / "launcher.stdout",done.stdout); write(RUN / "launcher.stderr",done.stderr)
    payload={"return_code":done.returncode}
    for role in ("structure","fluid"):
        path=RUN / f"{role}.json"
        payload[role]=json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    RESULTS.mkdir(parents=True); write(RESULTS / "time_layer_raw.json",json.dumps(payload,indent=2)+"\n")
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
