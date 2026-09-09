"""Run the one authorized current-CFD non-zero prescribed-motion bridge.

The paired exercise starts from the immutable native zero-motion state at
physical OF time 0.105 s.  That state was naturally produced by pimpleFoam;
no diagnostic compatible-Uf value is copied into either case.  The only
difference between the two cases is the mesh-motion delivery path:

* native `interpolatingSolidBody` with the supported OF10 `sixDoFMotion`
  table; and
* the current real preCICE adapter, `pointDisplacement`, and
  `displacementLaplacian` mover.

It is deliberately a bounded implementation bridge, not a free-FSI run or a
cycle-statistics study.  A single invocation prepares and executes exactly
one paired case; existing execution evidence causes a fail-closed refusal.
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
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BASELINE = (
    ROOT
    / "runtime"
    / "fixed_cylinder_precursor_initialization_v1_run_002"
    / "zero_motion_dynamic_restart"
)
CURRENT_ZERO = ROOT / "runtime" / "cfd_current_fixed_zero_bridge_v1_run_002" / "zero_precice_case"
RUNTIME = ROOT / "runtime" / "cfd_current_dynamic_nonzero_bridge_v1_run_001"
RESULTS = ROOT / "results" / "cfd_current_dynamic_nonzero_bridge_v1_run_001"
PYDEPS = ROOT / "runtime" / "284_precice_single_slice_smoke_real_v1" / "python_deps"

PROTOTYPE_ROOT_WSL = "/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1"
ABI_ROOT_WSL = PROTOTYPE_ROOT_WSL + "/owner_diagnostic_abi_build_001"
OF_PREFIX_WSL = ABI_ROOT_WSL + "/openfoam10"
ADAPTER_LIB_WSL = PROTOTYPE_ROOT_WSL + "/adapter_owner_diagnostic_build_001/lib"
ENV_SCRIPT_WSL = "/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/tools/of10_owned_atomic_mesh_history_restore_prototype_v1/prototype_env.sh"
ADAPTER_SHA256 = "c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17"

START = 0.105
DT = 0.005
STEPS = 100
END = START + STEPS * DT
AMPLITUDE_M = 0.1
FREQUENCY_HZ = 0.16
OMEGA = 2.0 * math.pi * FREQUENCY_HZ
RAMP_S = 0.1

# Frozen before execution.  Motion identity is a hard implementation gate.
# The two mesh algorithms intentionally have different interior deformation,
# so force agreement is reported quantitatively but is not asserted bitwise.
MOTION_ABS_TOL_M = 1.0e-9
MAX_COURANT = 0.5
MAX_GLOBAL_CONTINUITY = 1.0e-8
FORCE_COMPARE_RELATIVE_L2_REPORTING = 0.15

NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wsl(path: Path) -> str:
    raw = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + raw[0].lower() + raw[2:]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Python on this host does not accept ``newline`` on Path.write_text().
    # Keep exact LF serialization through the supported file-object API.
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def motion(time_s: float) -> tuple[float, float, float]:
    """Return imposed y, analytic ydot, and sampled-time ramp at OF time."""
    tau = max(0.0, time_s - START)
    if tau < RAMP_S:
        ramp = 0.5 * (1.0 - math.cos(math.pi * tau / RAMP_S))
        ramp_dot = 0.5 * math.pi / RAMP_S * math.sin(math.pi * tau / RAMP_S)
    else:
        ramp = 1.0
        ramp_dot = 0.0
    angle = OMEGA * tau
    y = AMPLITUDE_M * ramp * math.sin(angle)
    vy = AMPLITUDE_M * (ramp_dot * math.sin(angle) + ramp * OMEGA * math.cos(angle))
    return y, vy, ramp


def sampled_motion_plan() -> list[dict[str, float]]:
    plan: list[dict[str, float]] = []
    previous = None
    for step in range(STEPS + 1):
        time_s = START + step * DT
        y, analytic_vy, ramp = motion(time_s)
        plan.append(
            {
                "step": step,
                "time_s": time_s,
                "y_m": y,
                "analytic_vy_m_per_s": analytic_vy,
                "sampled_vy_m_per_s": 0.0 if previous is None else (y - previous) / DT,
                "ramp": ramp,
            }
        )
        previous = y
    return plan


def source_hashes() -> dict[str, str]:
    files = (
        "U",
        "p",
        "phi",
        "Uf",
        "meshPhi",
        "pointDisplacement",
        "cellDisplacement",
        "polyMesh/points",
        "uniform/time",
    )
    return {name: sha256(BASELINE / "0.105" / name) for name in files}


def require_baseline() -> None:
    required = (
        "0.105/U",
        "0.105/p",
        "0.105/phi",
        "0.105/Uf",
        "0.105/meshPhi",
        "0.105/pointDisplacement",
        "0.105/cellDisplacement",
        "0.105/polyMesh/points",
        "0.105/uniform/time",
        "constant/polyMesh/points",
        "system/fvSchemes",
        "system/fvSolution",
        "constant/dynamicMeshDict",
    )
    missing = [name for name in required if not (BASELINE / name).is_file()]
    if missing:
        raise RuntimeError(f"legal native dynamic baseline incomplete: {missing}")
    # The baseline and the real preCICE zero path are known to have byte-equal
    # state at 0.105.  Re-check it rather than relying on a report statement.
    for name in ("U", "p", "phi", "Uf", "meshPhi", "pointDisplacement", "cellDisplacement", "polyMesh/points"):
        if sha256(BASELINE / "0.105" / name) != sha256(CURRENT_ZERO / "0.105" / name):
            raise RuntimeError(f"baseline is no longer identical to real preCICE zero state: {name}")


def copy_restart(case: Path) -> None:
    shutil.copytree(BASELINE / "constant", case / "constant")
    shutil.copytree(CURRENT_ZERO / "system", case / "system")
    shutil.copytree(BASELINE / "0.105", case / "0.105")


def control(adapter: bool) -> str:
    adapter_lib = 'libs ("libpreciceAdapterFunctionObject.so");\n' if adapter else ""
    adapter_fn = "preCICE_Adapter { type preciceAdapterFunctionObject; } " if adapter else ""
    return f"""FoamFile {{ format ascii; class dictionary; object controlDict; }}
