"""Run one bounded fixed-vs-real-preCICE-zero CFD bridge.

This is a test-only experiment.  It copies the immutable formal slice case
and PRECURSOR_STATE_V1 into a new runtime, then runs (1) pimpleFoam without
the adapter and dynamicMeshDict, and (2) the same case through the real
preCICE adapter with a prescribed all-zero displacement participant.
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
FORMAL_CASE = ROOT / "runtime" / "formal_three_slice_implicit_0p05s_owned_mesh_history_v1_run_001" / "cases" / "slice_0000"
PRECURSOR = ROOT / "results" / "fixed_cylinder_precursor_initialization_contract_v1_run_002" / "PRECURSOR_STATE_V1"
MANIFEST = PRECURSOR / "manifest.json"
RUNTIME = ROOT / "runtime" / "cfd_current_fixed_zero_bridge_v1_run_002"
RESULTS = ROOT / "results" / "cfd_current_fixed_zero_bridge_v1_run_002"
PYDEPS = ROOT / "runtime" / "284_precice_single_slice_smoke_real_v1" / "python_deps"
PROTOTYPE_ROOT_WSL = "/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1"
ADAPTER_BUILD = "adapter_owner_diagnostic_build_001"
ADAPTER_LIB_WSL = f"{PROTOTYPE_ROOT_WSL}/{ADAPTER_BUILD}/lib"
ENV_SCRIPT_WSL = "/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/tools/of10_owned_atomic_mesh_history_restore_prototype_v1/prototype_env.sh"
DT = 0.005
START = 0.100
END = 0.150
FORCE_ABS_TOL_N = 1.0e-6
FORCE_REL_TOL = 1.0e-8
MESH_ABS_TOL_M = 1.0e-12


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wsl(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def copy_common_case(case: Path) -> None:
    shutil.copytree(FORMAL_CASE / "constant", case / "constant")
    shutil.copytree(FORMAL_CASE / "system", case / "system")
    (case / "0.1").mkdir(parents=True)
    expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["field_hashes"]
    for field in ("U", "p", "phi"):
        source = PRECURSOR / field
        if sha256(source) != expected[field]:
            raise RuntimeError(f"PRECURSOR_STATE_V1 hash mismatch for {field}")
        shutil.copy2(source, case / "0.1" / field)
    for field in ("pointDisplacement", "cellDisplacement"):
        shutil.copy2(FORMAL_CASE / "0.1" / field, case / "0.1" / field)


def force_control() -> str:
    return """FoamFile { format ascii; class dictionary; object controlDict; }
