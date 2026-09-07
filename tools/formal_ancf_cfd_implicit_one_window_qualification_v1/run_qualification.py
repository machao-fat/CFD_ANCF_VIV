"""One and only one formal three-slice ANCF--CFD implicit window.

This launcher deliberately inherits frozen physics and numerics, but binds all
Fluid participants to the source-pinned patch-0005 diagnostic library by an
absolute path.  It never launches a second window.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
from coupling.moving_mesh_openfoam10_case_contract_v1 import preflight as case_preflight
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log
from coupling.ancf_newton_evidence_v1 import validate_records
from coupling.precice_path_v1 import canonical_wsl_path, socket_directory_preflight


RUN = os.environ.get(
    "FORMAL_IMPLICIT_RUN_ID",
    "formal_implicit_initial_data_and_socket_path_fix_v1_run_001",
)
RUNTIME, RESULTS = ROOT / "runtime" / RUN, ROOT / "results" / RUN
PARTICIPANT = ROOT / "tools" / "checkpoint_aware_structure_participant_and_one_window_implicit_qualification_v1" / "implicit_structure_participant.py"
WORKER = ROOT / "runtime" / "parallel_implicit_coupling_readiness_and_0p05s_diagnostic_v1" / "cpp_worker_build" / "cfd_ancf_ancf_kernel_worker"
QUALITY_V4 = ROOT / "tools" / "parallel_explicit_fsi_timestep_stability_diagnostic_v1" / "openfoam_quality_contract_v4.json"
INITIAL_DATA_REGRESSION = ROOT / "results" / "formal_implicit_projected_initial_state_guard_closure_v1_regression_002" / "initial_data_and_path_regression.json"
LIB_WSL = "/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_006/lib"
LIB_FILE = Path(LIB_WSL) / "libpreciceAdapterFunctionObject.so"
UPSTREAM = "d53753b1c927b2413b02299c9da15725b3e772f0"
PATCH_SET = ["0001-respect-adapter-target-dir", "0002-diagnostic-rollback-fingerprints", "0004-registry-safe-rollback-and-motion-timing", "0005-precice-time-layer-and-different-input-rollback"]
DT = 0.005


def sha256(path: Path) -> str:
    if path.as_posix().startswith("/") and os.name == "nt":
        completed = subprocess.run(
            ["wsl.exe", "-d", "Ubuntu-22.04", "--", "sha256sum", path.as_posix()],
            check=True, text=True, encoding="utf-8", errors="replace", capture_output=True,
        )
        return completed.stdout.split()[0]
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linux_file_exists(path: Path) -> bool:
    if path.as_posix().startswith("/") and os.name == "nt":
        return subprocess.run(
            ["wsl.exe", "-d", "Ubuntu-22.04", "--", "test", "-f", path.as_posix()],
            capture_output=True,
        ).returncode == 0
    return path.is_file()


def linux_realpath(path: Path) -> str:
    if path.as_posix().startswith("/") and os.name == "nt":
        completed = subprocess.run(
            ["wsl.exe", "-d", "Ubuntu-22.04", "--", "realpath", path.as_posix()],
            check=True, text=True, encoding="utf-8", errors="replace", capture_output=True,
        )
        return completed.stdout.strip()
    return str(path.resolve())


def wsl_process(command: list[str], **kwargs):
    if os.name == "nt":
        command = ["wsl.exe", "-d", "Ubuntu-22.04", "--", *command]
    return subprocess.run(command, **kwargs)


def put(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    # The host-side launcher also supports the pinned Python 3.9 runtime,
    # whose Path.write_text() has no newline= keyword.  Explicitly retain LF
    # because this file is executed by bash inside WSL.
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def wsl(path: Path) -> str:
    return canonical_wsl_path(path)


def implicit_xml(base, sid: int) -> str:
    original = base.xml(sid)
    replacement = (
        f'<coupling-scheme:parallel-implicit><participants first="Structure_{sid:04d}" second="Fluid_{sid:04d}"/>'
        '<max-time value="0.005"/><time-window-size value="0.005"/><min-iterations value="2"/><max-iterations value="8"/>'
        '<absolute-or-relative-convergence-measure data="Displacement" mesh="Structure-Mesh" abs-limit="1e-8" rel-limit="1e-5"/>'
        '<absolute-or-relative-convergence-measure data="Force" mesh="Structure-Mesh" abs-limit="1e-3" rel-limit="1e-5"/>'
        f'<exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{sid:04d}" to="Fluid_{sid:04d}" initialize="yes" substeps="false"/>'
        f'<exchange data="Force" mesh="Structure-Mesh" from="Fluid_{sid:04d}" to="Structure_{sid:04d}" substeps="false"/>'
        '</coupling-scheme:parallel-implicit>'
    )
    return re.sub(r'<coupling-scheme:parallel-explicit>.*?</coupling-scheme:parallel-explicit>', replacement, original, flags=re.S)


def control(base) -> str:
    text = base.CONTROL.replace(
        "startFrom startTime; startTime 0; stopAt endTime; endTime 1;",
        "startFrom startTime; startTime 0.1; stopAt endTime; endTime 0.105;",
    )
    return text.replace('libs ("libpreciceAdapterFunctionObject.so");', f'libs ("{LIB_WSL}/libpreciceAdapterFunctionObject.so");')


def structure_contract(original: dict) -> dict:
    contract = dict(original)
    contract.update({
        "schema_version": "formal-ancf-cfd-implicit-one-window-qualification-v1",
        "run_id": RUN,
        "case_id": "formal_ancf_cfd_implicit_one_window_qualification_v1_case_001",
        "duration_s": DT,
        "dt_s": DT,
        "number_of_steps": 1,
        "openfoam_physical_time_offset_s": 0.1,
        "coupling_scheme": "parallel-implicit",
        "initial_structure_state": "NO_FLOW_EQUILIBRIUM",
        "implicit_convergence": {
            "min_iterations": 2,
            "max_iterations": 8,
            "acceleration": "none",
            "measures": [
                {"data": "Displacement", "mesh": "Structure-Mesh", "abs_limit": 1e-8, "rel_limit": 1e-5},
                {"data": "Force", "mesh": "Structure-Mesh", "abs_limit": 1e-3, "rel_limit": 1e-5},
            ],
        },
        "openfoam_quality_v4": {"path": str(QUALITY_V4), "sha256": sha256(QUALITY_V4)},
        "adapter": {"library_wsl": LIB_WSL, "sha256": sha256(LIB_FILE), "upstream_commit": UPSTREAM, "patch_set": PATCH_SET},
        "time_layer": {"initial_read_relative_time_s": 0.0, "post_advance_retry_read": "getMaxTimeStepSize()", "openfoam_time_relation": "t_OF=0.100 s+tau"},
        "containment": "ARMED_BY_FROZEN_REGRESSION",
        "scope": "exactly one coupled physical window; no automatic continuation",
    })
    return contract


def prepare():
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to overwrite immutable formal runtime")
    if not linux_file_exists(LIB_FILE):
        raise RuntimeError("patch-0005 adapter library is absent")
    if not INITIAL_DATA_REGRESSION.is_file():
        raise RuntimeError("projected initial-data regression evidence is absent")
    initial_data_regression = json.loads(INITIAL_DATA_REGRESSION.read_text(encoding="utf-8"))
    projected = initial_data_regression.get("projected_initial_state_guard", {})
    if (initial_data_regression.get("INITIAL_DATA_PROTOCOL") != "PASS" or
            initial_data_regression.get("SOCKET_PATH_CANONICALIZATION") != "PASS" or
            projected.get("status") != "PASS"):
        raise RuntimeError("projected initial-data/socket preflight fails")
    smoke = load(ROOT / "tools" / "preconditioned_coupled_0p1s_smoke_v1" / "run_smoke.py", "formal_implicit_preconditioned")
    original = smoke.contract
    smoke.RUN, smoke.RUNTIME, smoke.RESULTS = RUN, RUNTIME, RESULTS
    smoke.HERE, smoke.STEPS, smoke.DT, smoke.QUALITY = HERE, 1, DT, QUALITY_V4
    smoke.contract = lambda: structure_contract(original())
    smoke.cfg_xml = implicit_xml
    smoke.control = control
    base, cases, contract = smoke.prepare()
    base.PARTICIPANT_SCRIPT, base.WORKER = PARTICIPANT, WORKER
    socket_preflight = socket_directory_preflight(RUNTIME / "precice-sockets")
    if socket_preflight["status"] != "PASS":
        raise RuntimeError("preCICE socket directory preflight fails")
    preflight = {str(sid): case_preflight(case, "0.1") for sid, case in enumerate(cases)}
    if not all(item.get("MOVING_MESH_CASE_PREFLIGHT") == "PASS" for item in preflight.values()):
        raise RuntimeError("moving-mesh production preflight fails")
    adapter_manifest = {
        "realpath": linux_realpath(LIB_FILE),
        "sha256": sha256(LIB_FILE),
        "upstream_commit": UPSTREAM,
        "patch_set": PATCH_SET,
        "OpenFOAM": "Foundation 10 /opt/openfoam10 linux64GccDPInt32Opt",
        "preCICE": "3.4.1",
        "socket_directory": socket_preflight,
        "fluid_cases": {str(sid): {"controlDict_adapter_library": LIB_WSL + "/libpreciceAdapterFunctionObject.so", "preflight": preflight[str(sid)]} for sid in range(3)},
    }
    put(RUNTIME / "adapter_manifest.json", adapter_manifest)
    put(RESULTS / "production_preflight.json", {
        "projected_initial_data_regression": {
            "path": str(INITIAL_DATA_REGRESSION),
            "sha256": sha256(INITIAL_DATA_REGRESSION),
            "initial_data_protocol": initial_data_regression["INITIAL_DATA_PROTOCOL"],
            "socket_path_canonicalization": initial_data_regression["SOCKET_PATH_CANONICALIZATION"],
            "projected_initial_state_guard": projected.get("status"),
        },
        "adapter_manifest": adapter_manifest,
        "precursor_transfer": json.loads((RESULTS / "preflight.json").read_text(encoding="utf-8")),
        "quality_v4_sha256": sha256(QUALITY_V4),
        "generalized_force_metric_v2": contract["generalized_force_metric_v2"],
        "structure_participant": {"path": str(PARTICIPANT), "sha256": sha256(PARTICIPANT), "checkpoint_schema": "structure-participant-checkpoint-schema-v1", "prior_rollback_regression": "PASS (immutable run_003)", "wire_identity": "monotonic/non-restorable PASS (frozen regression)", "time_layer_contract": "PASS (frozen contract)", "realtime_containment": "PASS (frozen regression)"},
    })
    return base, cases, contract


def launch(base, cases: list[Path]) -> int:
    logs = RUNTIME / "logs"
    configs = " ".join("'" + wsl(case / "precice-config.xml") + "'" for case in cases)
    fluid = []
    for sid, case in enumerate(cases):
        trace = wsl(RUNTIME / f"fluid_{sid:04d}_adapter_trace.jsonl")
        command = (
            f"(cd '{wsl(case)}' && PRECICE_ADAPTER_ROLLBACK_DIAGNOSTICS_PATH='{trace}' "
            f"PRECICE_ADAPTER_BUILD_SHA256='{sha256(LIB_FILE)}' pimpleFoam > '{wsl(logs / f'fluid_{sid:04d}.stdout')}' "
            f"2> '{wsl(logs / f'fluid_{sid:04d}.stderr')}') & p{sid}=$!"
        )
        fluid.append(command)
    script = [
        "set -o pipefail", "export ZSH_NAME=", "source /opt/openfoam10/etc/bashrc",
        f"export LD_LIBRARY_PATH='{LIB_WSL}':$LD_LIBRARY_PATH",
        f"export PYTHONPATH='{wsl(ROOT)}/src:{wsl(base.PYDEPS)}'",
        f"python3 '{wsl(PARTICIPANT)}' --contract '{wsl(RUNTIME / base.CONTRACT.name)}' --state '{wsl(base.STATE)}' --worker '{wsl(WORKER)}' --runtime '{wsl(RUNTIME)}' --config {configs} --vertex-count 40 > '{wsl(logs / 'structure.stdout')}' 2> '{wsl(logs / 'structure.stderr')}' & spid=$!",
        *fluid,
        "wait \"$spid\"; sr=$?; if [ \"$sr\" -ne 0 ]; then kill \"$p0\" \"$p1\" \"$p2\" 2>/dev/null || true; fi",
        "wait \"$p0\"; r0=$?; wait \"$p1\"; r1=$?; wait \"$p2\"; r2=$?",
        f"printf 'structure_return=%s\\nfluid_0000_return=%s\\nfluid_0001_return=%s\\nfluid_0002_return=%s\\n' \"$sr\" \"$r0\" \"$r1\" \"$r2\" > '{wsl(logs / 'returns.txt')}'",
        "[ \"$sr\" -eq 0 ] && [ \"$r0\" -eq 0 ] && [ \"$r1\" -eq 0 ] && [ \"$r2\" -eq 0 ]",
    ]
    launch_file = RUNTIME / "launch.sh"
    put(launch_file, "\n".join(script) + "\n")
    result = wsl_process(["bash", wsl(launch_file)], cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=900)
    put(logs / "launcher.stdout", result.stdout); put(logs / "launcher.stderr", result.stderr)
    return result.returncode


def parse_force(path: Path):
    rows = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line and not line.startswith("#")]
    if not rows:
        return None
    values = [float(x) for x in re.findall(r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", rows[-1])]
    return {"pressure_Fx_N": values[1], "pressure_Fy_N": values[2], "viscous_Fx_N": values[4], "viscous_Fy_N": values[5], "total_Fx_N": values[1] + values[4], "total_Fy_N": values[2] + values[5]}


def trace_rows(sid: int):
    path = RUNTIME / f"fluid_{sid:04d}_adapter_trace.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []


def persistent_equal(a: dict, b: dict, name: str) -> bool:
    return a["states"][name].get("canonical_hash_fnv1a64") == b["states"][name].get("canonical_hash_fnv1a64")


def audit(cases: list[Path], return_code: int) -> dict:
    quality_module = load(ROOT / "tools" / "parallel_explicit_fsi_timestep_stability_diagnostic_v1" / "quality_v4.py", "formal_quality_v4")
    quality_contract = json.loads(QUALITY_V4.read_text(encoding="utf-8"))
    summary_path = RUNTIME / "structure_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
    iterations = [json.loads(line) for line in (RUNTIME / "implicit_iterations.jsonl").read_text(encoding="utf-8").splitlines()] if (RUNTIME / "implicit_iterations.jsonl").is_file() else []
    records = [json.loads(line) for line in (RUNTIME / "records.jsonl").read_text(encoding="utf-8").splitlines()] if (RUNTIME / "records.jsonl").is_file() else []
    newton = [json.loads(line) for line in (RUNTIME / "newton_evidence.jsonl").read_text(encoding="utf-8").splitlines()] if (RUNTIME / "newton_evidence.jsonl").is_file() else []
    traces, rollback = {}, {}
    for sid, case in enumerate(cases):
        trace = trace_rows(sid); traces[str(sid)] = trace
        by_event = {}
        for row in trace: by_event.setdefault(row.get("event"), []).append(row)
        checkpoint = by_event.get("CHECKPOINT_WRITE", [None])[0]
        restored = by_event.get("POST_ROLLBACK_BEFORE_NEXT_INPUT", [])
        persistent = ("U", "p", "phi", "Uf", "cellDisplacement", "mesh_points")
        field_ok = bool(checkpoint and restored) and all(all(persistent_equal(checkpoint, item, name) for name in persistent) and checkpoint["physical_time"] == item["physical_time"] and checkpoint["time_index"] == item["time_index"] for item in restored)
        mesh_ok = bool(checkpoint and restored) and all(persistent_equal(checkpoint, item, "mesh_points") for item in restored)
        derived_ok = bool(checkpoint and restored) and all(item["states"]["meshPhi"]["classification"] in ("PERSISTENT_RESTORED", "NOT_OBSERVABLE_NOT_REGISTERED") for item in restored)
        rollback[str(sid)] = {"events": [row.get("event") for row in trace], "field_identity": field_ok, "mesh_identity": mesh_ok, "derived_history": derived_ok, "checkpoint": checkpoint, "restores": restored}
    quality = {}
    for sid, case in enumerate(cases):
        try:
            parsed = audit_log(RUNTIME / "logs" / f"fluid_{sid:04d}.stdout", case / "system" / "fvSolution")
            quality[str(sid)] = quality_module.evaluate_quality_v4(parsed, quality_contract)
        except Exception as exc:
            # A pre-solve failure is a failed Quality V4 gate, not a reason to
            # discard the immutable runtime's first-blocker evidence.
            quality[str(sid)] = {"status": "fail", "error": f"{type(exc).__name__}: {exc}"}
    forces = []
    for case in cases:
        files = list(case.glob("postProcessing/cylinderForces/*/forces.dat"))
        forces.append(parse_force(files[0]) if len(files) == 1 else None)
    final_loads = records[0]["loads"] if len(records) == 1 else []
    v2 = [row for row in iterations if row.get("event") == "post_cpp_correction"]
    restores = [row for row in iterations if row.get("event") == "checkpoint_restore"]
    wires = [row.get("wire_sequence") for row in v2]
    try:
        newton_ok = validate_records(newton, expected_steps=1).get("status") == "pass"
    except Exception:
        newton_ok = False
    max_ux, max_vx = [], []
    if records:
        for motion in records[0]["motion"]:
            max_ux.append(abs(float(motion["ux_m"]))); max_vx.append(abs(float(motion["vx_mps"])))
    checks = {
        "three_adapter_manifests": (RUNTIME / "adapter_manifest.json").is_file(),
        "return_codes": return_code == 0 and summary.get("status") == "completed",
        "structure_rollback": bool(restores) and all(row.get("checkpoint_state_sha256") == row.get("post_restore_state_sha256") for row in restores),
        "unique_wire_ids": len(wires) >= 2 and len(wires) == len(set(wires)),
        "fluid_field_history_rollback": all(item["field_identity"] and item["derived_history"] for item in rollback.values()),
        "dynamic_mesh_rollback": all(item["mesh_identity"] for item in rollback.values()),
        "two_to_eight_iterations": 2 <= int(summary.get("coupling_iterations", 0)) <= 8,
        "single_commit": len(records) == 1 and summary.get("committed_steps") == 1,
        "final_of_time": all(trace and abs(float(trace[-1].get("physical_time", math.inf)) - 0.105) <= 1e-12 for trace in traces.values()),
        "force_contract": len(final_loads) == 3 and all(abs(float(load["force_x_N"]) - float(load["force_2d_x_Npm"]) * float(load["slice_length_m"])) <= 1e-10 for load in final_loads),
        "generalized_force_v2": bool(v2) and all(row["generalized_force_metric_v2"]["GENERALIZED_FORCE_MAPPING_V2"] == "PASS" for row in v2),
        "newton": newton_ok,
        "quality_v4": all(item["status"] == "pass" for item in quality.values()),
        "no_fpe": return_code == 0,
        "forces_available": all(force is not None for force in forces),
    }
    result = {
        "FORMAL_IMPLICIT_ONE_WINDOW": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks, "return_code": return_code, "adapter_manifest": json.loads((RUNTIME / "adapter_manifest.json").read_text(encoding="utf-8")),
        "structure_summary": summary, "iteration_count": summary.get("coupling_iterations"), "iteration_evidence": iterations,
        "fluid_rollback": rollback, "quality_v4": quality, "final_raw_force": forces, "integrated_structural_force": final_loads,
        "max_abs_ux_m": max_ux, "max_abs_vx_mps": max_vx,
        "first_blocker": next((name for name, value in checks.items() if not value), None),
    }
    put(RESULTS / "formal_one_window_gate.json", result)
    return result


def main() -> int:
    base, cases, _ = prepare()
    code = launch(base, cases)
    result = audit(cases, code)
    print(json.dumps({"gate": result["FORMAL_IMPLICIT_ONE_WINDOW"], "iterations": result["iteration_count"], "blocker": result["first_blocker"]}, ensure_ascii=False))
    return 0 if result["FORMAL_IMPLICIT_ONE_WINDOW"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