application pimpleFoam;
{adapter_lib}startFrom latestTime; stopAt endTime; endTime {END:.12g}; deltaT {DT:.12g};
writeControl timeStep; writeInterval 1; purgeWrite 0; writeFormat ascii; writePrecision 12; writeCompression off; timeFormat general; timePrecision 12; runTimeModifiable false;
functions {{ {adapter_fn}cylinderForces {{ type forces; libs ("libforces.so"); writeControl timeStep; writeInterval 1; log yes; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); }} }}
"""


def native_dynamic_mesh() -> str:
    return """FoamFile { format ascii; class dictionary; object dynamicMeshDict; }
mover
{
    type motionSolver;
    libs ("libfvMeshMovers.so" "libfvMotionSolvers.so");
    motionSolver interpolatingSolidBody;
    patches (cylinder);
    CofG (0 0 0);
    innerDistance 0.75;
    outerDistance 2.50;
    solidBodyMotionFunction sixDoFMotion;
    translationRotation table;
    interpolationScheme linear;
    file "$FOAM_CASE/constant/bridgeMotion.dat";
}
"""


def adapter_dynamic_mesh() -> str:
    return """FoamFile { format ascii; class dictionary; object dynamicMeshDict; }
mover { type motionSolver; libs ("libfvMeshMovers.so" "libfvMotionSolvers.so"); motionSolver displacementLaplacian; diffusivity uniform; }
"""


def motion_table(plan: list[dict[str, float]]) -> str:
    entries = [f"({row['time_s']:.12g} ((0 {row['y_m']:.16g} 0) (0 0 0)))" for row in plan]
    return f"{len(entries)}\n(\n" + "\n".join(entries) + "\n)\n"


def precice_dict() -> str:
    return """FoamFile { format ascii; class dictionary; object preciceDict; }