application pimpleFoam;
startFrom startTime; startTime 0.1; stopAt endTime; endTime 0.15; deltaT 0.005;
writeControl timeStep; writeInterval 1; purgeWrite 0; writeFormat ascii; writePrecision 12; writeCompression off; timeFormat general; timePrecision 12; runTimeModifiable false;
functions { cylinderForces { type forces; libs (\"libforces.so\"); writeControl timeStep; writeInterval 1; log yes; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); } }
"""


def adapter_control() -> str:
    return f"""FoamFile {{ format ascii; class dictionary; object controlDict; }}
application pimpleFoam;
libs (\"libpreciceAdapterFunctionObject.so\");
startFrom startTime; startTime 0.1; stopAt endTime; endTime 0.15; deltaT 0.005;
writeControl timeStep; writeInterval 1; purgeWrite 0; writeFormat ascii; writePrecision 12; writeCompression off; timeFormat general; timePrecision 12; runTimeModifiable false;
functions {{ preCICE_Adapter {{ type preciceAdapterFunctionObject; }} cylinderForces {{ type forces; libs (\"libforces.so\"); writeControl timeStep; writeInterval 1; log yes; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); }} }}
"""


def precice_dict() -> str:
    return """FoamFile { format ascii; class dictionary; object preciceDict; }
preciceConfig \"precice-config.xml\"; participant Fluid_0000; modules (FSI); FSI { solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1000; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement pointDisplacement; nameCellDisplacement cellDisplacement; nameForce Force; } interfaces { Interface1 { mesh Fluid-Mesh; patches (cylinder); locations faceCenters; readData (Displacement); writeData (Force); } }
"""


def precice_xml(exchange: Path) -> str:
    return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<precice-configuration xmlns:data=\"http://www.precice.org/schemas/data\" xmlns:m2n=\"http://www.precice.org/schemas/m2n\" xmlns:coupling-scheme=\"http://www.precice.org/schemas/coupling-scheme\" xmlns:mapping=\"http://www.precice.org/schemas/mapping\">
<data:vector name=\"Displacement\" waveform-degree=\"0\"/><data:vector name=\"Force\" waveform-degree=\"0\"/>
<mesh name=\"Structure-Mesh\" dimensions=\"2\"><use-data name=\"Displacement\"/><use-data name=\"Force\"/></mesh><mesh name=\"Fluid-Mesh\" dimensions=\"2\"><use-data name=\"Displacement\"/><use-data name=\"Force\"/></mesh>
<m2n:sockets acceptor=\"Structure_0000\" connector=\"Fluid_0000\" exchange-directory=\"{wsl(exchange)}\"/>
<participant name=\"Structure_0000\"><provide-mesh name=\"Structure-Mesh\"/><write-data name=\"Displacement\" mesh=\"Structure-Mesh\"/><read-data name=\"Force\" mesh=\"Structure-Mesh\"/></participant>
<participant name=\"Fluid_0000\"><receive-mesh name=\"Structure-Mesh\" from=\"Structure_0000\"/><provide-mesh name=\"Fluid-Mesh\"/><mapping:nearest-neighbor direction=\"read\" from=\"Structure-Mesh\" to=\"Fluid-Mesh\" constraint=\"consistent\"/><mapping:nearest-neighbor direction=\"write\" from=\"Fluid-Mesh\" to=\"Structure-Mesh\" constraint=\"conservative\"/><write-data name=\"Force\" mesh=\"Fluid-Mesh\"/><read-data name=\"Displacement\" mesh=\"Fluid-Mesh\"/></participant>
<coupling-scheme:parallel-explicit><participants first=\"Structure_0000\" second=\"Fluid_0000\"/><max-time value=\"0.05\"/><time-window-size value=\"0.005\"/><exchange data=\"Displacement\" mesh=\"Structure-Mesh\" from=\"Structure_0000\" to=\"Fluid_0000\" initialize=\"yes\" substeps=\"false\"/><exchange data=\"Force\" mesh=\"Structure-Mesh\" from=\"Fluid_0000\" to=\"Structure_0000\" substeps=\"false\"/></coupling-scheme:parallel-explicit>
</precice-configuration>
"""


def participant_code() -> str:
    return r'''from __future__ import annotations
import json, math, sys
from pathlib import Path
import precice

config, evidence = map(Path, sys.argv[1:3])
vertices=[(0.5*math.cos(2*math.pi*i/40),0.5*math.sin(2*math.pi*i/40)) for i in range(40)]
participant=precice.Participant("Structure_0000",str(config),0,1)
mesh=participant.set_mesh_vertices("Structure-Mesh",vertices)
initial_requested=participant.requires_initial_data()
zero=[[0.0,0.0] for _ in vertices]
if initial_requested:
    participant.write_data("Structure-Mesh","Displacement",mesh,zero)
participant.initialize()
rows=[]; step=0
try:
    while participant.is_coupling_ongoing():
        participant.write_data("Structure-Mesh","Displacement",mesh,zero)
        participant.advance(0.005)
        force=participant.read_data("Structure-Mesh","Force",mesh,0.0)
        force=force.tolist() if hasattr(force,"tolist") else force
        rows.append({"step":step+1,"physical_time_s":0.1+(step+1)*0.005,"input_displacement_max_m":0.0,"force_sum_N":[sum(float(row[d]) for row in force) for d in range(2)],"force_max_abs_N":max(abs(float(v)) for row in force for v in row) if force else 0.0})
        step += 1
finally:
    participant.finalize()
evidence.write_text(json.dumps({"initial_data_requested":initial_requested,"steps":step,"rows":rows,"all_zero_input":True},indent=2)+"\n",encoding="utf-8")
'''


def prepare() -> tuple[Path, Path]:
    if RESULTS.exists():
        raise RuntimeError("refusing to overwrite existing bridge results")
    if not MANIFEST.is_file():
        raise RuntimeError("PRECURSOR_STATE_V1 manifest missing")
    fixed = RUNTIME / "fixed_case"
    zero = RUNTIME / "zero_precice_case"
    if not RUNTIME.exists():
        RUNTIME.mkdir(parents=True)
        copy_common_case(fixed)
        copy_common_case(zero)
    elif not fixed.is_dir() or not zero.is_dir():
        raise RuntimeError("existing bridge runtime is not a recognized preparation")
    # Fixed reference: no dynamic mesh and no adapter.  The point/cell fields
    # are retained as copied input evidence but are not consumed by pimpleFoam.
    (fixed / "constant" / "dynamicMeshDict").unlink(missing_ok=True)
    write(fixed / "system" / "controlDict", force_control())
    # Real preCICE zero-motion path.
    write(zero / "system" / "controlDict", adapter_control())
    write(zero / "system" / "preciceDict", precice_dict())
    exchange = RUNTIME / "precice-sockets"
    exchange.mkdir(parents=True)
    write(zero / "precice-config.xml", precice_xml(exchange))
    write(RUNTIME / "zero_participant.py", participant_code())
    manifest = {
        "schema_version": "cfd-current-fixed-zero-bridge-v1",
        "status": "prepared",
        "source_formal_case": str(FORMAL_CASE),
        "precursor_manifest": str(MANIFEST),
        "source_time_s": START,
        "target_time_s": END,
        "dt_s": DT,
        "steps": 10,
        "force_abs_tol_N": FORCE_ABS_TOL_N,
        "force_rel_tol": FORCE_REL_TOL,
        "mesh_abs_tol_m": MESH_ABS_TOL_M,
        "adapter_library_wsl": ADAPTER_LIB_WSL,
        "openfoam_prefix_wsl": PROTOTYPE_ROOT_WSL + "/owner_diagnostic_abi_build_001/openfoam10",
        "mesh_sha256": {name: sha256(FORMAL_CASE / "constant" / "polyMesh" / name) for name in ("points", "faces", "owner", "neighbour", "boundary")},
    }
    write(RUNTIME / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    return fixed, zero


def launch_fixed(fixed: Path) -> int:
    script = "\n".join((
        "set -o pipefail",
        f"source '{ENV_SCRIPT_WSL}' '{PROTOTYPE_ROOT_WSL}'",
        f"cd '{wsl(fixed)}'",
        f"pimpleFoam > '{wsl(RUNTIME / 'fixed.stdout')}' 2> '{wsl(RUNTIME / 'fixed.stderr')}'",
    )) + "\n"
    write(RUNTIME / "launch_fixed.sh", script)
    done = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(RUNTIME / "launch_fixed.sh")], text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=300)
    write(RUNTIME / "launch_fixed_launcher.stdout", done.stdout)
    write(RUNTIME / "launch_fixed_launcher.stderr", done.stderr)
    return done.returncode


def launch_zero(zero: Path) -> int:
    script = "\n".join((
        "set -o pipefail",
        f"source '{ENV_SCRIPT_WSL}' '{PROTOTYPE_ROOT_WSL}'",
        f"export LD_LIBRARY_PATH='{ADAPTER_LIB_WSL}':$LD_LIBRARY_PATH",
        f"export PYTHONPATH='{wsl(PYDEPS)}'",
        f"export PRECICE_ADAPTER_BUILD_SHA256='c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17'",
        f"cd '{wsl(zero)}'",
        f"python3 '{wsl(RUNTIME / 'zero_participant.py')}' '{wsl(zero / 'precice-config.xml')}' '{wsl(RUNTIME / 'zero_participant_evidence.json')}' > '{wsl(RUNTIME / 'zero_structure.stdout')}' 2> '{wsl(RUNTIME / 'zero_structure.stderr')}' & structure_pid=$!",
        f"pimpleFoam > '{wsl(RUNTIME / 'zero_fluid.stdout')}' 2> '{wsl(RUNTIME / 'zero_fluid.stderr')}' & fluid_pid=$!",
        "wait $structure_pid; structure_rc=$?",
        "wait $fluid_pid; fluid_rc=$?",
        f"printf 'structure=%s\\nfluid=%s\\n' \"$structure_rc\" \"$fluid_rc\" > '{wsl(RUNTIME / 'zero_returns.txt')}'",
        "[ $structure_rc -eq 0 ] && [ $fluid_rc -eq 0 ]",
    )) + "\n"
    write(RUNTIME / "launch_zero.sh", script)
    done = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(RUNTIME / "launch_zero.sh")], text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=300)
    write(RUNTIME / "launch_zero_launcher.stdout", done.stdout)
    write(RUNTIME / "launch_zero_launcher.stderr", done.stderr)
    return done.returncode


def parse_force_file(path: Path) -> list[dict[str, float]]:
    if not path.is_file():
        return []
    rows=[]
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line=line.strip()
        if not line or line.startswith("#"):
            continue
        values=re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", line)
        if len(values) < 13:
            continue
        try:
            p=[float(values[i]) for i in (1,2,3)]
            v=[float(values[i]) for i in (4,5,6)]
            rows.append({"time_s":float(values[0]),"pressure_x_N":p[0],"pressure_y_N":p[1],"pressure_z_N":p[2],"viscous_x_N":v[0],"viscous_y_N":v[1],"viscous_z_N":v[2],"total_x_N":p[0]+v[0],"total_y_N":p[1]+v[1],"total_z_N":p[2]+v[2]})
        except ValueError:
            pass
    return rows


def collect() -> dict:
    def force_path(case: Path) -> Path:
        candidates=list((case / "postProcessing" / "cylinderForces").glob("*/forces.dat"))
        return sorted(candidates)[-1] if candidates else case / "postProcessing" / "cylinderForces" / "missing" / "forces.dat"
    fixed_force=parse_force_file(force_path(RUNTIME / "fixed_case"))
    zero_force=parse_force_file(force_path(RUNTIME / "zero_precice_case"))
    compare=[]
    for index,(a,b) in enumerate(zip(fixed_force,zero_force),1):
        diffs={k:b[k]-a[k] for k in ("pressure_x_N","pressure_y_N","viscous_x_N","viscous_y_N","total_x_N","total_y_N")}
        tol={k:max(FORCE_ABS_TOL_N,FORCE_REL_TOL*max(abs(a[k]),abs(b[k]),1.0)) for k in diffs}
        compare.append({"step":index,"fixed":a,"zero":b,"diff":diffs,"tolerance":tol,"pass":all(abs(diffs[k])<=tol[k] for k in diffs)})
    participant=json.loads((RUNTIME/"zero_participant_evidence.json").read_text(encoding="utf-8")) if (RUNTIME/"zero_participant_evidence.json").is_file() else {}
    fluid_log=(RUNTIME/"zero_fluid.stdout").read_text(encoding="utf-8",errors="replace") if (RUNTIME/"zero_fluid.stdout").is_file() else ""
    fixed_log=(RUNTIME/"fixed.stdout").read_text(encoding="utf-8",errors="replace") if (RUNTIME/"fixed.stdout").is_file() else ""
    co_re=re.compile(r"Courant Number mean: ([0-9.eE+-]+) max: ([0-9.eE+-]+)")
    def cos(text): return [{"mean":float(m.group(1)),"max":float(m.group(2))} for m in co_re.finditer(text)]
    return {"fixed_force_file":str(force_path(RUNTIME/"fixed_case")),"zero_force_file":str(force_path(RUNTIME/"zero_precice_case")),"fixed_force":fixed_force,"zero_force":zero_force,"comparison":compare,"participant":participant,"fixed_courant":cos(fixed_log),"zero_courant":cos(fluid_log),"fixed_end":fixed_log.rstrip().endswith("End"),"zero_end":fluid_log.rstrip().endswith("End"),"all_force_rows_pass":len(compare)==10 and all(row["pass"] for row in compare),"zero_steps":participant.get("steps")}


def main() -> int:
    fixed,zero=prepare()
    fixed_rc=launch_fixed(fixed)
    zero_rc=launch_zero(zero) if fixed_rc==0 else 125
    result=collect()
    result.update({"fixed_return_code":fixed_rc,"zero_return_code":zero_rc,"status":"PASS" if fixed_rc==0 and zero_rc==0 and result["all_force_rows_pass"] and result["zero_steps"]==10 else "FAIL_CLOSED"})
    RESULTS.mkdir(parents=True,exist_ok=True)
    write(RESULTS / "bridge_result.json",json.dumps(result,indent=2)+"\n")
    print(json.dumps({"status":result["status"],"fixed_return_code":fixed_rc,"zero_return_code":zero_rc,"zero_steps":result.get("zero_steps"),"force_rows":len(result["comparison"])}))
    return 0 if result["status"]=="PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
