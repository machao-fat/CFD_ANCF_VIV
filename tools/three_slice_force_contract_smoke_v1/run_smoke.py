"""Fresh, bounded launcher for THREE_SLICE_FORCE_CONTRACT_SMOKE_V1."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.openfoam_quality_contract_v3.audit import audit_records
from coupling.convergence_observability_v1.openfoam_log import OpenFOAMLogParser

STAGE = "stage_force_contract_smoke_v1"
RUNTIME = ROOT / "runtime" / (STAGE + "_run_008")
RESULTS = ROOT / "results" / "three_slice_force_contract_smoke_v1_run_008"
CONTRACT = Path(__file__).with_name("three_slice_force_contract_smoke_v1_run_008.json")
SOURCE = ROOT / "cases/openfoam/single_slice_ancf_fsi"
STATE = ROOT / "runtime/stage4f_d_cpp_worker_initialization_v1/run_20260827_cpp_only/ancf_t0_state_cpp.json"
WORKER = ROOT / "runtime/292_cpp_worker_linux_build_v1/cfd_ancf_ancf_kernel_worker"
PYDEPS = ROOT / "runtime/284_precice_single_slice_smoke_real_v1/python_deps"

CONTROL = 'FoamFile { format ascii; class dictionary; object controlDict; }\napplication pimpleFoam;\nlibs ("libpreciceAdapterFunctionObject.so");\nstartFrom startTime; startTime 0; stopAt endTime; endTime 1; deltaT 0.005;\nwriteControl timeStep; writeInterval 1; purgeWrite 0; writeFormat ascii; writePrecision 12; writeCompression off; timeFormat general; timePrecision 12; runTimeModifiable false;\nfunctions { preCICE_Adapter { type preciceAdapterFunctionObject; } cylinderForces { type forces; libs ("libforces.so"); writeControl timeStep; writeInterval 1; log yes; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); } }\n'
# Foundation OpenFOAM 10 mover syntax.  The old dynamicFvMesh shorthand did
# not provide the persisted mesh-coordinate evidence required by revalidation.
DYNAMIC = 'FoamFile { format ascii; class dictionary; object dynamicMeshDict; }\nmover { type motionSolver; libs ("libfvMeshMovers.so" "libfvMotionSolvers.so"); motionSolver displacementLaplacian; diffusivity uniform; }\n'
POINT = 'FoamFile { format ascii; class pointVectorField; location "0"; object pointDisplacement; }\ndimensions [0 1 0 0 0 0 0]; internalField uniform (0 0 0); boundaryField { inlet { type fixedValue; value uniform (0 0 0); } outlet { type fixedValue; value uniform (0 0 0); } lower { type symmetryPlane; } upper { type symmetryPlane; } cylinder { type fixedValue; value uniform (0 0 0); } front { type empty; } back { type empty; } }\n'
CELL = 'FoamFile { format ascii; class volVectorField; location "0"; object cellDisplacement; }\ndimensions [0 1 0 0 0 0 0]; internalField uniform (0 0 0); boundaryField { inlet { type zeroGradient; } outlet { type zeroGradient; } lower { type symmetryPlane; } upper { type symmetryPlane; } cylinder { type fixedValue; value uniform (0 0 0); } front { type empty; } back { type empty; } }\n'


def wsl(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def put(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def ensure_cell_displacement_final(case: Path) -> None:
    """Supply the OpenFOAM 10 mover's final motion-solve control."""
    path = case / "system" / "fvSolution"
    text = path.read_text(encoding="utf-8")
    if "cellDisplacementFinal" not in text:
        text = text.replace("\n}\n\nPIMPLE\n{", "\n    cellDisplacementFinal\n    {\n        $cellMotionUx;\n        relTol 0;\n    }\n}\n\nPIMPLE\n{")
        put(path, text)