preciceConfig "precice-config.xml"; participant Fluid_0000; modules (FSI);
FSI { solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1000; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement pointDisplacement; nameCellDisplacement cellDisplacement; nameForce Force; }
interfaces { Interface1 { mesh Fluid-Mesh; patches (cylinder); locations faceCenters; readData (Displacement); writeData (Force); } }
"""


def precice_xml(exchange: Path) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">
<data:vector name="Displacement" waveform-degree="0"/><data:vector name="Force" waveform-degree="0"/>
<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>
<m2n:sockets acceptor="Structure_0000" connector="Fluid_0000" exchange-directory="{wsl(exchange)}"/>
<participant name="Structure_0000"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>
<participant name="Fluid_0000"><receive-mesh name="Structure-Mesh" from="Structure_0000"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>
<coupling-scheme:parallel-explicit><participants first="Structure_0000" second="Fluid_0000"/><max-time value="{STEPS * DT:.12g}"/><time-window-size value="{DT:.12g}"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_0000" to="Fluid_0000" initialize="yes" substeps="false"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid_0000" to="Structure_0000" substeps="false"/></coupling-scheme:parallel-explicit>
</precice-configuration>
"""


def participant_code() -> str:
    return r'''from __future__ import annotations
import hashlib, json, math, sys
from pathlib import Path
import precice

config, plan_path, evidence_path = map(Path, sys.argv[1:4])
plan = json.loads(plan_path.read_text(encoding="utf-8"))
vertices = [(0.5 * math.cos(2 * math.pi * i / 40), 0.5 * math.sin(2 * math.pi * i / 40)) for i in range(40)]
participant = precice.Participant("Structure_0000", str(config), 0, 1)
mesh = participant.set_mesh_vertices("Structure-Mesh", vertices)
def payload(y): return [[0.0, y] for _ in vertices]
def digest(values): return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
rows = []
try:
    initial = payload(float(plan[0]["y_m"]))
    requested = participant.requires_initial_data()
    if requested:
        participant.write_data("Structure-Mesh", "Displacement", mesh, initial)
    rows.append({"event":"INITIAL_DATA", "for_physical_time_s":plan[0]["time_s"], "payload_sha256":digest(initial), "y_m":plan[0]["y_m"], "requested":requested})
    participant.initialize()
    step = 0
    while participant.is_coupling_ongoing():
        target = plan[step + 1]
        values = payload(float(target["y_m"]))
        participant.write_data("Structure-Mesh", "Displacement", mesh, values)
        rows.append({"event":"WRITE_DISPLACEMENT_FOR_NEXT_CFD_STEP", "step":step + 1, "for_physical_time_s":target["time_s"], "y_m":target["y_m"], "sampled_vy_m_per_s":target["sampled_vy_m_per_s"], "payload_sha256":digest(values)})
        participant.advance(0.005)
        force = participant.read_data("Structure-Mesh", "Force", mesh, 0.0)
        force = force.tolist() if hasattr(force, "tolist") else force
        rows.append({"event":"READ_FORCE_AFTER_CFD_STEP", "step":step + 1, "physical_time_s":target["time_s"], "force_sum_N":[sum(float(row[d]) for row in force) for d in range(2)], "force_payload_sha256":digest(force)})
        step += 1
finally:
    participant.finalize()
evidence_path.write_text(json.dumps({"steps":step, "rows":rows, "contains_ancf":False, "motion_source":"frozen bridgeMotionPlan.json"}, indent=2) + "\n", encoding="utf-8")
'''


