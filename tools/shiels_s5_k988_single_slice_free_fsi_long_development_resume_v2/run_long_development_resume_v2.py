"""Prepare and launch one authorized resume after a hosting interruption.

The run continues only the last jointly accepted 6.370 s state with the same
owner-diagnostic OF10 ABI, real preCICE adapter, and existing SDOFRunner. It
refuses any existing execution evidence: no retry or automatic extension is
possible from this launcher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime" / "shiels_s5_k988_single_slice_free_fsi_long_development_resume_v2_run_001"
RESULTS = ROOT / "results" / "shiels_s5_k988_single_slice_free_fsi_long_development_resume_v2_run_001"
PARENT_RUNTIME = ROOT / "runtime" / "shiels_s5_k988_single_slice_free_fsi_long_development_v1_run_001"
PARENT_CASE = PARENT_RUNTIME / "precice_displacementLaplacian"
PYDEPS = ROOT / "runtime" / "284_precice_single_slice_smoke_real_v1" / "python_deps"
PARTICIPANT = ROOT / "tools" / "shiels_s5_k988_single_slice_free_fsi_long_development_resume_v2" / "sdof_precice_continuation_participant.py"

PROTOTYPE_ROOT_WSL = "/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1"
ABI_ROOT_WSL = PROTOTYPE_ROOT_WSL + "/owner_diagnostic_abi_build_001"
OF_PREFIX_WSL = ABI_ROOT_WSL + "/openfoam10"
ADAPTER_LIB_WSL = PROTOTYPE_ROOT_WSL + "/adapter_owner_diagnostic_build_001/lib"
ENV_SCRIPT_WSL = "/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/tools/of10_owned_atomic_mesh_history_restore_prototype_v1/prototype_env.sh"
ADAPTER_SHA256 = "c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17"

START = 6.37
DT = 0.005
STEPS = 18757
END = START + STEPS * DT
VERTEX_COUNT = 40
MASS_KG = 2500.0
STIFFNESS_NPM = 4940.0
NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"

# Frozen before launch.  These are safety/implementation gates, not a VIV
# amplitude or long-time stability criterion.
MAX_COURANT = 0.5
MAX_GLOBAL_CONTINUITY = 1.0e-8
MOTION_ABS_TOL_M = 1.0e-9
COUPLING_DISPLACEMENT_ABS_LIMIT_M = 1.0e-8
MAX_ABS_DISPLACEMENT_M = 0.05
MAX_ABS_VELOCITY_MPS = 0.5
MAX_ABS_FORCE_Y_N = 2.0e4
MIN_ITERATIONS = 2
MAX_ITERATIONS = 8


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wsl(path: Path) -> str:
    raw = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + raw[0].lower() + raw[2:]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def write_json(path: Path, value: Any) -> None:
    write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def block(text: str, name: str) -> str:
    found = re.search(rf"\b{re.escape(name)}\s*\{{", text)
    if found is None:
        raise RuntimeError(f"missing OpenFOAM boundary block: {name}")
    start = text.find("{", found.start())
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    raise RuntimeError(f"unterminated OpenFOAM boundary block: {name}")


def source_hashes() -> dict[str, str]:
    names = ("U", "p", "phi", "Uf", "meshPhi", "pointDisplacement", "cellDisplacement", "polyMesh/points", "uniform/time")
    return {name: sha256(PARENT_CASE / "6.37" / name) for name in names}


def parse_force_at(path: Path, time_s: float) -> dict[str, float]:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        values = [float(value) for value in re.findall(NUMBER, line)]
        if len(values) >= 7 and abs(values[0] - time_s) <= 1.0e-12:
            return {
                "time_s": values[0],
                "pressure_x_N": values[1], "pressure_y_N": values[2],
                "viscous_x_N": values[4], "viscous_y_N": values[5],
                "total_x_N": values[1] + values[4], "total_y_N": values[2] + values[5],
            }
    raise RuntimeError(f"no cylinderForces row at t={time_s:g} in {path}")


def require_parent() -> dict[str, Any]:
    required = (
        "6.37/U", "6.37/p", "6.37/phi", "6.37/Uf", "6.37/meshPhi", "6.37/pointDisplacement",
        "6.37/cellDisplacement", "6.37/polyMesh/points", "6.37/uniform/time", "constant/polyMesh/points",
        "system/fvSchemes", "system/fvSolution", "constant/dynamicMeshDict",
    )
    missing = [item for item in required if not (PARENT_CASE / item).is_file()]
    if missing:
        raise RuntimeError(f"accepted 6.370 CFD continuation state is incomplete: {missing}")
    if (PARENT_RUNTIME / "returns.txt").exists():
        raise RuntimeError("interrupted parent unexpectedly has terminal execution evidence")
    events = [json.loads(line) for line in (PARENT_RUNTIME / "structure" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    commits = [row for row in events if row.get("event") == "window_commit"]
    if len(commits) != 243:
        raise RuntimeError("interrupted parent does not contain exactly 243 accepted commits")
    final = commits[-1]
    if abs(float(final["physical_time_s"]) - START) > 1.0e-12:
        raise RuntimeError("parent final commit is not at the authorized 6.370 s boundary")
    state = final["accepted_state"]
    if int(state["step"]) != 1253 or abs(float(state["local_time_s"]) - 6.265) > 1.0e-12:
        raise RuntimeError("parent SDOF state has an unexpected 6.370 s step/time identity")
    force_file = PARENT_CASE / "postProcessing" / "cylinderForces" / "5.155" / "forces.dat"
    initial_force = parse_force_at(force_file, START)
    if abs(initial_force["total_y_N"] - float(final["force_y_total_N"])) > 1.0e-8:
        raise RuntimeError("parent final CFD force and accepted structure force differ")
    equilibrium_a = (initial_force["total_y_N"] - STIFFNESS_NPM * float(state["y_m"])) / MASS_KG
    if abs(equilibrium_a - float(state["a_mps2"])) > 1.0e-15:
        raise RuntimeError("parent accepted acceleration is not force-consistent")
    interface_y = float(final["final_input_y_m"])
    residual = abs(interface_y - float(state["y_m"]))
    if residual > COUPLING_DISPLACEMENT_ABS_LIMIT_M:
        raise RuntimeError("parent final interface/structure residual exceeds frozen convergence tolerance")
    return {
        "final_commit": final,
        "force": initial_force,
        "interface_y_m": interface_y,
        "interface_structure_residual_m": residual,
        "parent_events_sha256": sha256(PARENT_RUNTIME / "structure" / "events.jsonl"),
    }


def control_dict() -> str:
    return f'''FoamFile {{ format ascii; class dictionary; object controlDict; }}
application pimpleFoam;
libs ("libpreciceAdapterFunctionObject.so");
startFrom latestTime; stopAt endTime; endTime {END:.12g}; deltaT {DT:.12g};
writeControl timeStep; writeInterval 1; purgeWrite 0; writeFormat ascii; writePrecision 12; writeCompression off; timeFormat general; timePrecision 12; runTimeModifiable false;
functions {{ preCICE_Adapter {{ type preciceAdapterFunctionObject; }} cylinderForces {{ type forces; libs ("libforces.so"); writeControl timeStep; writeInterval 1; log yes; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); }} }}
'''


def dynamic_mesh() -> str:
    return '''FoamFile { format ascii; class dictionary; object dynamicMeshDict; }
mover { type motionSolver; libs ("libfvMeshMovers.so" "libfvMotionSolvers.so"); motionSolver displacementLaplacian; diffusivity uniform; }
'''


def precice_dict() -> str:
    return '''FoamFile { format ascii; class dictionary; object preciceDict; }
preciceConfig "precice-config.xml"; participant Fluid_0000; modules (FSI);
FSI { solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1000; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement pointDisplacement; nameCellDisplacement cellDisplacement; nameForce Force; }
interfaces { Interface1 { mesh Fluid-Mesh; patches (cylinder); locations faceCenters; readData (Displacement); writeData (Force); } }
'''


def precice_xml(exchange: Path) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">
<data:vector name="Displacement" waveform-degree="0"/><data:vector name="Force" waveform-degree="0"/>
<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>
<m2n:sockets acceptor="Structure_0000" connector="Fluid_0000" exchange-directory="{wsl(exchange)}"/>
<participant name="Structure_0000"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>
<participant name="Fluid_0000"><receive-mesh name="Structure-Mesh" from="Structure_0000"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>
<coupling-scheme:parallel-implicit><participants first="Structure_0000" second="Fluid_0000"/><max-time value="{STEPS * DT:.12g}"/><time-window-size value="{DT:.12g}"/><min-iterations value="{MIN_ITERATIONS}"/><max-iterations value="{MAX_ITERATIONS}"/><absolute-or-relative-convergence-measure data="Displacement" mesh="Structure-Mesh" abs-limit="1e-8" rel-limit="1e-5"/><absolute-or-relative-convergence-measure data="Force" mesh="Structure-Mesh" abs-limit="1e-3" rel-limit="1e-5"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_0000" to="Fluid_0000" initialize="yes" substeps="false"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid_0000" to="Structure_0000" substeps="false"/></coupling-scheme:parallel-implicit>
</precice-configuration>
'''


def prepare() -> None:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("runtime/results already exist: one execution only; no automatic retry")
    parent = require_parent()
    initial_force = parent["force"]
    final = parent["final_commit"]
    state = final["accepted_state"]
    case = RUNTIME / "precice_displacementLaplacian"
    shutil.copytree(PARENT_CASE, case)
    # The parent stopped during W244 at 6.375 s.  That directory is a
    # rejected/incomplete trial, never a restart source.  Remove numeric
    # directories later than the last jointly accepted time only in this new
    # runtime before `startFrom latestTime` is allowed to run.
    removed_trial_times: list[str] = []
    for entry in case.iterdir():
        if not entry.is_dir():
            continue
        try:
            value = float(entry.name)
        except ValueError:
            continue
        if value > START + 1.0e-12:
            shutil.rmtree(entry)
            removed_trial_times.append(entry.name)
    if removed_trial_times != ["6.375"]:
        raise RuntimeError(f"unexpected copied unaccepted time directories: {removed_trial_times}")
    # Function-object output and preCICE socket files are parent-run evidence,
    # not restart state.  Remove only their copies in this new runtime.
    shutil.rmtree(case / "postProcessing")
    write(case / "system" / "controlDict", control_dict())
    exchange = RUNTIME / "precice-sockets"
    exchange.mkdir(parents=True)
    write(case / "precice-config.xml", precice_xml(exchange))
    contract = {
        "schema_version": "shiels-s5-k988-single-slice-free-fsi-long-development-resume-v2",
        "execution_policy": "one controlled resume only from accepted 6.370 s to 100.155 s; automatic retry/extension forbidden",
        "physical_contract": {
            "Re": 100, "m_star_shiels": 5.0, "k_star_shiels": 9.88, "b_star_shiels": 0.0,
            "D_m": 1.0, "U_mps": 1.0, "rho_kgpm3": 1000.0, "nu_m2ps": 0.01, "span_m": 1.0,
            "M_kg": MASS_KG, "K_Npm": STIFFNESS_NPM, "C_Nspm": 0.0,
            "equation": "M*y_ddot + K*y = Fy_total; transverse only; x=0",
            "force_definition": "total pressure plus viscous cylinder force over the 1 m computational span",
        },
        "restart": {
            "parent_runtime": str(PARENT_RUNTIME), "parent_events_sha256": parent["parent_events_sha256"],
            "parent_status": "INCOMPLETE_RUNTIME; restart source is only its final jointly accepted 6.370 s state",
            "physical_time_s": START, "sdof_state": state,
            "previous_accepted_force_y_N": initial_force["total_y_N"],
            "initial_interface_y_m": parent["interface_y_m"],
            "interface_structure_residual_m": parent["interface_structure_residual_m"],
            "prior_accepted_windows": 1253,
            "cumulative_fluid_work_J": final["cumulative_fluid_work_J"],
            "cumulative_energy_balance_defect_J": final["cumulative_energy_balance_defect_J"],
            "force_components_N": initial_force,
            "naturally_persisted_fields": source_hashes(),
            "counterfactual_Uf_used": False,
        },
        "coupling": {
            "scheme": "parallel-implicit", "dt_s": DT, "start_of_time_s": START, "end_of_time_s": END,
            "accepted_window_limit": STEPS, "min_iterations": MIN_ITERATIONS, "max_iterations": MAX_ITERATIONS,
            "acceleration": "none", "displacement_abs_limit_m": 1e-8, "displacement_rel_limit": 1e-5,
            "force_abs_limit_N": 1e-3, "force_rel_limit": 1e-5,
            "time_layer_contract": "initial data equals the parent final CFD interface y(t0); SDOF restores the parent accepted state. Every trial writes candidate y(t_n), reads Force(t_n), and restores only the same current-window physical checkpoint.",
        },
        "frozen_safety_gates": {"max_Co": MAX_COURANT, "max_abs_global_continuity": MAX_GLOBAL_CONTINUITY,
                                "max_abs_y_m": MAX_ABS_DISPLACEMENT_M, "max_abs_v_mps": MAX_ABS_VELOCITY_MPS,
                                "max_abs_Fy_N": MAX_ABS_FORCE_Y_N, "motion_abs_tol_m": MOTION_ABS_TOL_M},
        "abi": {"of_prefix_wsl": OF_PREFIX_WSL, "adapter_lib_wsl": ADAPTER_LIB_WSL, "adapter_sha256": ADAPTER_SHA256},
        "prohibited": ["ANCF", "three-slice", "long VIV", "counterfactual Uf", "added mass", "damping", "automatic rerun", "dt/mesh/PIMPLE change"],
    }
    write_json(RUNTIME / "contract.json", contract)
    write_json(RUNTIME / "manifest.json", {
        "participant": str(PARTICIPANT), "participant_sha256": sha256(PARTICIPANT), "contract_sha256": sha256(RUNTIME / "contract.json"),
        "parent_6p370_hashes": source_hashes(), "restart_force": initial_force, "case": str(case),
        "removed_unaccepted_trial_time_directories": removed_trial_times,
        "only_new_production_path_component": "test-only continuation-capable SDOF preCICE participant wrapper",
    })


def abi_preflight() -> dict[str, Any]:
    script = RUNTIME / "abi_preflight.sh"
    write(script, "\n".join((
        "set -o pipefail", "export ZSH_NAME=", f"source '{ENV_SCRIPT_WSL}' '{ABI_ROOT_WSL}'",
        f"export LD_LIBRARY_PATH='{ADAPTER_LIB_WSL}':$LD_LIBRARY_PATH",
        "pimple=$(command -v pimpleFoam)", "printf 'PIMPLE=%s\\n' \"$(readlink -f \"$pimple\")\"",
        f"printf 'ADAPTER=%s\\n' \"$(readlink -f '{ADAPTER_LIB_WSL}/libpreciceAdapterFunctionObject.so')\"",
        "printf 'PIMPLE_SHA256='; sha256sum \"$(readlink -f \"$pimple\")\"",
        f"printf 'ADAPTER_SHA256='; sha256sum '{ADAPTER_LIB_WSL}/libpreciceAdapterFunctionObject.so'",
        "printf '%s\\n' '--- LDD_PIMPLE ---'; ldd -r \"$(readlink -f \"$pimple\")\"",
        f"printf '%s\\n' '--- LDD_ADAPTER ---'; ldd -r '{ADAPTER_LIB_WSL}/libpreciceAdapterFunctionObject.so'",
    )) + "\n")
    done = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(script)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    result = {"return_code": done.returncode, "stdout": done.stdout, "stderr": done.stderr,
              "no_opt_openfoam10": "/opt/openfoam10" not in done.stdout,
              "no_undefined_symbol": "undefined symbol" not in done.stdout.lower(),
              "required_abi_root": ABI_ROOT_WSL, "required_adapter_root": ADAPTER_LIB_WSL}
    result["status"] = "PASS" if done.returncode == 0 and result["no_opt_openfoam10"] and result["no_undefined_symbol"] and ABI_ROOT_WSL in done.stdout and ADAPTER_LIB_WSL in done.stdout else "FAIL_CLOSED"
    return result


def preflight() -> None:
    if not (RUNTIME / "manifest.json").is_file():
        raise RuntimeError("prepare must complete before preflight")
    if (RUNTIME / "returns.txt").exists():
        raise RuntimeError("execution evidence exists; preflight cannot alter a used fixture")
    parent = require_parent()
    case = RUNTIME / "precice_displacementLaplacian"
    copied_hashes = {name: sha256(case / "6.37" / name) for name in source_hashes()}
    copy_identity = copied_hashes == source_hashes()
    unit_path = RESULTS / "continuation_wrapper_unit.json"
    done = subprocess.run(["python", str(PARTICIPANT), "--self-test", "--output", str(unit_path)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    unit = json.loads(unit_path.read_text(encoding="utf-8")) if done.returncode == 0 and unit_path.is_file() else {}
    abi = abi_preflight()
    outcome = {"continuation_wrapper_unit": unit, "unit_stdout": done.stdout, "unit_stderr": done.stderr, "abi": abi,
               "parent_restart": parent, "copied_6p370_field_identity": copy_identity,
               "time_layer": {"initial_data": "write parent final CFD interface y(t0=6.370) before initialize", "trial": "write candidate y(t_n), advance, read Force(t_n), correct", "rollback": "restore the same resumed-window SDOF state/previous accepted force only"}}
    outcome["status"] = "PASS" if unit.get("status") == "PASS" and abi.get("status") == "PASS" and copy_identity else "FAIL_CLOSED"
    write_json(RUNTIME / "preflight.json", outcome)
    if outcome["status"] != "PASS":
        raise RuntimeError("continuation wrapper, restart identity, or ABI preflight failed; CFD launch forbidden")


def launcher() -> str:
    case = RUNTIME / "precice_displacementLaplacian"
    participant_runtime = RUNTIME / "structure"
    return "\n".join((
        "set -o pipefail", "export ZSH_NAME=", f"source '{ENV_SCRIPT_WSL}' '{ABI_ROOT_WSL}'",
        f"export LD_LIBRARY_PATH='{ADAPTER_LIB_WSL}':$LD_LIBRARY_PATH", f"export PYTHONPATH='{wsl(PYDEPS)}:{wsl(ROOT)}'",
        f"export PRECICE_ADAPTER_BUILD_SHA256='{ADAPTER_SHA256}'",
        f"python3 '{wsl(PARTICIPANT)}' --config '{wsl(case / 'precice-config.xml')}' --runtime '{wsl(participant_runtime)}' --contract '{wsl(RUNTIME / 'contract.json')}' --vertex-count {VERTEX_COUNT} > '{wsl(RUNTIME / 'participant.stdout')}' 2> '{wsl(RUNTIME / 'participant.stderr')}' & structure_pid=$!",
        f"(cd '{wsl(case)}' && pimpleFoam > '{wsl(RUNTIME / 'fluid.stdout')}' 2> '{wsl(RUNTIME / 'fluid.stderr')}') & fluid_pid=$!",
        "wait $structure_pid; structure_rc=$?", "wait $fluid_pid; fluid_rc=$?",
        f"printf 'structure=%s fluid=%s\\n' \"$structure_rc\" \"$fluid_rc\" > '{wsl(RUNTIME / 'returns.txt')}'",
        "[ $structure_rc -eq 0 ] && [ $fluid_rc -eq 0 ] || exit 1",
        f"(cd '{wsl(case)}' && checkMesh -time {END:.12g} -allTopology -allGeometry > '{wsl(RUNTIME / 'checkMesh.stdout')}' 2> '{wsl(RUNTIME / 'checkMesh.stderr')}')",
    )) + "\n"


def execute() -> None:
    if not (RUNTIME / "preflight.json").is_file() or json.loads((RUNTIME / "preflight.json").read_text(encoding="utf-8")).get("status") != "PASS":
        raise RuntimeError("preflight is not PASS; launch forbidden")
    if (RUNTIME / "returns.txt").exists() or (RUNTIME / "launcher_return.json").exists():
        raise RuntimeError("execution evidence already exists; automatic retry forbidden")
    write(RUNTIME / "launch.sh", launcher())
    done = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(RUNTIME / "launch.sh")], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=7200)
    write(RUNTIME / "launcher.stdout", done.stdout)
    write(RUNTIME / "launcher.stderr", done.stderr)
    write_json(RUNTIME / "launcher_return.json", {"return_code": done.returncode})
    if done.returncode != 0:
        raise RuntimeError(f"controlled free-FSI trial returned {done.returncode}; first failure retained and no rerun permitted")


def launch_detached() -> None:
    if not (RUNTIME / "preflight.json").is_file() or json.loads((RUNTIME / "preflight.json").read_text(encoding="utf-8")).get("status") != "PASS":
        raise RuntimeError("preflight is not PASS; launch forbidden")
    if (RUNTIME / "returns.txt").exists() or (RUNTIME / "launcher_return.json").exists():
        raise RuntimeError("execution evidence already exists; automatic retry forbidden")
    write(RUNTIME / "launch.sh", launcher())
    creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    process = subprocess.Popen(
        ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(RUNTIME / "launch.sh")],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=creation_flags, close_fds=True,
    )
    write_json(RUNTIME / "launcher_process.json", {"pid": process.pid, "detached": True})


def points(case: Path, time_name: str) -> list[list[float]]:
    text = (case / time_name / "polyMesh" / "points").read_text(encoding="utf-8", errors="replace")
    return [[float(value) for value in row] for row in re.findall(rf"\(\s*({NUMBER})\s+({NUMBER})\s+({NUMBER})\s*\)", text)]


def cylinder_vertex_ids(case: Path) -> list[int]:
    boundary = block((case / "constant" / "polyMesh" / "boundary").read_text(encoding="utf-8"), "cylinder")
    start = int(re.search(r"\bstartFace\s+(\d+)", boundary).group(1))
    count = int(re.search(r"\bnFaces\s+(\d+)", boundary).group(1))
    faces = []
    for line in (case / "constant" / "polyMesh" / "faces").read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"\s*\d+\(([^)]*)\)", line)
        if match:
            faces.append([int(value) for value in match.group(1).split()])
    return sorted({point for face in faces[start : start + count] for point in face})


def patch_y_error(case: Path, time_name: str, expected_y: float) -> dict[str, Any]:
    raw = block((case / time_name / "pointDisplacement").read_text(encoding="utf-8", errors="replace"), "cylinder")
    values = re.findall(rf"\(\s*({NUMBER})\s+({NUMBER})\s+({NUMBER})\s*\)", raw)
    if values:
        ys = [float(row[1]) for row in values]
        return {"representation": "nonuniform", "value_count": len(ys), "max_abs_y_error_m": max(abs(value - expected_y) for value in ys)}
    uniform = re.search(rf"\bvalue\s+uniform\s+\(\s*({NUMBER})\s+({NUMBER})\s+({NUMBER})\s*\)", raw)
    if uniform is None:
        raise RuntimeError(f"cannot parse cylinder pointDisplacement at {time_name}")
    return {"representation": "uniform", "value_count": 1, "max_abs_y_error_m": abs(float(uniform.group(2)) - expected_y)}


def force_rows(case: Path) -> tuple[list[dict[str, float]], dict[str, int]]:
    file = case / "postProcessing" / "cylinderForces" / f"{START:.12g}" / "forces.dat"
    final_rows: dict[float, dict[str, float]] = {}
    records_by_time: dict[str, int] = {}
    for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
        values = [float(value) for value in re.findall(NUMBER, line)]
        if len(values) >= 7 and values[0] > START + 0.25 * DT:
            time_s = values[0]
            time_key = f"{time_s:.12g}"
            records_by_time[time_key] = records_by_time.get(time_key, 0) + 1
            # The force function writes once per implicit coupling iteration.
            # The last same-time record is the final iteration used by the
            # accepted structure window; preserve the raw count separately.
            final_rows[time_s] = {"time_s": time_s, "pressure_x_N": values[1], "pressure_y_N": values[2], "viscous_x_N": values[4], "viscous_y_N": values[5], "total_x_N": values[1] + values[4], "total_y_N": values[2] + values[5]}
    return [final_rows[time_s] for time_s in sorted(final_rows)], records_by_time


def log_audit() -> dict[str, Any]:
    text = (RUNTIME / "fluid.stdout").read_text(encoding="utf-8", errors="replace")
    co = [(float(a), float(b)) for a, b in re.findall(rf"Courant Number mean:\s*({NUMBER})\s+max:\s*({NUMBER})", text)]
    continuity = [float(value) for value in re.findall(rf"global\s*=\s*({NUMBER})", text)]
    forbidden = [name for name, pattern in {"foam_fatal": r"foam\s+fatal", "negative_volume": r"negative\s+volume", "nan": r"\bnan\b"}.items() if re.search(pattern, text, re.I)]
    fpe = re.findall(r".*floating\s+point\s+exception.*", text, re.I)
    if any("enabling" not in row.lower() for row in fpe):
        forbidden.append("floating_point_exception")
    return {"ended": text.rstrip().endswith("End"), "max_Co": max((row[1] for row in co), default=float("inf")),
            "max_abs_global_continuity": max((abs(value) for value in continuity), default=float("inf")), "forbidden": forbidden,
            "checkMesh_mesh_ok": "Mesh OK" in (RUNTIME / "checkMesh.stdout").read_text(encoding="utf-8", errors="replace")}


def audit() -> dict[str, Any]:
    case = RUNTIME / "precice_displacementLaplacian"
    summary = json.loads((RUNTIME / "structure" / "structure_summary.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (RUNTIME / "structure" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    commits = [row for row in events if row.get("event") == "window_commit"]
    forces, force_records_by_time = force_rows(case)
    restart = json.loads((RUNTIME / "contract.json").read_text(encoding="utf-8"))["restart"]
    if len(commits) != STEPS or len(forces) != STEPS:
        raise RuntimeError("incomplete output; cannot evaluate free-FSI first trial")
    initial_points = points(case, f"{START:.12g}")
    initial_interface_y = float(restart["initial_interface_y_m"])
    ids = cylinder_vertex_ids(case)
    motion_rows = []
    for commit, force in zip(commits, forces):
        time_name = f"{commit['physical_time_s']:.12g}"
        expected_y = float(commit["final_input_y_m"])
        live = points(case, time_name)
        # The restart mesh already contains the parent interface displacement.
        # Compare the continuation increment, not the absolute displacement twice.
        geometry_error = max(abs(live[index][1] - (initial_points[index][1] + expected_y - initial_interface_y)) for index in ids)
        patch = patch_y_error(case, time_name, expected_y)
        state = commit["accepted_state"]
        motion_rows.append({"window_index": commit["window_index"], "time_s": commit["physical_time_s"], "expected_input_y_m": expected_y,
                            "accepted_y_m": state["y_m"], "accepted_v_mps": state["v_mps"], "accepted_a_mps2": state["a_mps2"],
                            "actual_geometry_max_abs_y_error_m": geometry_error, "pointDisplacement": patch,
                            "force": force, "participant_force_y_N": commit["force_y_total_N"],
                            "force_sum_delta_N": force["total_y_N"] - float(commit["force_y_total_N"]),
                            "mechanical_energy_J": commit["mechanical_energy_J"], "cumulative_fluid_work_J": commit["cumulative_fluid_work_J"],
                            "cumulative_energy_balance_defect_J": commit["cumulative_energy_balance_defect_J"], "coupling_iterations": commit["iteration_count"]})
    logs = log_audit()
    returns = (RUNTIME / "returns.txt").read_text(encoding="utf-8").strip()
    hard = {
        "returns": returns == "structure=0 fluid=0", "one_thousand_commits": int(summary.get("accepted_windows", -1)) == STEPS,
        "rollback_observed": int(summary.get("checkpoint_restores", 0)) >= STEPS,
        "two_to_eight_iterations": all(MIN_ITERATIONS <= int(row["coupling_iterations"]) <= MAX_ITERATIONS for row in motion_rows),
        "motion_geometry": all(row["actual_geometry_max_abs_y_error_m"] <= MOTION_ABS_TOL_M and row["pointDisplacement"]["max_abs_y_error_m"] <= MOTION_ABS_TOL_M for row in motion_rows),
        "force_identity": all(abs(row["force_sum_delta_N"]) <= 1.0e-8 for row in motion_rows),
        "structure_containment": all(abs(row["accepted_y_m"]) <= MAX_ABS_DISPLACEMENT_M and abs(row["accepted_v_mps"]) <= MAX_ABS_VELOCITY_MPS and abs(row["participant_force_y_N"]) <= MAX_ABS_FORCE_Y_N for row in motion_rows),
        "quality": logs["ended"] and logs["max_Co"] <= MAX_COURANT and logs["max_abs_global_continuity"] <= MAX_GLOBAL_CONTINUITY and not logs["forbidden"] and logs["checkMesh_mesh_ok"],
        "restored_initial_state": all(abs(float(summary["initial_state"][key]) - float(restart["sdof_state"][key])) <= 1.0e-15 for key in ("y_m", "v_mps", "a_mps2")) and int(summary["initial_state"]["step"]) == int(restart["sdof_state"]["step"]),
    }
    result = {"schema_version": "shiels-s5-k988-single-slice-free-fsi-long-development-resume-v2-result", "status": "PASS" if all(hard.values()) else "FAIL_CLOSED",
              "hard_gates": hard, "restart": restart, "structure_summary": summary, "window_rows": motion_rows, "fluid_logs": logs,
              "force_function_records_by_time": force_records_by_time,
              "limitations": ["This is only 0.05 s, far shorter than one natural period; no lock-in/steady VIV claim is made.", "Energy is reported with trapezoidal fluid work because the undamped structure may gain/loss energy through fluid work; energy constancy is not a gate.", "The result applies to the existing Python SDOFRunner wrapper, not C++ ANCF or the 50 m riser."]}
    RESULTS.mkdir(parents=True, exist_ok=True)
    write_json(RESULTS / "first_trial_result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "preflight", "execute", "launch_detached", "audit"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(); print(json.dumps({"status": "PREPARED", "runtime": str(RUNTIME)})); return 0
    if args.command == "preflight":
        preflight(); print(json.dumps({"status": "PREFLIGHT_PASS", "runtime": str(RUNTIME)})); return 0
    if args.command == "execute":
        execute(); print(json.dumps({"status": "EXECUTED", "runtime": str(RUNTIME)})); return 0
    if args.command == "launch_detached":
        launch_detached(); print(json.dumps({"status": "LAUNCHED_DETACHED", "runtime": str(RUNTIME)})); return 0
    result = audit(); print(json.dumps({"status": result["status"], "hard_gates": result["hard_gates"]})); return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