def xml(sid: int) -> str:
    socket = wsl(RUNTIME / "precice-sockets")
    return "\n".join((
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">',
        '<data:vector name="Displacement" waveform-degree="1"/><data:vector name="Force" waveform-degree="1"/>',
        '<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>',
        f'<m2n:sockets acceptor="Structure_{sid:04d}" connector="Fluid_{sid:04d}" exchange-directory="{socket}"/>',
        f'<participant name="Structure_{sid:04d}"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>',
        f'<participant name="Fluid_{sid:04d}"><receive-mesh name="Structure-Mesh" from="Structure_{sid:04d}"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>',
        f'<coupling-scheme:parallel-explicit><participants first="Structure_{sid:04d}" second="Fluid_{sid:04d}"/><time-window-size value="0.005"/><max-time value="1"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{sid:04d}" to="Fluid_{sid:04d}"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid_{sid:04d}" to="Structure_{sid:04d}"/></coupling-scheme:parallel-explicit></precice-configuration>',
    ))


def prepare() -> list[Path]:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to reuse versioned smoke paths")
    for path in (CONTRACT, SOURCE, STATE, WORKER, PYDEPS):
        if not path.exists(): raise RuntimeError(f"missing source: {path}")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if hashlib.sha256(STATE.read_bytes()).hexdigest() != contract["ANCF"]["initial_state"]["sha256"]:
        raise RuntimeError("fresh C++ static state hash mismatch")
    cases = []
    for sid in range(3):
        case = RUNTIME / "cases" / f"slice_{sid:04d}"
        for name in ("0", "constant", "system"): shutil.copytree(SOURCE / name, case / name)
        ensure_cell_displacement_final(case)
        put(case / "system/controlDict", CONTROL)
        put(case / "constant/dynamicMeshDict", DYNAMIC)
        put(case / "0/pointDisplacement", POINT); put(case / "0/cellDisplacement", CELL)
        # ``displacementLaplacian`` moves mesh points through the registered
        # pointDisplacement field.  Keep cellDisplacement for the adapter's
        # face-centre representation, but never disable its point projection.
        put(case / "system/preciceDict", f'FoamFile {{ format ascii; class dictionary; object preciceDict; }}\npreciceConfig "precice-config.xml"; participant Fluid_{sid:04d}; modules (FSI); FSI {{ solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1000; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement pointDisplacement; nameCellDisplacement cellDisplacement; nameForce Force; }} interfaces {{ Interface1 {{ mesh Fluid-Mesh; patches (cylinder); locations faceCenters; readData (Displacement); writeData (Force); }} }}\n')
        put(case / "precice-config.xml", xml(sid)); cases.append(case)
    (RUNTIME / "logs").mkdir(parents=True); (RUNTIME / "precice-sockets").mkdir()
    shutil.copy2(CONTRACT, RUNTIME / CONTRACT.name)
    return cases