def prepare() -> None:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("runtime/results already exist: refusing an automatic second bridge execution")
    require_baseline()
    plan = sampled_motion_plan()
    native = RUNTIME / "native_interpolatingSolidBody"
    adapter = RUNTIME / "precice_displacementLaplacian"
    copy_restart(native)
    copy_restart(adapter)
    write(native / "system/controlDict", control(adapter=False))
    write(native / "constant/dynamicMeshDict", native_dynamic_mesh())
    write(native / "constant/bridgeMotion.dat", motion_table(plan))
    write(adapter / "system/controlDict", control(adapter=True))
    write(adapter / "constant/dynamicMeshDict", adapter_dynamic_mesh())
    write(adapter / "system/preciceDict", precice_dict())
    exchange = RUNTIME / "precice-sockets"
    exchange.mkdir(parents=True)
    write(adapter / "precice-config.xml", precice_xml(exchange))
    write(RUNTIME / "bridgeMotionPlan.json", json.dumps(plan, indent=2) + "\n")
    write(RUNTIME / "prescribed_participant.py", participant_code())
    manifest = {
        "schema_version": "cfd-current-dynamic-nonzero-bridge-v1",
        "execution_policy": "one paired execution; no automatic rerun",
        "baseline": {
            "path": str(BASELINE),
            "time_s": START,
            "build": "10-c4cf895ad8fa",
            "naturally_persisted_fields": source_hashes(),
            "preCICE_zero_byte_identity_rechecked": True,
            "note": "baseline was produced by a native zero-motion continuation; no counterfactual Uf is used",
        },
        "current_config_source": str(CURRENT_ZERO),
        "paths": {
            "native": "interpolatingSolidBody + sixDoFMotion table",
            "current": "real preCICE adapter + pointDisplacement + displacementLaplacian",
            "only_intended_difference": "mesh-motion delivery path",
        },
        "motion": {
            "formula": "y(t)=A*r(tau)*sin(2*pi*f*tau), tau=t-0.105; r=0.5*(1-cos(pi*tau/0.1)) for 0<=tau<0.1 else 1",
            "amplitude_m": AMPLITUDE_M,
            "amplitude_over_D": AMPLITUDE_M,
            "frequency_hz": FREQUENCY_HZ,
            "omega_rad_per_s": OMEGA,
            "ramp_s": RAMP_S,
            "start_s": START,
            "end_s": END,
            "steps": STEPS,
            "dt_s": DT,
            "table_interpolation": "linear between the frozen output-time samples",
        },
        "frozen_gates": {
            "motion_abs_tol_m": MOTION_ABS_TOL_M,
            "max_courant": MAX_COURANT,
            "max_abs_global_continuity": MAX_GLOBAL_CONTINUITY,
            "force_relative_l2_reporting_band": FORCE_COMPARE_RELATIVE_L2_REPORTING,
            "force_interpretation": "reporting only: different legitimate interior mesh deformation does not imply pointwise or force bit-identity",
        },
        "abi": {
            "of_prefix_wsl": OF_PREFIX_WSL,
            "adapter_lib_wsl": ADAPTER_LIB_WSL,
            "adapter_sha256": ADAPTER_SHA256,
        },
        "prohibited": ["ANCF", "free feedback", "counterfactual Uf", "0.05s three-slice rerun", "long-period statistics", "automatic rerun"],
    }
    write(RUNTIME / "manifest.json", json.dumps(manifest, indent=2) + "\n")


def launcher() -> str:
    native = RUNTIME / "native_interpolatingSolidBody"
    adapter = RUNTIME / "precice_displacementLaplacian"
    return "\n".join(
        (
            "set -o pipefail",
            "export ZSH_NAME=",
            f"source '{ENV_SCRIPT_WSL}' '{ABI_ROOT_WSL}'",
            f"command -v pimpleFoam > '{wsl(RUNTIME / 'pimpleFoam_path.txt')}'",
            f"pimpleFoam -help > '{wsl(RUNTIME / 'pimpleFoam_help.txt')}' 2>&1 || true",
            f"(cd '{wsl(native)}' && pimpleFoam > '{wsl(RUNTIME / 'native.stdout')}' 2> '{wsl(RUNTIME / 'native.stderr')}')",
            "native_rc=$?",
            "[ $native_rc -eq 0 ] || exit $native_rc",
            f"export LD_LIBRARY_PATH='{ADAPTER_LIB_WSL}':$LD_LIBRARY_PATH",
            f"export PYTHONPATH='{wsl(PYDEPS)}'",
            f"export PRECICE_ADAPTER_BUILD_SHA256='{ADAPTER_SHA256}'",
            f"python3 '{wsl(RUNTIME / 'prescribed_participant.py')}' '{wsl(adapter / 'precice-config.xml')}' '{wsl(RUNTIME / 'bridgeMotionPlan.json')}' '{wsl(RUNTIME / 'participant_evidence.json')}' > '{wsl(RUNTIME / 'participant.stdout')}' 2> '{wsl(RUNTIME / 'participant.stderr')}' & structure_pid=$!",
            f"(cd '{wsl(adapter)}' && pimpleFoam > '{wsl(RUNTIME / 'adapter.stdout')}' 2> '{wsl(RUNTIME / 'adapter.stderr')}') & fluid_pid=$!",
            "wait $structure_pid; structure_rc=$?",
            "wait $fluid_pid; fluid_rc=$?",
            f"printf 'native=%s structure=%s fluid=%s\\n' \"$native_rc\" \"$structure_rc\" \"$fluid_rc\" > '{wsl(RUNTIME / 'returns.txt')}'",
            "[ $structure_rc -eq 0 ] && [ $fluid_rc -eq 0 ] || exit 1",
            f"(cd '{wsl(native)}' && checkMesh -time {END:.12g} -allTopology -allGeometry > '{wsl(RUNTIME / 'native.checkMesh.stdout')}' 2> '{wsl(RUNTIME / 'native.checkMesh.stderr')}')",
            f"(cd '{wsl(adapter)}' && checkMesh -time {END:.12g} -allTopology -allGeometry > '{wsl(RUNTIME / 'adapter.checkMesh.stdout')}' 2> '{wsl(RUNTIME / 'adapter.checkMesh.stderr')}')",
        )
    ) + "\n"


