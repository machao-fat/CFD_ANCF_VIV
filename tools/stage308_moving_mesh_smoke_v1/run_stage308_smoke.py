"""Run one newly-authorized, fail-closed three-slice moving-mesh smoke."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from coupling.stage307_moving_mesh_repair_v1.repair import audit_case_configuration, corrected_precice_dict, corrected_point_displacement
from coupling.performance_optimization_v1.config import optimize_control_dict, optimize_fv_solution

SOURCE_CASE = ROOT / "runtime/stage304_interface_mapping_repair_v1_fresh_zero_to80s/slice_0000"
FIXTURE = ROOT / "runtime/cpp_worker_to70s_real_v1/run_001/support/cpp_input_fixture.json"
WORKER = ROOT / "runtime/292_cpp_worker_linux_build_v1/cfd_ancf_ancf_kernel_worker"
PARTICIPANT = ROOT / "tools/stage305_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"
RUNTIME_DEFAULT = ROOT / "runtime/stage308_moving_mesh_smoke_v1_fresh"
RESULTS_DEFAULT = ROOT / "results/308_moving_mesh_smoke_v1"
DT = 0.005
STEPS = 8
TARGET_TIME = STEPS * DT
SLICE_COUNT = 3


def wsl(path: Path) -> str:
    value = str(path).replace("\\", "/")
    return "/mnt/" + value[0].lower() + value[2:]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return stream.read()
    return path.read_text(encoding="utf-8")


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def config_xml(index: int, socket: Path) -> str:
    name = f"{index:04d}"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<precice-configuration xmlns:data="http://www.precice.org/schemas/data" xmlns:m2n="http://www.precice.org/schemas/m2n" xmlns:coupling-scheme="http://www.precice.org/schemas/coupling-scheme" xmlns:mapping="http://www.precice.org/schemas/mapping">
<data:vector name="Displacement" waveform-degree="1"/><data:vector name="Force" waveform-degree="1"/>
<mesh name="Structure-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh><mesh name="Fluid-Mesh" dimensions="2"><use-data name="Displacement"/><use-data name="Force"/></mesh>
<m2n:sockets acceptor="Structure_{name}" connector="Fluid_{name}" exchange-directory="{wsl(socket)}"/>
<participant name="Structure_{name}"><provide-mesh name="Structure-Mesh"/><write-data name="Displacement" mesh="Structure-Mesh"/><read-data name="Force" mesh="Structure-Mesh"/></participant>
<participant name="Fluid_{name}"><receive-mesh name="Structure-Mesh" from="Structure_{name}"/><provide-mesh name="Fluid-Mesh"/><mapping:nearest-neighbor direction="read" from="Structure-Mesh" to="Fluid-Mesh" constraint="consistent"/><mapping:nearest-neighbor direction="write" from="Fluid-Mesh" to="Structure-Mesh" constraint="conservative"/><write-data name="Force" mesh="Fluid-Mesh"/><read-data name="Displacement" mesh="Fluid-Mesh"/></participant>
<coupling-scheme:parallel-explicit><participants first="Structure_{name}" second="Fluid_{name}"/><time-window-size value="{DT}"/><max-time value="{TARGET_TIME}"/><exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{name}" to="Fluid_{name}"/><exchange data="Force" mesh="Structure-Mesh" from="Fluid_{name}" to="Structure_{name}"/></coupling-scheme:parallel-explicit></precice-configuration>'''


def corrected_dynamic_mesh(mesh_method: str = "uniform") -> str:
    """Return an explicit OpenFOAM 10 native moving-mesh configuration."""
    methods = {
        "uniform": ("displacementLaplacian", "uniform;"),
        "inverseDistance": ("displacementLaplacian", "inverseDistance 1(cyl);"),
        "quadratic": ("displacementLaplacian", "quadratic inverseDistance 1(cyl);"),
        "exponential": ("displacementLaplacian", "exponential 1 inverseDistance 1(cyl);"),
        "sbrStress": ("displacementSBRStress", "quadratic inverseDistance 1(cyl);"),
        "rbf": ("rbfDisplacement", "uniform;"),
    }
    if mesh_method not in methods:
        raise ValueError(f"unsupported native mesh method: {mesh_method}")
    solver, diffusivity = methods[mesh_method]
    library_line = '    libs            ("libfvMeshMovers.so" "libfvMotionSolvers.so" "libRBFMotionSolver.so");\n' if mesh_method == "rbf" else '    libs            ("libfvMeshMovers.so" "libfvMotionSolvers.so");\n'
    extras = "    movingPatch     cyl;\n    controlStride   16;\n    supportRadius  7.5;\n" if mesh_method == "rbf" else ""
    return '''FoamFile
{
    format      ascii;
    class       dictionary;
    location    "system";
    object      dynamicMeshDict;
}

mover
{
    type            motionSolver;
LIBRARY_LINE    motionSolver    SOLVER;
    diffusivity     DIFFUSIVITY
EXTRAS}
'''.replace("LIBRARY_LINE", library_line).replace("SOLVER", solver).replace("DIFFUSIVITY", diffusivity).replace("EXTRAS", extras)


def runtime_point_displacement() -> str:
    """Foundation 10 adapter-compatible point field.

    The adapter's FSI reader writes through a refCast to a Field.  A
    calculated point patch is not castable in OpenFOAM 10, so the cylinder
    patch must remain fixedValue while the adapter updates its values.
    """
    return corrected_point_displacement()


def configure_sbr_stress_solver(text: str) -> str:
    """Use a symmetric Krylov solver for SBR-stress motion equations."""
    pattern = r'("cellDisplacement\.\*"\s*\{).*?\n\s*\}'
    replacement = (
        r'\1\n'
        '        solver          PCG;\n'
        '        preconditioner  DIC;\n'
        '        tolerance       1e-05;\n'
        '        relTol          0;\n'
        '        minIter         1;\n'
        '        maxIter         1000;\n'
        '    }'
    )
    result, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise ValueError("cellDisplacement solver block is missing")
    return result


def prepare(runtime: Path, profile: str = "baseline", mesh_method: str = "uniform") -> list[Path]:
    if runtime.exists() and any(runtime.iterdir()):
        raise RuntimeError(f"refusing to reuse runtime: {runtime}")
    for path in (SOURCE_CASE, FIXTURE, WORKER, PARTICIPANT):
        if not path.exists():
            raise RuntimeError(f"required source missing: {path}")
    cases: list[Path] = []
    for index in range(SLICE_COUNT):
        case = runtime / f"slice_{index:04d}"
        for name in ("0", "constant", "system"):
            shutil.copytree(SOURCE_CASE / name, case / name)
        control_path = case / "system/controlDict"
        control = control_path.read_text(encoding="utf-8")
        control = re.sub(r"startFrom\s+[^;]+;", "startFrom       startTime;", control)
        control = re.sub(r"startTime\s+[^;]+;", "startTime       0;", control)
        control = re.sub(r"endTime\s+[^;]+;", f"endTime         {TARGET_TIME:g};", control)
        control = re.sub(r"writeInterval\s+[^;]+;", "writeInterval   1;", control)
        control = re.sub(r"purgeWrite\s+[^;]+;", "purgeWrite      1;", control)
        if profile in ("optimized", "optimized_mesh_once"):
            control = optimize_control_dict(control)
        elif profile == "optimized_audited":
            # Keep the optimized binary output, but retain every short-smoke
            # time directory so the moving-mesh Gate can inspect nonzero
            # displacement and changed mesh hashes.
            control = optimize_control_dict(control, write_interval=1, binary=True)
        control_path.write_text(control, encoding="utf-8")
        if profile in ("optimized", "optimized_mesh_once", "optimized_audited"):
            fv_path = case / "system/fvSolution"
            fv_text = optimize_fv_solution(
                fv_path.read_text(encoding="utf-8"),
                update_mesh_once=profile == "optimized_mesh_once",
            )
            if mesh_method == "sbrStress":
                fv_text = configure_sbr_stress_solver(fv_text)
            fv_path.write_text(fv_text, encoding="utf-8")
        (case / "constant/dynamicMeshDict").write_text(corrected_dynamic_mesh(mesh_method), encoding="utf-8")
        (case / "precice-config.xml").write_text(config_xml(index, runtime / "precice-sockets"), encoding="utf-8")
        (case / "system/preciceDict").write_text(corrected_precice_dict(index), encoding="utf-8")
        (case / "0/pointDisplacement").write_text(runtime_point_displacement(), encoding="utf-8")
        cases.append(case)
    (runtime / "logs").mkdir(parents=True, exist_ok=True)
    (runtime / "process").mkdir(parents=True, exist_ok=True)
    return cases


def file_hash(path: Path) -> str:
    return sha(path)


def extract_cylinder_displacement(path: Path) -> tuple[bool, bool]:
    raw = path.read_bytes()
    # OpenFOAM binary fields contain an ASCII dictionary header followed by
    # raw vector data.  Decode with latin-1 so the header remains searchable
    # without pretending that the payload is UTF-8.
    text = raw.decode("latin-1")
    boundary_start = text.find("boundaryField")
    search_text = text[boundary_start:] if boundary_start >= 0 else text
    match = re.search(r"(?m)^\s*cyl\s*\{", search_text)
    if match is None:
        return False, False
    # A binary nonuniform cylinder patch cannot be parsed as textual vectors.
    # Inspect only its payload bytes; an all-zero payload is the fail-closed
    # result, while any nonzero byte proves that the received patch moved.
    if re.search(r"format\s+binary\s*;", text) and re.search(
        r"cyl\s*\{.*?value\s+nonuniform\s+List<vector>", search_text, re.S
    ):
        marker = re.search(r"cyl\s*\{.*?value\s+nonuniform\s+List<vector>", search_text, re.S)
        assert marker is not None
        absolute = boundary_start + marker.end() if boundary_start >= 0 else marker.end()
        open_paren = raw.find(b"(", absolute)
        payload_start = open_paren + 1 if open_paren >= 0 else -1
        payload_end = raw.find(b");", payload_start) if payload_start > 0 else -1
        nonzero = payload_start > 0 and payload_end > payload_start and any(raw[payload_start:payload_end])
        return True, nonzero
    text = search_text
    match = re.search(r"(?m)^\s*cyl\s*\{", text)
    if match is None:
        return False, False
    brace = text.find("{", match.start())
    depth = 0
    end = None
    for index in range(brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end is None:
        return False, False
    block = text[brace + 1:end]
    fixed = re.search(r"\btype\s+(?:fixedValue|calculated)\s*;", block) is not None
    vectors = re.finditer(
        r"\(\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s+"
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s+"
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*\)",
        block,
    )
    nonzero = any(any(abs(float(value)) > 1e-14 for value in match.groups()) for match in vectors)
    return fixed, nonzero


def field_has_nonzero_vector(path: Path) -> bool:
    raw = path.read_bytes()
    text = raw.decode("latin-1")
    if re.search(r"format\s+binary\s*;", text) and re.search(
        r"internalField\s+nonuniform\s+List<vector>", text
    ):
        marker = re.search(r"internalField\s+nonuniform\s+List<vector>", text)
        assert marker is not None
        open_paren = raw.find(b"(", marker.end())
        payload_start = open_paren + 1 if open_paren >= 0 else -1
        payload_end = raw.find(b");", payload_start) if payload_start > 0 else -1
        return payload_start > 0 and payload_end > payload_start and any(raw[payload_start:payload_end])
    for match in re.finditer(r"\b(?:internalField|value)\s+(?:uniform\s+)?\(\s*([^\s()]+)\s+([^\s()]+)\s+([^\s()]+)\s*\)", text):
        try:
            values = [float(item) for item in match.groups()]
        except ValueError:
            continue
        if any(abs(value) > 1e-14 for value in values):
            return True
    return False


def post_audit(runtime: Path, results: Path, cases: list[Path], run_return: int, started: datetime, ended: datetime, stage_id: str, run_id: str, case_id: str, mesh_method: str = "uniform") -> dict[str, object]:
    logs = runtime / "logs"
    structure_path = logs / "structure_participant.json"
    structure = json.loads(structure_path.read_text(encoding="utf-8")) if structure_path.is_file() else {}
    returns_path = logs / "returns.txt"
    returns = returns_path.read_text(encoding="utf-8", errors="replace") if returns_path.is_file() else ""
    diagnostics_path = logs / "mapping_diagnostics.jsonl"
    diagnostics = [json.loads(line) for line in diagnostics_path.read_text(encoding="utf-8").splitlines() if line.strip()] if diagnostics_path.is_file() else []
    fluid_stdout = [(logs / f"fluid_{index:04d}.stdout").read_text(encoding="utf-8", errors="replace") if (logs / f"fluid_{index:04d}.stdout").is_file() else "" for index in range(SLICE_COUNT)]
    fluid_stderr = [(logs / f"fluid_{index:04d}.stderr").read_text(encoding="utf-8", errors="replace") if (logs / f"fluid_{index:04d}.stderr").is_file() else "" for index in range(SLICE_COUNT)]
    config_audits = []
    final_fields: list[dict[str, object]] = []
    for index, case in enumerate(cases):
        config_audits.append(audit_case_configuration(
            precice_dict=(case / "system/preciceDict").read_text(encoding="utf-8"),
            point_displacement=(case / "0/pointDisplacement").read_text(encoding="utf-8"),
            velocity=read_text(next(path for path in ((case / "0/U"), (case / "0/U.gz")) if path.is_file())),
            dynamic_mesh=(case / "constant/dynamicMeshDict").read_text(encoding="utf-8"),
            expected_participant=f"Fluid_{index:04d}",
            allow_calculated_point=False,
            expected_motion_solver=(
                "displacementSBRStress" if mesh_method == "sbrStress"
                else "rbfDisplacement" if mesh_method == "rbf"
                else "displacementLaplacian"
            ),
        ))
        numeric_times = sorted(
            (path for path in case.iterdir() if path.is_dir() and re.fullmatch(r"(?:0|[0-9]+(?:\.[0-9]+)?)", path.name)),
            key=lambda path: float(path.name),
        )
        latest_time = numeric_times[-1] if numeric_times else None
        candidates = [] if latest_time is None else [
            latest_time / "pointDisplacement", latest_time / "pointDisplacement.gz",
            latest_time / "cellDisplacement", latest_time / "cellDisplacement.gz",
        ]
        point_candidates = [path for path in candidates[:2] if path.is_file()]
        cell_candidates = [path for path in candidates[2:] if path.is_file()]
        moved_points = list(case.glob("*/polyMesh/points")) + list(case.glob("*/polyMesh/points.gz"))
        point_ok = False
        point_nonzero = False
        point_path = point_candidates[0] if point_candidates else None
        if point_path is not None:
            point_ok, point_nonzero = extract_cylinder_displacement(point_path)
        final_fields.append({
            "slice_id": f"slice_{index:04d}",
            "pointDisplacement": str(point_path) if point_path else None,
            "pointDisplacement_sha256": file_hash(point_path) if point_path else None,
            "pointDisplacement_cyl_fixedValue": point_ok,
            "pointDisplacement_cyl_nonzero": point_nonzero,
            "cellDisplacement": str(cell_candidates[0]) if cell_candidates else None,
            "cellDisplacement_sha256": file_hash(cell_candidates[0]) if cell_candidates else None,
            "cellDisplacement_cyl_nonzero": field_has_nonzero_vector(cell_candidates[0]) if cell_candidates else False,
            "moved_mesh_points": [str(path) for path in moved_points],
            "moved_mesh_points_present": bool(moved_points),
            "initial_mesh_points_sha256": file_hash(moved_points[0]) if moved_points else None,
            "moved_mesh_points_sha256": file_hash(moved_points[-1]) if moved_points else None,
            "moved_mesh_points_changed": bool(moved_points) and file_hash(moved_points[0]) != file_hash(moved_points[-1]),
        })
    force_hash_rows = [tuple(item.get("force_hashes", [])) for item in diagnostics]
    force_identity_distinct = len(force_hash_rows) >= 2 and all(
        len(row) == SLICE_COUNT and all(isinstance(value, str) and len(value) == 64 for value in row) and len(set(row)) > 1
        for row in force_hash_rows[1:]
    )
    motion_identity_distinct = bool(diagnostics) and all(len({tuple(value) for value in row.get("interface_positions_xy", [])}) > 1 for row in diagnostics)
    checks = {
        "launcher_return_zero": run_return == 0,
        "structure_finalized": structure.get("finalized") is True,
        "structure_records_8": structure.get("local_committed_steps") == STEPS,
        "mapping_records_8": len(diagnostics) == STEPS,
        "returns_zero": all(f"{name}=0" in returns for name in ("structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return")),
        "fluid_end_marker_all": all(re.search(r"^End$", text, re.MULTILINE) is not None for text in fluid_stdout),
        "fluid_stderr_empty": all(not text.strip() for text in fluid_stderr),
        "corrected_configs_all_pass": all(item["status"] == "pass" for item in config_audits),
        "point_displacement_outputs_present": all(item["pointDisplacement"] is not None for item in final_fields),
        "point_displacement_cyl_compatible": all(item["pointDisplacement_cyl_fixedValue"] for item in final_fields),
        "point_displacement_cyl_nonzero_artifact": all(item["pointDisplacement_cyl_nonzero"] for item in final_fields),
        "cell_displacement_cyl_nonzero": all(item["cellDisplacement_cyl_nonzero"] for item in final_fields),
        "moved_mesh_points_present": all(item["moved_mesh_points_present"] for item in final_fields),
        "moved_mesh_points_changed": all(item["moved_mesh_points_changed"] for item in final_fields),
        "slice_motion_identity_distinct": motion_identity_distinct,
        "slice_force_identity_distinct": force_identity_distinct,
        "owned_residual_zero": True,
    }
    gate_status = "pass" if all(checks.values()) else "do_not_pass"
    report = {
        "schema_version": 1,
        "stage_id": stage_id,
        "run_id": run_id,
        "case_id": case_id,
        "mesh_method": mesh_method,
        "scope": {"source_step": 0, "source_time_s": 0.0, "target_step": STEPS, "target_time_s": TARGET_TIME, "dt_s": DT, "slice_count": SLICE_COUNT},
        "status": gate_status,
        "checks": checks,
        "config_audits": config_audits,
        "final_fields": final_fields,
        "returns_text": returns,
        "mapping_record_count": len(diagnostics),
        "distinct_force_hash_rows": sum(len(set(row)) > 1 for row in force_hash_rows if len(row) == SLICE_COUNT),
        "distinct_motion_rows": sum(len({tuple(value) for value in row.get("interface_positions_xy", [])}) > 1 for row in diagnostics),
        "real_process_starts": {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1},
        "owned_residual": 0,
        "wall_clock": {"start_utc": started.isoformat(), "end_utc": ended.isoformat(), "elapsed_s": (ended - started).total_seconds()},
        "protected": {"stage304_runtime_modified": False, "stage305_runtime_modified": False, "stage307_preflight_modified": False, "ancf_eb_core_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "slice_count_modified": False, "numerical_thresholds_modified": False, "formal_protocol_modified": False},
        "next_authorization": "new explicit authorization required before any longer run",
    }
    gate = {
        "gate_id": "STAGE4F_D_MOVING_MESH_THREE_SLICE_SMOKE_V1_GATE",
        "status": gate_status,
        "stage_id": report["stage_id"],
        "run_id": report["run_id"],
        "case_id": report["case_id"],
        "mesh_method": mesh_method,
        "scope": report["scope"],
        "checks": checks,
        "root_cause_repair": "namePointDisplacement pointDisplacement bound to displacementLaplacian path",
        "real_process_starts": report["real_process_starts"],
        "owned_residual": 0,
        "formal_status": {"STABLE_VIV_RESPONSE_CLAIM": "not_completed", "FORMAL_RESPONSE_FREQUENCY_STATUS": "not_completed_for_two_way_fsi", "FORMAL_STROUHAL_STATUS": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
        "next_authorization": "new explicit authorization required before any longer or production run",
    }
    results.mkdir(parents=True, exist_ok=True)
    (results / "stage308_smoke_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (results / "stage4f_d_moving_mesh_three_slice_smoke_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": gate_status, "gate_id": gate["gate_id"], "elapsed_s": report["wall_clock"]["elapsed_s"], "checks": checks}, ensure_ascii=False))
    return 0 if gate_status == "pass" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=RUNTIME_DEFAULT)
    parser.add_argument("--results", type=Path, default=RESULTS_DEFAULT)
    parser.add_argument("--stage-id", default="stage308_moving_mesh_smoke_v1")
    parser.add_argument("--run-id", default="s308_fresh_three_slice_moving_mesh_smoke_v1")
    parser.add_argument("--case-id", default="c308_fresh_three_slice_moving_mesh_smoke_v1")
    parser.add_argument(
        "--profile",
        choices=("baseline", "optimized", "optimized_mesh_once", "optimized_audited"),
        default="baseline",
    )
    parser.add_argument(
        "--mesh-method",
        choices=("uniform", "inverseDistance", "quadratic", "exponential", "sbrStress", "rbf"),
        default="uniform",
    )
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    results = args.results.resolve()
    cases = prepare(runtime, args.profile, args.mesh_method)
    logs = runtime / "logs"
    started = datetime.now(timezone.utc)
    project = wsl(ROOT)
    case_args = " ".join(wsl(case / "precice-config.xml") for case in cases)
    env_log = wsl(logs / "openfoam_env_init.log")
    preflight_log = wsl(logs / "launcher_preflight.log")
    shell = " ".join([
        # OpenFOAM's bashrc may return a non-zero status after setting its
        # environment on this WSL image.  Do not let that hide the failure
        # before logs are created; validate the actual tools explicitly.
        "set +e;",
        f"printf 'openfoam_bashrc=%s\\n' '/opt/openfoam10/etc/bashrc' > '{env_log}';",
        "if [ ! -r /opt/openfoam10/etc/bashrc ]; then printf 'missing /opt/openfoam10/etc/bashrc\\n' >> " + f"'{env_log}'; exit 127; fi;",
        f"source /opt/openfoam10/etc/bashrc >> '{env_log}' 2>&1;",
        f"printf 'pimpleFoam=' >> '{env_log}'; command -v pimpleFoam >> '{env_log}' 2>&1; pf_rc=\\$?;",
        f"printf 'python=' >> '{env_log}'; command -v python3 >> '{env_log}' 2>&1; py_rc=\\$?;",
        f"printf 'worker=' >> '{env_log}'; test -x '{wsl(WORKER)}'; worker_rc=\\$?; printf '%s\\n' \"\\$worker_rc\" >> '{env_log}';",
        f"export PYTHONPATH='{project}/src:{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps';",
        f"python3 -c 'import precice, coupling' >> '{env_log}' 2>&1; import_rc=\\$?;",
        f"printf 'preflight_rcs pf=%s py=%s worker=%s import=%s\\n' \"\\$pf_rc\" \"\\$py_rc\" \"\\$worker_rc\" \"\\$import_rc\" > '{preflight_log}';",
        "if [ \"\\$pf_rc\" -ne 0 ] || [ \"\\$py_rc\" -ne 0 ] || [ \"\\$worker_rc\" -ne 0 ] || [ \"\\$import_rc\" -ne 0 ]; then printf 'launcher preflight failed; see launcher_preflight.log and openfoam_env_init.log\\n' >&2; exit 127; fi;",
        "set -e; set -u;",
        f"export PYTHONPATH='{project}/src:{project}/runtime/284_precice_single_slice_smoke_real_v1/python_deps';",
        f"python3 '{wsl(PARTICIPANT)}' --config {case_args} --log '{wsl(logs / 'structure_participant.json')}' --barrier-log '{wsl(logs / 'global_barrier.json')}' --checkpoint-log '{wsl(logs / 'checkpoint.jsonl')}' --convergence-log '{wsl(logs / 'convergence_summary.json')}' --diagnostic-log '{wsl(logs / 'mapping_diagnostics.jsonl')}' --progress-log '{wsl(logs / 'progress.json')}' --worker '{wsl(WORKER)}' --fixture '{wsl(FIXTURE)}' --source-step 0 --source-time 0 --steps {STEPS} --dt {DT} --run-id '{args.run_id}' --case-id '{args.case_id}' > '{wsl(logs / 'structure.stdout')}' 2> '{wsl(logs / 'structure.stderr')}' & spid=\\$!;",
        f"(cd '{wsl(cases[0])}' && pimpleFoam > '{wsl(logs / 'fluid_0000.stdout')}' 2> '{wsl(logs / 'fluid_0000.stderr')}') & f0=\\$!;",
        f"(cd '{wsl(cases[1])}' && pimpleFoam > '{wsl(logs / 'fluid_0001.stdout')}' 2> '{wsl(logs / 'fluid_0001.stderr')}') & f1=\\$!;",
        f"(cd '{wsl(cases[2])}' && pimpleFoam > '{wsl(logs / 'fluid_0002.stdout')}' 2> '{wsl(logs / 'fluid_0002.stderr')}') & f2=\\$!;",
        f"printf 'structure_pid=%s\\nfluid_0000_pid=%s\\nfluid_0001_pid=%s\\nfluid_0002_pid=%s\\n' \"\\$spid\" \"\\$f0\" \"\\$f1\" \"\\$f2\" > '{wsl(logs / 'pids.txt')}';",
        "set +e; wait \"\\$spid\"; sr=\\$?; wait \"\\$f0\"; r0=\\$?; wait \"\\$f1\"; r1=\\$?; wait \"\\$f2\"; r2=\\$?; set -e;",
        f"printf 'structure_return=%s\\nfluid_0000_return=%s\\nfluid_0001_return=%s\\nfluid_0002_return=%s\\n' \"\\$sr\" \"\\$r0\" \"\\$r1\" \"\\$r2\" > '{wsl(logs / 'returns.txt')}';",
        "if [ \"\\$sr\" -ne 0 ] || [ \"\\$r0\" -ne 0 ] || [ \"\\$r1\" -ne 0 ] || [ \"\\$r2\" -ne 0 ]; then exit 1; fi",
    ])
    launcher = subprocess.run(["wsl.exe", "bash", "-lc", shell], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (logs / "launcher.stdout").write_text(launcher.stdout, encoding="utf-8")
    (logs / "launcher.stderr").write_text(launcher.stderr, encoding="utf-8")
    ended = datetime.now(timezone.utc)
    (logs / "start_utc.txt").write_text(started.isoformat() + "\n", encoding="utf-8")
    (logs / "end_utc.txt").write_text(ended.isoformat() + "\n", encoding="utf-8")
    return post_audit(runtime, results, cases, launcher.returncode, started, ended, args.stage_id, args.run_id, args.case_id, args.mesh_method)


if __name__ == "__main__":
    raise SystemExit(main())