def launch(cases: list[Path]) -> int:
    logs = RUNTIME / "logs"; part = wsl(Path(__file__).with_name("structure_participant.py")); root = wsl(ROOT)
    configs = " ".join("'" + wsl(case / "precice-config.xml") + "'" for case in cases)
    fluid = [f"(cd '{wsl(case)}' && pimpleFoam > '{wsl(logs / f'fluid_{sid:04d}.stdout')}' 2> '{wsl(logs / f'fluid_{sid:04d}.stderr')}') & p{sid}=$!" for sid,case in enumerate(cases)]
    script = ["set -o pipefail", "export ZSH_NAME=", "source /opt/openfoam10/etc/bashrc", f"export PYTHONPATH='{root}/src:{wsl(PYDEPS)}'", f"python3 '{part}' --contract '{wsl(RUNTIME / CONTRACT.name)}' --state '{wsl(STATE)}' --worker '{wsl(WORKER)}' --runtime '{wsl(RUNTIME)}' --config {configs} --vertex-count 40 > '{wsl(logs / 'structure.stdout')}' 2> '{wsl(logs / 'structure.stderr')}' & spid=$!", *fluid, f"printf 'structure_pid=%s\\nfluid_0000_pid=%s\\nfluid_0001_pid=%s\\nfluid_0002_pid=%s\\n' \"$spid\" \"$p0\" \"$p1\" \"$p2\" > '{wsl(logs / 'pids.txt')}'", "wait \"$spid\"; sr=$?; if [ \"$sr\" -ne 0 ]; then kill \"$p0\" \"$p1\" \"$p2\" 2>/dev/null || true; fi", "wait \"$p0\"; r0=$?; wait \"$p1\"; r1=$?; wait \"$p2\"; r2=$?", f"printf 'structure_return=%s\\nfluid_0000_return=%s\\nfluid_0001_return=%s\\nfluid_0002_return=%s\\n' \"$sr\" \"$r0\" \"$r1\" \"$r2\" > '{wsl(logs / 'returns.txt')}'", "[ \"$sr\" -eq 0 ] && [ \"$r0\" -eq 0 ] && [ \"$r1\" -eq 0 ] && [ \"$r2\" -eq 0 ]"]
    launch_file = RUNTIME / "launch.sh"
    put(launch_file, "\n".join(script) + "\n")
    completed = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(launch_file)], cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace", timeout=900)
    put(logs / "launcher.stdout", completed.stdout); put(logs / "launcher.stderr", completed.stderr); return completed.returncode