def execute() -> None:
    if not (RUNTIME / "manifest.json").is_file():
        raise RuntimeError("prepare must complete before execution")
    if (RUNTIME / "returns.txt").exists() or (RUNTIME / "launcher_return.json").exists():
        raise RuntimeError("execution evidence already exists: automatic rerun forbidden")
    write(RUNTIME / "launch.sh", launcher())
    done = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(RUNTIME / "launch.sh")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    write(RUNTIME / "launcher.stdout", done.stdout)
    write(RUNTIME / "launcher.stderr", done.stderr)
    write(RUNTIME / "launcher_return.json", json.dumps({"return_code": done.returncode}, indent=2) + "\n")
    if done.returncode != 0:
        raise RuntimeError(f"controlled bridge failed with launcher return {done.returncode}; no retry is permitted")


def block(text: str, name: str) -> str:
    found = re.search(rf"\b{re.escape(name)}\s*\{{", text)
    if not found:
        raise RuntimeError(f"missing block {name}")
    start = text.find("{", found.start())
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    raise RuntimeError(f"unterminated block {name}")


def cylinder_centroid(case: Path, time_name: str) -> list[float]:
    boundary = block((case / "constant/polyMesh/boundary").read_text(encoding="utf-8"), "cylinder")
    start = int(re.search(r"\bstartFace\s+(\d+)", boundary).group(1))
    count = int(re.search(r"\bnFaces\s+(\d+)", boundary).group(1))
    point_text = (case / time_name / "polyMesh/points").read_text(encoding="utf-8", errors="replace")
    points = [[float(v) for v in row] for row in re.findall(rf"\(\s*({NUMBER})\s+({NUMBER})\s+({NUMBER})\s*\)", point_text)]
    faces: list[list[int]] = []
    for line in (case / "constant/polyMesh/faces").read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"\s*\d+\(([^)]*)\)", line)
        if match:
            faces.append([int(value) for value in match.group(1).split()])
    selected = faces[start : start + count]
    centres = [[sum(points[index][axis] for index in face) / len(face) for axis in range(3)] for face in selected]
    return [sum(row[axis] for row in centres) / len(centres) for axis in range(3)]


def patch_displacement_y(case: Path, time_name: str) -> float | None:
    path = case / time_name / "pointDisplacement"
    if not path.is_file():
        return None
    try:
        cylinder = block(path.read_text(encoding="utf-8", errors="replace"), "cylinder")
    except RuntimeError:
        return None
    values = re.findall(rf"\(\s*({NUMBER})\s+({NUMBER})\s+({NUMBER})\s*\)", cylinder)
    if not values:
        uniform = re.search(rf"\bvalue\s+uniform\s+\(\s*({NUMBER})\s+({NUMBER})\s+({NUMBER})\s*\)", cylinder)
        return float(uniform.group(2)) if uniform else None
    return sum(float(value[1]) for value in values) / len(values)


