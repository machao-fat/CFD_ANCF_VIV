"""Run the single, time-layer-corrected V2 non-zero motion bridge.

V1 deliberately remains immutable: it established that the old test
participant supplied the initial (0.105 s) value to the first CFD output
(0.110 s).  This V2 wrapper reuses its frozen case construction and binary
closure, changing only the *test participant's preCICE storage-layer
schedule*.  It does not phase-shift the physical motion formula or alter any
production CFD, adapter, OpenFOAM, mesh, or coupling implementation.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
V1_TOOL = ROOT / "tools" / "cfd_current_dynamic_nonzero_bridge_v1" / "run_bridge.py"
RUNTIME = ROOT / "runtime" / "cfd_current_dynamic_nonzero_bridge_v2_run_001"
RESULTS = ROOT / "results" / "cfd_current_dynamic_nonzero_bridge_v2_run_001"
V1_RUNTIME = ROOT / "runtime" / "cfd_current_dynamic_nonzero_bridge_v1_run_001"
V1_RESULTS = ROOT / "results" / "cfd_current_dynamic_nonzero_bridge_v1_run_001" / "bridge_result.json"


def load_v1() -> Any:
    spec = importlib.util.spec_from_file_location("bridge_v1", V1_TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load immutable V1 bridge tool: {V1_TOOL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load_v1()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def configure_base() -> None:
    """Reuse V1's case construction only after assigning independent paths."""
    base.RUNTIME = RUNTIME
    base.RESULTS = RESULTS
    base.participant_code = participant_code_v2


def participant_code_v2() -> str:
    # A parallel-explicit, non-subcycled exchange stores the initial sample
    # for the first fluid window.  The adapter reads it at initialize(0.0),
    # then after each fluid solve reads the next end-of-window sample using
    # relativeReadTime=maxDt.  Payload labels below record storage semantics
    # separately from the physical output time that consumes the sample.
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
step = 0
try:
    requested = participant.requires_initial_data()
    if not requested:
        raise RuntimeError("V2 requires the configured initial Displacement exchange")
    initial_target = plan[1]
    initial = payload(float(initial_target["y_m"]))
    participant.write_data("Structure-Mesh", "Displacement", mesh, initial)
    rows.append({"event":"INITIAL_DATA_FOR_FIRST_CFD_OUTPUT", "precice_storage_time_s":0.0, "payload_plan_step":1, "payload_motion_time_s":initial_target["time_s"], "expected_cfd_output_time_s":initial_target["time_s"], "y_m":initial_target["y_m"], "payload_sha256":digest(initial), "requested":requested})
    participant.initialize()
    while participant.is_coupling_ongoing():
        # V1's immutable trace proves a write before advance i is consumed by
        # the CFD output of window i+1.  The final duplicate is exchanged only
        # after output .605 and cannot affect a later CFD output.
        payload_step = min(step + 2, len(plan) - 1)
        target = plan[payload_step]
        values = payload(float(target["y_m"]))
        participant.write_data("Structure-Mesh", "Displacement", mesh, values)
        rows.append({"event":"WRITE_DISPLACEMENT_FOR_FUTURE_CFD_OUTPUT", "advance_index":step + 1, "precice_storage_time_before_advance_s":step * 0.005, "payload_plan_step":payload_step, "payload_motion_time_s":target["time_s"], "expected_cfd_output_time_s":target["time_s"] if step < len(plan) - 2 else None, "final_unconsumed_duplicate":step == len(plan) - 2, "y_m":target["y_m"], "sampled_vy_m_per_s":target["sampled_vy_m_per_s"], "payload_sha256":digest(values)})
        participant.advance(0.005)
        step += 1
        force = participant.read_data("Structure-Mesh", "Force", mesh, 0.0)
        force = force.tolist() if hasattr(force, "tolist") else force
        applied = plan[step]
        rows.append({"event":"READ_FORCE_AFTER_CFD_OUTPUT", "step":step, "cfd_output_time_s":applied["time_s"], "expected_applied_plan_step":step, "expected_applied_y_m":applied["y_m"], "force_sum_N":[sum(float(row[d]) for row in force) for d in range(2)], "force_payload_sha256":digest(force)})
finally:
    participant.finalize()
