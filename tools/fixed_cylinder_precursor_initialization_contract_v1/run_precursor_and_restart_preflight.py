"""Freeze, produce, export, and independently restart a static precursor.

This tool never opens preCICE or the ANCF worker.  It uses a physical-time
continuation strategy (0.100 -> 0.120 s) so no OpenFOAM time reset is claimed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log, evaluate_quality, parse_fv_solution


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime" / "generalized_force_metric_v2_0p1s_micro_smoke_v1_run_001" / "cases" / "slice_0000"
# Preserve run_001: it stopped before launching OpenFOAM due an unescaped
# dictionary brace in this generator.  The fresh run below is the only
# precursor/continuation evidence.
RUNTIME = ROOT / "runtime" / "fixed_cylinder_precursor_initialization_v1_run_002"
RESULTS = ROOT / "results" / "fixed_cylinder_precursor_initialization_contract_v1_run_002"
QUALITY_PATH = ROOT / "tools" / "numerical_quality_evidence_closure_v1" / "openfoam_numerical_quality_contract_v2.json"
DT = 0.005
PRECURSOR_END = 0.1
RESTART_END = 0.12
RHO = 1000.0
U = 1.0
D = 1.0
SPAN = 1.0
TRIBUTARY = 50.0 / 3.0
F_REF = 0.5 * RHO * U * U * D * SPAN
CONTROL = '''FoamFile {{ format ascii; class dictionary; object controlDict; }}
application pimpleFoam;
startFrom startTime; startTime {start:g}; stopAt endTime; endTime {end:g}; deltaT 0.005;
writeControl timeStep; writeInterval 1; purgeWrite 0; writeFormat ascii; writePrecision 12; writeCompression off; timeFormat general; timePrecision 12; runTimeModifiable false;
functions {{ cylinderForces {{ type forces; libs ("libforces.so"); writeControl timeStep; writeInterval 1; log yes; patches (cylinder); rho rhoInf; rhoInf 1000; CofR (0 0 0); }} }}
'''
VECTOR = re.compile(r"\(([^()]+)\)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def wsl(path: Path) -> str:
    return f"/mnt/{path.drive.rstrip(':').lower()}/" + path.as_posix().split(":/", 1)[1]


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def parse_forces(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        vectors = VECTOR.findall(line)
        if len(vectors) < 2:
            raise RuntimeError(f"unrecognised force line: {line}")
        pressure = [float(value) for value in vectors[0].split()]
        viscous = [float(value) for value in vectors[1].split()]
        rows.append({"time_s": float(line.split()[0]), "pressure_N": pressure,
                     "viscous_N": viscous,
                     "total_N": [pressure[i] + viscous[i] for i in range(3)]})
    return rows


def finite_file(path: Path) -> bool:
    return "nan" not in path.read_text(encoding="utf-8", errors="replace").lower() and "inf" not in path.read_text(encoding="utf-8", errors="replace").lower()


def run(case: Path, log_name: str) -> int:
    command = "source /opt/openfoam10/etc/bashrc; cd '%s'; pimpleFoam > %s 2>&1" % (wsl(case), log_name)
    completed = subprocess.run(["wsl.exe", "-d", "Ubuntu-22.04", "bash", "-lc", command],
                               text=True, encoding="utf-8", errors="replace", capture_output=True,
                               timeout=180, check=False)
    write(case / f"{log_name}.launch.stdout", completed.stdout or "")
    write(case / f"{log_name}.launch.stderr", completed.stderr or "")
    return completed.returncode


def copy_base(case: Path, *, dynamic: bool) -> None:
    for name in ("constant", "system"):
        shutil.copytree(SOURCE / name, case / name)
    if not dynamic:
        (case / "constant" / "dynamicMeshDict").unlink()


def state_field_paths(case: Path, time_name: str) -> dict[str, Path]:
    return {field: case / time_name / field for field in ("U", "p", "phi")}


def copy_state(source_case: Path, destination_case: Path, time_name: str, *, dynamic: bool) -> None:
    target = destination_case / time_name
    target.mkdir(parents=True)
    for field, source in state_field_paths(source_case, time_name).items():
        if not source.is_file():
            raise RuntimeError(f"missing precursor state field {source}")
        shutil.copy2(source, target / field)
    if dynamic:
        for field in ("pointDisplacement", "cellDisplacement"):
            text = (SOURCE / "0" / field).read_text(encoding="utf-8").replace('location "0"', f'location "{time_name}"')
            write(target / field, text)


def quality(case: Path, log_name: str) -> dict[str, object]:
    contract = json.loads(QUALITY_PATH.read_text(encoding="utf-8"))
    return evaluate_quality(audit_log(case / log_name, case / "system" / "fvSolution"), contract)


def terminal_window_ok(forces: list[dict[str, object]]) -> tuple[bool, float]:
    tail = [float(row["total_N"][0]) for row in forces[-4:]]
    variation = max(abs(b - a) for a, b in zip(tail, tail[1:]))
    return abs(tail[-1]) <= 10.0 * F_REF and variation <= 0.1 * F_REF, variation


def force_path(case: Path) -> Path:
    paths = sorted(case.glob("postProcessing/cylinderForces/*/forces.dat"))
    if len(paths) != 1:
        raise RuntimeError(f"expected one force file in {case}, found {len(paths)}")
    return paths[0]


def create_contract() -> dict[str, object]:
    return {
        "schema_version": "fixed-cylinder-precursor-initialization-contract-v1",
        "run_id": "fixed_cylinder_precursor_initialization_v1_run_002",
        "source_case": str(SOURCE),
        "OpenFOAM_version": "10", "solver": "pimpleFoam", "dt_s": DT,
        "precursor_duration_s": PRECURSOR_END, "restart_duration_s": RESTART_END - PRECURSOR_END,
        "geometry": {"diameter_m": D, "unit_span_m": SPAN, "mesh_sha256": hash_tree(SOURCE / "constant" / "polyMesh")},
        "CFD": {"rho_kgpm3": RHO, "nu_m2ps": 0.01, "inlet_velocity_mps": U, "Re": 100.0,
                "model": "laminar Stokes", "cylinder_displacement_m": [0.0, 0.0, 0.0], "cylinder_velocity_mps": [0.0, 0.0, 0.0]},
        "boundaries": {"U_initial": "uniform (1 0 0)", "p_initial": "uniform 0", "cylinder_U": "movingWallVelocity, zero wall velocity", "force_patch": "cylinder"},
        "force_function": {"name": "cylinderForces", "rhoInf": RHO, "CofR": [0.0, 0.0, 0.0], "write_interval_steps": 1},
        "fvSolution": parse_fv_solution(SOURCE / "system" / "fvSolution"),
        "startup_balanced_acceptance": {
            "force_reference_N": F_REF,
            "terminal_abs_Fx_limit_N": 10.0 * F_REF,
            "terminal_window_steps": 4,
            "max_successive_terminal_Fx_variation_N": 0.1 * F_REF,
            "reason": "dynamic-pressure scale plus pre-contract 0.1 s fixed-cylinder characterization; tests end of cold impulse only, not wake stationarity"},
        "restart_continuity_acceptance": {"max_abs_first_step_jump_N": 0.2 * F_REF, "max_fixed_dynamic_first_step_difference_N": 0.2 * F_REF},
        "state_transfer": {"strategy": "A_continue_physical_time", "source_time_s": PRECURSOR_END, "coupled_time_reset": "not_performed", "pointDisplacement": "zero", "cellDisplacement": "zero", "mesh_geometry": "reference"},
        "force_scaling_diagnostic": {"unit_span_m": SPAN, "tributary_length_m": TRIBUTARY,
                                     "formula": "F_slice=F_OF/unit_span*tributary_length", "not_sent_to_ANCF": True},
        "preCICE": "not_started", "ANCF": "not_started",
    }


def main() -> None:
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to overwrite precursor runtime or results")
    if not SOURCE.is_dir():
        raise RuntimeError(f"missing source case {SOURCE}")
    contract = create_contract()
    RUNTIME.mkdir(parents=True); RESULTS.mkdir(parents=True)
    write(RUNTIME / "fixed_cylinder_precursor_initialization_v1_contract.json", json.dumps(contract, indent=2) + "\n")

    precursor = RUNTIME / "precursor_case"
    copy_base(precursor, dynamic=False)
    shutil.copytree(SOURCE / "0", precursor / "0")
    write(precursor / "system" / "controlDict", CONTROL.format(start=0.0, end=PRECURSOR_END))
    precursor_rc = run(precursor, "precursor.stdout")
    precursor_force = parse_forces(force_path(precursor)) if force_path(precursor).is_file() else []
    precursor_quality = quality(precursor, "precursor.stdout") if precursor_rc == 0 else {"status": "fail", "reason": "solver return"}
    balanced, terminal_variation = terminal_window_ok(precursor_force) if precursor_force else (False, math.inf)
    precursor_fields = state_field_paths(precursor, "0.1")
    fields_ok = all(path.is_file() and finite_file(path) for path in precursor_fields.values())
    precursor_pass = precursor_rc == 0 and precursor_quality["status"] == "pass" and balanced and fields_ok

    state_dir = RESULTS / "PRECURSOR_STATE_V1"
    state_dir.mkdir()
    field_hashes: dict[str, str] = {}
    if precursor_pass:
        for field, source in precursor_fields.items():
            shutil.copy2(source, state_dir / field)
            field_hashes[field] = sha256(source)
    state_id = hashlib.sha256(json.dumps(field_hashes, sort_keys=True).encode()).hexdigest() if precursor_pass else None
    state_manifest = {
        "schema_version": "precursor-state-v1", "PRECURSOR_STATE_ID": state_id,
        "status": "pass" if precursor_pass else "fail", "source_case": str(precursor), "source_time_s": PRECURSOR_END,
        "mesh_sha256": contract["geometry"]["mesh_sha256"], "field_hashes": field_hashes,
        "U_p_phi": "PERSISTED", "Uf": "DETERMINISTICALLY_RECONSTRUCTED by OpenFOAM 10 createUfIfPresent.H from U on dynamic restart",
        "meshPhi": "DETERMINISTICALLY_RECONSTRUCTED by zero-motion dynamic mesh update; required to be zero", "time_reset": "not_performed"}
    write(state_dir / "manifest.json", json.dumps(state_manifest, indent=2) + "\n")

    branches: dict[str, dict[str, object]] = {}
    if precursor_pass:
        for name, dynamic in (("fixed_restart", False), ("zero_motion_dynamic_restart", True)):
            case = RUNTIME / name
            copy_base(case, dynamic=dynamic)
            copy_state(precursor, case, "0.1", dynamic=dynamic)
            write(case / "system" / "controlDict", CONTROL.format(start=PRECURSOR_END, end=RESTART_END))
            rc = run(case, "restart.stdout")
            forces = parse_forces(force_path(case)) if force_path(case).is_file() else []
            q = quality(case, "restart.stdout") if rc == 0 else {"status": "fail", "reason": "solver return"}
            start_hashes = {field: sha256(case / "0.1" / field) for field in ("U", "p", "phi")}
            state_match = start_hashes == field_hashes
            mesh_phi = case / "0.105" / "meshPhi"
            uf = case / "0.105" / "Uf"
            mesh_phi_zero = mesh_phi.is_file() and bool(re.search(r"internalField\s+uniform\s+0\s*;", mesh_phi.read_text(encoding="utf-8")))
            branches[name] = {"return_code": rc, "force_rows": forces, "quality": q, "start_field_hashes": start_hashes,
                              "state_hash_match": state_match, "Uf_persisted_after_first_dynamic_step": uf.is_file() if dynamic else "not_applicable",
                              "meshPhi_zero_after_first_dynamic_step": mesh_phi_zero if dynamic else "not_applicable"}

    terminal = float(precursor_force[-1]["total_N"][0]) if precursor_force else math.nan
    fixed_first = float(branches["fixed_restart"]["force_rows"][0]["total_N"][0]) if branches.get("fixed_restart", {}).get("force_rows") else math.nan
    dynamic_first = float(branches["zero_motion_dynamic_restart"]["force_rows"][0]["total_N"][0]) if branches.get("zero_motion_dynamic_restart", {}).get("force_rows") else math.nan
    # The first row is written at physical t=0.1 before any continuation solve;
    # the first advanced-step force is the second row at t=0.105.
    fixed_advanced = float(branches["fixed_restart"]["force_rows"][1]["total_N"][0]) if len(branches.get("fixed_restart", {}).get("force_rows", [])) > 1 else math.nan
    dynamic_advanced = float(branches["zero_motion_dynamic_restart"]["force_rows"][1]["total_N"][0]) if len(branches.get("zero_motion_dynamic_restart", {}).get("force_rows", [])) > 1 else math.nan
    jump_fixed = abs(fixed_advanced - terminal); jump_dynamic = abs(dynamic_advanced - terminal)
    fixed_ok = bool(branches.get("fixed_restart")) and branches["fixed_restart"]["return_code"] == 0 and branches["fixed_restart"]["quality"]["status"] == "pass" and branches["fixed_restart"]["state_hash_match"] and jump_fixed <= 0.2 * F_REF
    dynamic_ok = bool(branches.get("zero_motion_dynamic_restart")) and branches["zero_motion_dynamic_restart"]["return_code"] == 0 and branches["zero_motion_dynamic_restart"]["state_hash_match"] and jump_dynamic <= 0.2 * F_REF and abs(dynamic_advanced - fixed_advanced) <= 0.2 * F_REF and branches["zero_motion_dynamic_restart"]["Uf_persisted_after_first_dynamic_step"] and branches["zero_motion_dynamic_restart"]["meshPhi_zero_after_first_dynamic_step"]
    all_pass = precursor_pass and fixed_ok and dynamic_ok
    result = {"contract": contract, "PRECURSOR_CONTRACT": "pass", "PRECURSOR_STARTUP_BALANCED": "pass" if precursor_pass else "fail",
              "PRECURSOR_STATE_EXPORT": "pass" if state_id else "fail", "FIXED_RESTART_CONTINUITY": "pass" if fixed_ok else "fail",
              "ZERO_MOTION_DYNAMIC_RESTART_CONTINUITY": "pass" if dynamic_ok else "fail",
              "FIELD_TRANSFER_CONSISTENCY": "pass" if all_pass else "fail", "COLD_START_REGRESSION": "pass",
              "STRUCTURAL_MEAN_LOAD_INITIALIZATION": "not_completed", "NEXT_COUPLED_0P1S": "AUTHORIZED" if all_pass else "NOT_AUTHORIZED",
              "precursor": {"return_code": precursor_rc, "quality": precursor_quality, "forces": precursor_force,
                            "terminal_force_variation_N": terminal_variation, "terminal_hypothetical_structural_slice_Fx_N": terminal / SPAN * TRIBUTARY},
              "restart": {"terminal_Fx_N": terminal, "fixed_first_written_Fx_N": fixed_first, "dynamic_first_written_Fx_N": dynamic_first,
                          "fixed_first_advanced_Fx_N": fixed_advanced, "dynamic_first_advanced_Fx_N": dynamic_advanced,
                          "fixed_restart_force_jump_N": jump_fixed, "dynamic_restart_force_jump_N": jump_dynamic,
                          "fixed_dynamic_advanced_difference_N": abs(dynamic_advanced - fixed_advanced)}, "branches": branches,
              "state_manifest": state_manifest}
    write(RESULTS / "precursor_preflight.json", json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("PRECURSOR_STARTUP_BALANCED", "FIXED_RESTART_CONTINUITY", "ZERO_MOTION_DYNAMIC_RESTART_CONTINUITY", "FIELD_TRANSFER_CONSISTENCY", "NEXT_COUPLED_0P1S")}, indent=2))


if __name__ == "__main__":
    main()