def force_rows(case: Path) -> list[dict[str, float]]:
    candidates = sorted((case / "postProcessing/cylinderForces").glob("*/forces.dat"))
    if not candidates:
        return []
    rows: list[dict[str, float]] = []
    for raw in candidates[-1].read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        values = [float(value) for value in re.findall(NUMBER, raw)]
        if len(values) >= 7 and values[0] > START + 0.25 * DT:
            rows.append({
                "time_s": values[0],
                "pressure_x_N": values[1], "pressure_y_N": values[2],
                "viscous_x_N": values[4], "viscous_y_N": values[5],
                "total_x_N": values[1] + values[4], "total_y_N": values[2] + values[5],
            })
    return rows


def logs(case_name: str) -> dict[str, Any]:
    text = (RUNTIME / f"{case_name}.stdout").read_text(encoding="utf-8", errors="replace")
    co = [(float(a), float(b)) for a, b in re.findall(rf"Courant Number mean:\s*({NUMBER})\s+max:\s*({NUMBER})", text)]
    continuity = [float(value) for value in re.findall(rf"global\s*=\s*({NUMBER})", text)]
    forbidden_patterns = {
        "foam_fatal": r"foam\s+fatal",
        "negative_volume": r"negative\s+volume",
        "nan": r"\bnan\b",
    }
    forbidden = [name for name, pattern in forbidden_patterns.items() if re.search(pattern, text, flags=re.I)]
    # Foundation OF10 normally announces that SIGFPE trapping is enabled.  It
    # is evidence of the protection being active, not an exception.
    fpe_matches = re.findall(r".*floating\s+point\s+exception.*", text, flags=re.I)
    if any("floating point exception" in row.lower() and "enabling" not in row.lower() for row in fpe_matches):
        forbidden.append("floating_point_exception")
    return {
        "ended": text.rstrip().endswith("End"),
        "courant": [{"mean": mean, "max": maximum} for mean, maximum in co],
        "max_courant": max((value[1] for value in co), default=float("inf")),
        "max_abs_global_continuity": max((abs(value) for value in continuity), default=float("inf")),
        "forbidden_log_markers": forbidden,
        "checkMesh_mesh_ok": "Mesh OK" in (RUNTIME / f"{case_name}.checkMesh.stdout").read_text(encoding="utf-8", errors="replace"),
    }