evidence_path.write_text(json.dumps({"schema_version":"nonzero-bridge-v2-participant-events", "steps":step, "rows":rows, "contains_ancf":False, "motion_source":"frozen bridgeMotionPlan.json", "time_contract":"CFD output t_n consumes y(t_n); preCICE storage labels are not physical-motion labels"}, indent=2) + "\n", encoding="utf-8")
'''


def preflight_mapping() -> dict[str, Any]:
    """Prove V2's event schedule from the immutable V1 observation."""
    if not V1_RESULTS.is_file() or not (V1_RUNTIME / "participant_evidence.json").is_file():
        raise RuntimeError("immutable V1 timing evidence is unavailable")
    v1_result = json.loads(V1_RESULTS.read_text(encoding="utf-8"))
    lags = v1_result.get("input_time_level", {}).get("adapter_input_lag_steps", [])
    v1_events = json.loads((V1_RUNTIME / "participant_evidence.json").read_text(encoding="utf-8"))
    initial = next((row for row in v1_events.get("rows", []) if row.get("event") == "INITIAL_DATA"), None)
    writes = [row for row in v1_events.get("rows", []) if row.get("event") == "WRITE_DISPLACEMENT_FOR_NEXT_CFD_STEP"]
    v1_proves = (
        len(lags) == base.STEPS and all(value == 1 for value in lags)
        and initial is not None and initial.get("for_physical_time_s") == base.START
        and len(writes) == base.STEPS and writes[0].get("step") == 1
    )
    plan = base.sampled_motion_plan()
    mapping = []
    for output_step in range(1, base.STEPS + 1):
        source = "INITIAL_DATA_FOR_FIRST_CFD_OUTPUT" if output_step == 1 else "WRITE_BEFORE_ADVANCE"
        writer_advance = None if output_step == 1 else output_step - 1
        mapping.append({
            "cfd_output_step": output_step,
            "cfd_output_time_s": plan[output_step]["time_s"],
            "required_plan_step": output_step,
            "required_y_m": plan[output_step]["y_m"],
            "storage_source": source,
            "writer_advance_index": writer_advance,
            "v2_payload_plan_step": output_step,
            "mapping_exact": True,
        })
    result = {
        "schema_version": "nonzero-bridge-v2-time-layer-preflight",
        "status": "PASS" if v1_proves and all(row["mapping_exact"] for row in mapping) else "FAIL_CLOSED",
        "coupling_scheme": "parallel-explicit, non-subcycled",
        "precice_version": "3.4.1 (from immutable V1 Fluid stdout)",
        "adapter_read_order": ["initialize: readCouplingData(0.0)", "after each completed CFD solve: readCouplingData(maxTimeStepSize)"],
        "immutable_v1_observation": {"uniform_lag_steps": lags, "initial_event": initial, "first_write_event": writes[0] if writes else None},
        "v2_contract": "CFD output t_n must apply frozen y(t_n), with no phase shift of the formula",
        "output_mapping": mapping,
        "final_post_output_exchange": {"advance_index": base.STEPS, "payload_plan_step": base.STEPS, "role": "required preCICE write after final CFD output; has no later CFD output to affect"},
    }
    return result


def abi_preflight() -> dict[str, Any]:
    """Record the exact V1-qualified independent ABI closure before CFD."""
    # Execute a real script file, exactly as V1's launcher does.  `bash -c`
    # is not equivalent here because the stock OF10 environment startup is
    # shell-path sensitive on this host.
    script = RUNTIME / "abi_preflight.sh"
    write(script, "\n".join((
        "set -o pipefail",
        "export ZSH_NAME=",
        f"source '{base.ENV_SCRIPT_WSL}' '{base.ABI_ROOT_WSL}'",
        f"export LD_LIBRARY_PATH='{base.ADAPTER_LIB_WSL}':$LD_LIBRARY_PATH",
        "pimple=$(command -v pimpleFoam)",
        "printf 'PIMPLE=%s\\n' \"$(readlink -f \"$pimple\")\"",
        f"printf 'ADAPTER=%s\\n' \"$(readlink -f '{base.ADAPTER_LIB_WSL}/libpreciceAdapterFunctionObject.so')\"",
        "printf 'PIMPLE_SHA256='; sha256sum \"$(readlink -f \"$pimple\")\"",
        f"printf 'ADAPTER_SHA256='; sha256sum '{base.ADAPTER_LIB_WSL}/libpreciceAdapterFunctionObject.so'",
        "printf '%s\\n' '--- LDD_PIMPLE ---'; ldd -r \"$(readlink -f \"$pimple\")\"",
        f"printf '%s\\n' '--- LDD_ADAPTER ---'; ldd -r '{base.ADAPTER_LIB_WSL}/libpreciceAdapterFunctionObject.so'",
        "",
    )))
    completed = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", base.wsl(script)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    closure = completed.stdout
    result = {
        "return_code": completed.returncode,
        "stdout": closure,
        "stderr": completed.stderr,
        "required_abi_root": base.ABI_ROOT_WSL,
        "required_adapter_root": base.ADAPTER_LIB_WSL,
        "no_opt_openfoam10": "/opt/openfoam10" not in closure,
        "no_undefined_symbol": "undefined symbol" not in closure.lower(),
    }
    result["status"] = "PASS" if (
        completed.returncode == 0 and result["no_opt_openfoam10"] and result["no_undefined_symbol"]
        and base.ABI_ROOT_WSL in closure and base.ADAPTER_LIB_WSL in closure
    ) else "FAIL_CLOSED"
    return result


def prepare_preflight() -> None:
    configure_base()
    if RUNTIME.exists():
        # This is a pre-execution test-fixture refresh only.  It is allowed
        # solely because the initial draft has no solver/launcher evidence;
        # any attempted CFD execution remains immutable and fail-closed.
        if any((RUNTIME / name).exists() for name in ("returns.txt", "launcher_return.json", "native.stdout", "adapter.stdout")):
            raise RuntimeError("V2 contains execution evidence: refusing to alter its test fixture")
        if not (RUNTIME / "manifest.json").is_file():
            raise RuntimeError("existing V2 directory lacks a manifest; refusing to infer its provenance")
        write(RUNTIME / "prescribed_participant.py", participant_code_v2())
    else:
        base.prepare()
    preflight = preflight_mapping()
    abi = abi_preflight()
    write(RUNTIME / "time_layer_preflight.json", json.dumps(preflight, indent=2) + "\n")
    write(RUNTIME / "abi_preflight.json", json.dumps(abi, indent=2) + "\n")
    if preflight["status"] != "PASS" or abi["status"] != "PASS":
        raise RuntimeError("time-layer or ABI preflight failed; CFD launch is forbidden")
    manifest = json.loads((RUNTIME / "manifest.json").read_text(encoding="utf-8"))
    manifest.update({
        "schema_version": "cfd-current-dynamic-nonzero-bridge-v2",
        "v1_immutable_predecessor": {"runtime": str(V1_RUNTIME), "result": str(V1_RESULTS)},
        "test_only_change": "participant preCICE storage-layer schedule: initial plan[1], then plan[2] through plan[100]; no formula or production semantic change",
        "time_layer_preflight": {"path": "time_layer_preflight.json", "status": preflight["status"]},
        "abi_preflight": {"path": "abi_preflight.json", "status": abi["status"]},
        "motion_identity_scope": "complete cylinder boundary geometry and adapter pointDisplacement values, every output time",
    })
    write(RUNTIME / "manifest.json", json.dumps(manifest, indent=2) + "\n")


def cylinder_vertex_ids(case: Path) -> list[int]:
    boundary = base.block((case / "constant/polyMesh/boundary").read_text(encoding="utf-8"), "cylinder")
    start = int(re.search(r"\bstartFace\s+(\d+)", boundary).group(1))
    count = int(re.search(r"\bnFaces\s+(\d+)", boundary).group(1))
    faces = []
    for line in (case / "constant/polyMesh/faces").read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"\s*\d+\(([^)]*)\)", line)
        if match:
            faces.append([int(value) for value in match.group(1).split()])
    return sorted({point for face in faces[start : start + count] for point in face})


def points(case: Path, time_name: str) -> list[list[float]]:
    text = (case / time_name / "polyMesh/points").read_text(encoding="utf-8", errors="replace")
    return [[float(v) for v in row] for row in re.findall(rf"\(\s*({base.NUMBER})\s+({base.NUMBER})\s+({base.NUMBER})\s*\)", text)]


def boundary_geometry_error(case: Path, time_name: str, baseline_points: list[list[float]], ids: list[int], y_m: float) -> dict[str, Any]:
    live = points(case, time_name)
    errors = []
    for point_id in ids:
        expected = baseline_points[point_id].copy()
        expected[1] += y_m
        errors.extend(abs(live[point_id][axis] - expected[axis]) for axis in range(3))
    return {"vertex_count": len(ids), "max_abs_component_error_m": max(errors, default=float("inf")), "all_components_within_motion_tol": max(errors, default=float("inf")) <= base.MOTION_ABS_TOL_M}


def point_displacement_error(case: Path, time_name: str, y_m: float) -> dict[str, Any]:
    path = case / time_name / "pointDisplacement"
    cylinder = base.block(path.read_text(encoding="utf-8", errors="replace"), "cylinder")
    values = re.findall(rf"\(\s*({base.NUMBER})\s+({base.NUMBER})\s+({base.NUMBER})\s*\)", cylinder)
    if not values:
        uniform = re.search(rf"\bvalue\s+uniform\s+\(\s*({base.NUMBER})\s+({base.NUMBER})\s+({base.NUMBER})\s*\)", cylinder)
        if uniform is None:
            raise RuntimeError(f"cannot non-lazily parse cylinder pointDisplacement at {path}")
        values = [uniform.groups()]
    errors = [abs(float(value[axis]) - (y_m if axis == 1 else 0.0)) for value in values for axis in range(3)]
    return {"value_count": len(values), "max_abs_component_error_m": max(errors), "all_components_within_motion_tol": max(errors) <= base.MOTION_ABS_TOL_M}


def participant_schedule_ok(participant: dict[str, Any]) -> bool:
    rows = participant.get("rows", [])
    initial = next((row for row in rows if row.get("event") == "INITIAL_DATA_FOR_FIRST_CFD_OUTPUT"), {})
    reads = [row for row in rows if row.get("event") == "READ_FORCE_AFTER_CFD_OUTPUT"]
    writes = [row for row in rows if row.get("event") == "WRITE_DISPLACEMENT_FOR_FUTURE_CFD_OUTPUT"]
    return (
        participant.get("steps") == base.STEPS
        and initial.get("payload_plan_step") == 1
        and initial.get("expected_cfd_output_time_s") == base.START + base.DT
        and len(reads) == base.STEPS and all(row.get("expected_applied_plan_step") == row.get("step") for row in reads)
        and len(writes) == base.STEPS and all(row.get("payload_plan_step") == min(row.get("advance_index", 0) + 1, base.STEPS) for row in writes)
    )


def audit_v2() -> dict[str, Any]:
    configure_base()
    preliminary = base.audit()
    native = RUNTIME / "native_interpolatingSolidBody"
    adapter = RUNTIME / "precice_displacementLaplacian"
    plan = json.loads((RUNTIME / "bridgeMotionPlan.json").read_text(encoding="utf-8"))
    ids = cylinder_vertex_ids(native)
    native_baseline = points(native, "0.105")
    adapter_baseline = points(adapter, "0.105")
    full_boundary = []
    for item in plan[1:]:
        time_name = f"{item['time_s']:.12g}"
        full_boundary.append({
            "step": item["step"], "time_s": item["time_s"],
            "native_geometry": boundary_geometry_error(native, time_name, native_baseline, ids, float(item["y_m"])),
            "adapter_geometry": boundary_geometry_error(adapter, time_name, adapter_baseline, ids, float(item["y_m"])),
            "adapter_pointDisplacement": point_displacement_error(adapter, time_name, float(item["y_m"])),
        })
    participant = json.loads((RUNTIME / "participant_evidence.json").read_text(encoding="utf-8"))
    full_motion = all(
        row["native_geometry"]["all_components_within_motion_tol"]
        and row["adapter_geometry"]["all_components_within_motion_tol"]
        and row["adapter_pointDisplacement"]["all_components_within_motion_tol"]
        for row in full_boundary
    )
    time_preflight = json.loads((RUNTIME / "time_layer_preflight.json").read_text(encoding="utf-8"))
    hard = dict(preliminary["hard_gates"])
    hard.update({"time_layer_preflight": time_preflight["status"] == "PASS", "participant_schedule": participant_schedule_ok(participant), "complete_boundary_motion": full_motion})
    status = "PASS" if all(hard.values()) else "FAIL_CLOSED"
    force = preliminary["force_comparison"] if full_motion else {"status": "NOT_EVALUABLE", "reason": "boundary motion identity failed; force-method comparison is prohibited"}
    result = {
        "schema_version": "cfd-current-dynamic-nonzero-bridge-v2-result",
        "status": status,
        "hard_gates": hard,
        "time_layer_preflight": time_preflight,
        "full_boundary_motion": full_boundary,
        "participant": participant,
        "force_comparison": force,
        "base_v1_compatible_audit": preliminary,
        "limitations": [
            "The 0.15 relative-L2 force reporting band is descriptive, not a new pass gate.",
            "Legal interior mesh deformation and meshPhi need not be identical between interpolatingSolidBody and displacementLaplacian.",
            "This is prescribed motion without ANCF feedback; it is neither free-FSI nor a VIV validation.",
        ],
    }
    write(RESULTS / "bridge_result_v2.json", json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "execute", "audit"))
    args = parser.parse_args()
    if args.command == "preflight":
        prepare_preflight()
        print(json.dumps({"status": "PREFLIGHT_PASS", "runtime": str(RUNTIME)}))
        return 0
    if args.command == "execute":
        configure_base()
        preflight = json.loads((RUNTIME / "time_layer_preflight.json").read_text(encoding="utf-8"))
        abi = json.loads((RUNTIME / "abi_preflight.json").read_text(encoding="utf-8"))
        if preflight.get("status") != "PASS" or abi.get("status") != "PASS":
            raise RuntimeError("time-layer or ABI preflight is not PASS; launch forbidden")
        base.execute()
        print(json.dumps({"status": "EXECUTED", "runtime": str(RUNTIME)}))
        return 0
    result = audit_v2()
    print(json.dumps({"status": result["status"], "hard_gates": result["hard_gates"]}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