def audit(code: int) -> dict[str, object]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8")); summary_path = RUNTIME / "structure_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
    rows = [json.loads(line) for line in (RUNTIME / "records.jsonl").read_text(encoding="utf-8").splitlines()] if (RUNTIME / "records.jsonl").is_file() else []
    qc = contract["quality_contract"]; numerical = {"schema_version":1,"frozen_before_run":True,"courant_limit":qc["courant_limit"],"residual_definition":qc["residual_semantic_definition"],"residual_limit":qc["residual_threshold"],"continuity_definition":qc["continuity_semantic_definition"],"continuity_limit":qc["continuity_threshold"],"iteration_definition":qc["iteration_semantic_definition"],"iteration_limit":qc["iteration_failure"]}
    quality = {}
    reconciliation_errors: list[float] = []
    for sid in range(3):
        parser = OpenFOAMLogParser()
        log_path = RUNTIME / "logs" / f"fluid_{sid:04d}.stdout"
        for line in (log_path.read_text(encoding="utf-8",errors="replace").splitlines() if log_path.is_file() else []): parser.feed(line)
        quality[str(sid)] = audit_records(parser.finalize(), expected_count=200, expected_start_s=0.005, dt_s=0.005, numerical_contract=numerical)
        force_files = list((RUNTIME / "cases" / f"slice_{sid:04d}").glob("postProcessing/cylinderForces/*/forces.dat"))
        if len(force_files) != 1:
            reconciliation_errors.append(float("inf")); continue
        reported: dict[float, tuple[float, float, float]] = {}
        for line in force_files[0].read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line.startswith("#"): continue
            values = [float(value) for value in re.findall(r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", line)]
            if len(values) < 7: reconciliation_errors.append(float("inf")); continue
            reported[round(values[0], 12)] = (values[1] + values[4], values[2] + values[5], values[3] + values[6])
        for row in rows:
            actual = reported.get(round(float(row["time_s"]), 12)); load = row["loads"][sid]
            if actual is None: reconciliation_errors.append(float("inf")); continue
            reconciliation_errors.append(max(abs(actual[index] - float(load[key])) for index, key in enumerate(("openfoam_force_x_N", "openfoam_force_y_N", "openfoam_force_z_N"))))
    moment = [row["moment_audit"] for row in rows]
    maxf = max((float(item["force_error_absolute_N"]) for item in moment), default=float("inf")); maxm=max((float(item["moment_error_absolute_Nm"]) for item in moment),default=float("inf")); maxv=max((float(item["moment_error_normalized_v2"]) for item in moment),default=float("inf")); maxw=max((float(item.get("virtual_work",{}).get("normalized_error",float("inf"))) for item in moment),default=float("inf"))
    max_reconciliation = max(reconciliation_errors, default=float("inf"))
    mc=contract["mapping_contract"]
    force_chain_tolerance = float(mc["force_chain_identity_tolerance_N"])
    force_chain = all(
        all(
            all(abs(float(l[f"force_2d_{axis}_Npm"]) - float(l[f"openfoam_force_{axis}_N"])/float(l["unit_span_m"])) < force_chain_tolerance for axis in "xyz")
            and all(abs(float(l[f"force_{axis}_N"]) - float(l[f"force_2d_{axis}_Npm"])*float(l["slice_length_m"])) < force_chain_tolerance for axis in "xyz")
            for l in row["loads"]
        ) for row in rows
    )
    checks={"launch_return":code==0,"committed_200":len(rows)==200 and summary.get("committed_steps")==200,"three_loads_each_step":all(len(row.get("loads",[]))==3 for row in rows),"force_chain":force_chain,"force_function_reconciliation":max_reconciliation<=float(mc["openfoam_force_function_reconciliation_tolerance_N"]),"displacement":all(all(abs(float(m["x_m"])-float(m["x_ref_m"])-float(m["ux_m"]))<float(mc["displacement_identity_tolerance_m"]) and abs(float(m["y_m"])-float(m["y_ref_m"])-float(m["uy_m"]))<float(mc["displacement_identity_tolerance_m"]) and abs(float(m["z_m"])-float(m["z_ref_m"])-float(m["uz_m"]))<float(mc["displacement_identity_tolerance_m"]) for m in row["motion"]) for row in rows),"mapping":maxf<=mc["force_error_tolerance_N"] and maxm<=mc["absolute_moment_error_tolerance_Nm"] and maxv<=mc["normalized_moment_v2_tolerance"] and maxw<=mc["virtual_work_tolerance"],"quality":all(v["OBSERVABILITY_COMPLETENESS"]["status"]=="pass" and v["NUMERICAL_QUALITY"]["status"]=="pass" for v in quality.values()),"cpp":summary.get("status")=="completed" and summary.get("owned_residual")==0}
    result={"THREE_SLICE_FORCE_CONTRACT_SMOKE":"PASS" if all(checks.values()) else "FAIL","checks":checks,"max_force_error_N":maxf,"max_force_function_reconciliation_error_N":max_reconciliation,"max_absolute_moment_error_Nm":maxm,"max_v2_moment_error":maxv,"max_virtual_work_error":maxw,"quality":quality,"structure_summary":summary,"formal_status":contract["formal_status"],"next_stage_10_to_20s_physical_test":"CONDITIONAL" if all(checks.values()) else "NOT_AUTHORIZED"}
    RESULTS.mkdir(parents=True,exist_ok=True); put(RESULTS / "three_slice_force_contract_smoke_v1_gate.json",json.dumps(result,ensure_ascii=False,indent=2)); return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true", help="re-audit existing raw evidence without launching CFD")
    args = parser.parse_args()
    if args.audit_only:
        global RESULTS
        returns = (RUNTIME / "logs" / "returns.txt").read_text(encoding="utf-8")
        values = [int(value) for value in re.findall(r"(?:structure|fluid_\d+)_return=(\d+)", returns)]
        if len(values) != 4:
            raise RuntimeError("raw launch return evidence is incomplete")
        RESULTS = RESULTS.with_name(RESULTS.name + "_reaudit_v2")
        result = audit(0 if all(value == 0 for value in values) else 1)
    else:
        cases=prepare(); result=audit(launch(cases))
    print(json.dumps({"gate":result["THREE_SLICE_FORCE_CONTRACT_SMOKE"],"results":str(RESULTS)}))
    return 0 if result["THREE_SLICE_FORCE_CONTRACT_SMOKE"]=="PASS" else 1

if __name__ == "__main__": raise SystemExit(main())