def l2(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def audit() -> dict[str, Any]:
    native = RUNTIME / "native_interpolatingSolidBody"
    adapter = RUNTIME / "precice_displacementLaplacian"
    plan = json.loads((RUNTIME / "bridgeMotionPlan.json").read_text(encoding="utf-8"))
    baseline_centroid = cylinder_centroid(native, "0.105")
    snapshots: list[dict[str, Any]] = []
    for item in plan[1:]:
        time_name = f"{item['time_s']:.12g}"
        expected = baseline_centroid.copy()
        expected[1] += float(item["y_m"])
        native_c = cylinder_centroid(native, time_name)
        adapter_c = cylinder_centroid(adapter, time_name)
        native_error = math.sqrt(sum((native_c[i] - expected[i]) ** 2 for i in range(3)))
        adapter_error = math.sqrt(sum((adapter_c[i] - expected[i]) ** 2 for i in range(3)))
        snapshots.append({
            "step": item["step"], "time_s": item["time_s"], "expected_cylinder_centroid_m": expected,
            "native_cylinder_centroid_m": native_c, "adapter_cylinder_centroid_m": adapter_c,
            "native_motion_error_m": native_error, "adapter_motion_error_m": adapter_error,
            "native_adapter_centroid_delta_m": math.sqrt(sum((native_c[i] - adapter_c[i]) ** 2 for i in range(3))),
            "adapter_cylinder_pointDisplacement_y_m": patch_displacement_y(adapter, time_name),
            "meshPhi_present": {
                "native": (native / time_name / "meshPhi").is_file(),
                "adapter": (adapter / time_name / "meshPhi").is_file(),
            },
        })
    # The participant evidence records the *intended* outgoing preCICE time
    # layer.  Match the actual cylinder location against all frozen samples to
    # expose a delivery lag without assuming write() timing semantics.
    for row in snapshots:
        observed_y = row["adapter_cylinder_centroid_m"][1] - baseline_centroid[1]
        match = min(plan, key=lambda sample: abs(float(sample["y_m"]) - observed_y))
        row["adapter_best_matching_input_step"] = match["step"]
        row["adapter_best_matching_input_time_s"] = match["time_s"]
        row["adapter_best_matching_input_error_m"] = abs(float(match["y_m"]) - observed_y)
        row["adapter_input_lag_steps"] = row["step"] - match["step"]
    native_force = force_rows(native)
    adapter_force = force_rows(adapter)
    pairs = list(zip(native_force, adapter_force))
    force_comparison: dict[str, Any] = {"native_rows": len(native_force), "adapter_rows": len(adapter_force)}
    for component in ("pressure_x_N", "pressure_y_N", "viscous_x_N", "viscous_y_N", "total_x_N", "total_y_N"):
        difference = [right[component] - left[component] for left, right in pairs]
        reference = [left[component] for left, _ in pairs]
        force_comparison[component] = {
            "max_abs_difference_N": max((abs(value) for value in difference), default=None),
            "relative_l2": l2(difference) / max(l2(reference), 1.0),
            "within_reporting_band": l2(difference) / max(l2(reference), 1.0) <= FORCE_COMPARE_RELATIVE_L2_REPORTING,
        }
    participant = json.loads((RUNTIME / "participant_evidence.json").read_text(encoding="utf-8")) if (RUNTIME / "participant_evidence.json").is_file() else {}
    native_log = logs("native")
    adapter_log = logs("adapter")
    input_lags = [row["adapter_input_lag_steps"] for row in snapshots]
    one_step_input_lag = all(lag == 1 for lag in input_lags)
    hard = {
        "native_completed": native_log["ended"],
        "adapter_completed": adapter_log["ended"],
        "participant_steps": participant.get("steps") == STEPS,
        "all_meshPhi_written": all(row["meshPhi_present"][kind] for row in snapshots for kind in ("native", "adapter")),
        "native_motion_tracking": all(row["native_motion_error_m"] <= MOTION_ABS_TOL_M for row in snapshots),
        "adapter_motion_tracking": all(row["adapter_motion_error_m"] <= MOTION_ABS_TOL_M for row in snapshots),
        "native_courant": native_log["max_courant"] <= MAX_COURANT,
        "adapter_courant": adapter_log["max_courant"] <= MAX_COURANT,
        "native_continuity": native_log["max_abs_global_continuity"] <= MAX_GLOBAL_CONTINUITY,
        "adapter_continuity": adapter_log["max_abs_global_continuity"] <= MAX_GLOBAL_CONTINUITY,
        "native_no_hard_log_marker": not native_log["forbidden_log_markers"],
        "adapter_no_hard_log_marker": not adapter_log["forbidden_log_markers"],
        "force_rows_complete": len(native_force) == STEPS and len(adapter_force) == STEPS,
    }
    result = {
        "schema_version": "cfd-current-dynamic-nonzero-bridge-v1-result",
        "status": "PASS" if all(hard.values()) else "FAIL_CLOSED",
        "hard_gates": hard,
        "motion_tracking": snapshots,
        "force_comparison": force_comparison,
        "input_time_level": {
            "adapter_input_lag_steps": input_lags,
            "uniform_one_step_lag": one_step_input_lag,
            "consequence": "force comparison is not an interpolatingSolidBody-versus-adapter identity test when true; each adapter CFD step consumed the prior table sample",
        },
        "logs": {"native": native_log, "adapter": adapter_log},
        "participant": participant,
        "limitations": [
            "Interior mesh points, meshPhi, and fields are not required to be byte-identical because the two legal mover methods differ.",
            "The frozen 0.15 relative-L2 force band is descriptive rather than a validity gate; it is retained to make any discrepancy visible.",
            "This is prescribed motion without ANCF feedback and is not a free-FSI or VIV result.",
            "The execution is fail-closed if the real adapter does not consume the same frozen input time layer as the native reference.",
        ],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    write(RESULTS / "bridge_result.json", json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "execute", "audit"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
        print(json.dumps({"status": "PREPARED", "runtime": str(RUNTIME)}))
        return 0
    if args.command == "execute":
        execute()
        print(json.dumps({"status": "EXECUTED", "runtime": str(RUNTIME)}))
        return 0
    result = audit()
    print(json.dumps({"status": result["status"], "hard_gates": result["hard_gates"]}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
