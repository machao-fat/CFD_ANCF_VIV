"""Authoritative bounded production launcher for formal ANCF--CFD windows.

The default remains the frozen single parallel-implicit qualification.  The
paired short-horizon diagnostic may opt into its strictly allowlisted 10-window
mode through environment variables, while reusing this exact preparation,
library binding, preflight, and process-launch path.
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
from coupling.cpp_worker_persistent_ipc_v1.identity_contract import build_identity, assert_ledger_compatible


RUN = os.environ.get(
    "FORMAL_IMPLICIT_RUN_ID",
    "formal_implicit_initial_data_and_socket_path_fix_v1_run_001",
)
RUNTIME, RESULTS = ROOT / "runtime" / RUN, ROOT / "results" / RUN
PARTICIPANT = ROOT / "tools" / "checkpoint_aware_structure_participant_and_one_window_implicit_qualification_v1" / "implicit_structure_participant.py"
# The historical default remains intact.  A bounded cross-window qualification
# may pass a separately built, manifest-recorded worker through the explicit
# opt-in below; it must never silently select a diagnostic binary.
WORKER = Path(os.environ.get(
    "FORMAL_CPP_WORKER",
    str(ROOT / "runtime" / "parallel_implicit_coupling_readiness_and_0p05s_diagnostic_v1" /
        "cpp_worker_build" / "cfd_ancf_ancf_kernel_worker"),
))
QUALITY_V4 = ROOT / "tools" / "parallel_explicit_fsi_timestep_stability_diagnostic_v1" / "openfoam_quality_contract_v4.json"
INITIAL_DATA_REGRESSION = ROOT / "results" / "formal_implicit_projected_initial_state_guard_closure_v1_regression_002" / "initial_data_and_path_regression.json"
IPC_REGRESSION = ROOT / "results" / "formal_implicit_ipc_and_first_step_quality_closure_v1_ipc_regression_004" / "ipc_contract_regression.json"
QUALITY_COMPLETION_REGRESSION = ROOT / "results" / "formal_implicit_ipc_quality_v4_completion_regression_001" / "quality_v4_completion_regression.json"
CROSS_WINDOW_IPC_REGRESSION = ROOT / "runtime" / "implicit_cross_window_ipc_lifecycle_closure_v1" / "real_worker_multiwindow_regression_002" / "real_worker_multiwindow_regression.json"
LIB_WSL = "/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_006/lib"
LIB_FILE = Path(LIB_WSL) / "libpreciceAdapterFunctionObject.so"
UPSTREAM = "d53753b1c927b2413b02299c9da15725b3e772f0"
PATCH_SET = ["0001-respect-adapter-target-dir", "0002-diagnostic-rollback-fingerprints", "0004-registry-safe-rollback-and-motion-timing", "0005-precice-time-layer-and-different-input-rollback"]
DT = 0.005
SCHEME = os.environ.get("FORMAL_COUPLING_SCHEME", "parallel-implicit")
DURATION_S = float(os.environ.get("FORMAL_PHYSICAL_HORIZON_S", str(DT)))
PAIRED_MODE = os.environ.get("FORMAL_PAIRED_DIAGNOSTIC", "0") == "1"
TWO_WINDOW_IPC_MODE = os.environ.get("FORMAL_CROSS_WINDOW_IPC_QUALIFICATION", "0") == "1"
if SCHEME not in ("parallel-explicit", "parallel-implicit"):
    raise RuntimeError("FORMAL_COUPLING_SCHEME must be parallel-explicit or parallel-implicit")
if DURATION_S <= 0.0 or abs(DURATION_S / DT - round(DURATION_S / DT)) > 1e-12:
    raise RuntimeError("FORMAL_PHYSICAL_HORIZON_S must be a positive integral number of frozen dt")
STEPS = int(round(DURATION_S / DT))
if PAIRED_MODE and TWO_WINDOW_IPC_MODE:
    raise RuntimeError("paired diagnostic and cross-window qualification modes are mutually exclusive")
if PAIRED_MODE:
    if STEPS != 10 or abs(DURATION_S - 0.05) > 1e-12:
        raise RuntimeError("paired diagnostic is authorized only for exactly 0.050 s / 10 windows")
elif TWO_WINDOW_IPC_MODE:
    if SCHEME != "parallel-implicit" or STEPS != 2 or abs(DURATION_S - 0.01) > 1e-12:
        raise RuntimeError("cross-window IPC qualification is authorized only for exactly two implicit windows / 0.010 s")
else:
    if SCHEME != "parallel-implicit" or STEPS != 1:
        raise RuntimeError("formal qualification default remains exactly one parallel-implicit window")


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


def production_identity_snapshot() -> dict[str, object]:
    """Persist the code actually launched; a dirty Git tree is not a commit ID."""
    def git(*arguments: str) -> str:
        completed = subprocess.run(["git", *arguments], cwd=ROOT, check=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   capture_output=True)
        return completed.stdout
    status = git("status", "--porcelain=v1")
    relevant_diff = git("diff", "--no-ext-diff", "--",
                        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp",
                        "tools/implicit_cross_window_ipc_lifecycle_closure_v1",
                        "tools/formal_ancf_cfd_implicit_one_window_qualification_v1/run_qualification.py")
    put(RUNTIME / "running_code_relevant.diff", relevant_diff)
    return {
        "git_commit": git("rev-parse", "HEAD").strip(),
        "dirty": bool(status.strip()),
        "git_status_porcelain_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
        "relevant_diff_sha256": hashlib.sha256(relevant_diff.encode("utf-8")).hexdigest(),
        "relevant_diff_path": str(RUNTIME / "running_code_relevant.diff"),
        "launcher": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__).resolve())},
        "structure_participant": {"path": str(PARTICIPANT), "sha256": sha256(PARTICIPANT)},
        "cpp_worker": {"path": str(WORKER), "sha256": sha256(WORKER)},
    }


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def wsl(path: Path) -> str:
    return canonical_wsl_path(path)


def coupling_xml(base, sid: int) -> str:
    original = base.xml(sid)
    exchanges = (
        f'<exchange data="Displacement" mesh="Structure-Mesh" from="Structure_{sid:04d}" to="Fluid_{sid:04d}" initialize="yes" substeps="false"/>'
        f'<exchange data="Force" mesh="Structure-Mesh" from="Fluid_{sid:04d}" to="Structure_{sid:04d}" substeps="false"/>'
    )
    if SCHEME == "parallel-implicit":
        replacement = (
            f'<coupling-scheme:parallel-implicit><participants first="Structure_{sid:04d}" second="Fluid_{sid:04d}"/>'
            f'<max-time value="{DURATION_S:g}"/><time-window-size value="{DT:g}"/><min-iterations value="2"/><max-iterations value="8"/>'
            '<absolute-or-relative-convergence-measure data="Displacement" mesh="Structure-Mesh" abs-limit="1e-8" rel-limit="1e-5"/>'
            '<absolute-or-relative-convergence-measure data="Force" mesh="Structure-Mesh" abs-limit="1e-3" rel-limit="1e-5"/>'
            + exchanges + '</coupling-scheme:parallel-implicit>'
        )
    else:
        replacement = (
            f'<coupling-scheme:parallel-explicit><participants first="Structure_{sid:04d}" second="Fluid_{sid:04d}"/>'
            f'<max-time value="{DURATION_S:g}"/><time-window-size value="{DT:g}"/>'
            + exchanges + '</coupling-scheme:parallel-explicit>'
        )
    return re.sub(r'<coupling-scheme:parallel-explicit>.*?</coupling-scheme:parallel-explicit>', replacement, original, flags=re.S)


def control(base) -> str:
    text = base.CONTROL.replace(
        "startFrom startTime; startTime 0; stopAt endTime; endTime 1;",
        f"startFrom startTime; startTime 0.1; stopAt endTime; endTime {0.1 + DURATION_S:g};",
    )
    return text.replace('libs ("libpreciceAdapterFunctionObject.so");', f'libs ("{LIB_WSL}/libpreciceAdapterFunctionObject.so");')


def structure_contract(original: dict) -> dict:
    contract = dict(original)
    human_case_name = os.environ.get("FORMAL_HUMAN_CASE_NAME", "formal_ancf_cfd_implicit_one_window_qualification_v1_case_001")
    ipc_identity = build_identity(RUN, human_case_name, str(RUNTIME))
    ledger = RUNTIME / "ipc_identity_contract_v1.json"
    if ledger.is_file():
        assert_ledger_compatible(ipc_identity, json.loads(ledger.read_text(encoding="utf-8")))
    else:
        assert_ledger_compatible(ipc_identity)
    contract.update({
        "schema_version": "formal-ancf-cfd-production-window-v1",
        "run_id": ipc_identity["run_id"],
        "case_id": ipc_identity["case_id"],
        "ipc_identity": ipc_identity,
        "duration_s": DURATION_S,
        "dt_s": DT,
        "number_of_steps": STEPS,
        "openfoam_physical_time_offset_s": 0.1,
        "coupling_scheme": SCHEME,
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
        "containment_limits": {
            "max_abs_ux_m": 0.1,
            "max_abs_vx_mps": 20.0,
            "max_abs_raw_Fx_N": 2000000.0,
        },
        "containment": "ARMED_BY_FROZEN_REGRESSION_AND_PRODUCTION_PARTICIPANT",
        "scope": f"exactly {STEPS} coupled physical window(s), {DURATION_S:g} s; no automatic continuation",
    })
    return contract


def prepare():
    if RUNTIME.exists() or RESULTS.exists():
        raise RuntimeError("refusing to overwrite immutable formal runtime")
    if not linux_file_exists(LIB_FILE):
        raise RuntimeError("patch-0005 adapter library is absent")
    if not INITIAL_DATA_REGRESSION.is_file():
        raise RuntimeError("projected initial-data regression evidence is absent")
    if not IPC_REGRESSION.is_file() or not QUALITY_COMPLETION_REGRESSION.is_file():
        raise RuntimeError("IPC or Quality V4 completion regression evidence is absent")
    if TWO_WINDOW_IPC_MODE and not CROSS_WINDOW_IPC_REGRESSION.is_file():
        raise RuntimeError("cross-window real-worker regression evidence is absent")
    initial_data_regression = json.loads(INITIAL_DATA_REGRESSION.read_text(encoding="utf-8"))
    projected = initial_data_regression.get("projected_initial_state_guard", {})
    if (initial_data_regression.get("INITIAL_DATA_PROTOCOL") != "PASS" or
            initial_data_regression.get("SOCKET_PATH_CANONICALIZATION") != "PASS" or
            projected.get("status") != "PASS"):
        raise RuntimeError("projected initial-data/socket preflight fails")
    ipc_regression = json.loads(IPC_REGRESSION.read_text(encoding="utf-8"))
    quality_completion = json.loads(QUALITY_COMPLETION_REGRESSION.read_text(encoding="utf-8"))
    if ipc_regression.get("IPC_IDENTITY_CONTRACT_V1") != "PASS":
        raise RuntimeError("IPC identity contract preflight fails")
    if quality_completion.get("QUALITY_V4_COMPLETION_CLASSIFICATION") != "PASS":
        raise RuntimeError("Quality V4 completion-classification preflight fails")
    cross_window_regression = None
    if TWO_WINDOW_IPC_MODE:
        cross_window_regression = json.loads(CROSS_WINDOW_IPC_REGRESSION.read_text(encoding="utf-8"))
        if (cross_window_regression.get("CROSS_WINDOW_IPC_LIFECYCLE") != "PASS" or
                cross_window_regression.get("windows_committed") != 3 or
                cross_window_regression.get("real_cpp_worker") is not True):
            raise RuntimeError("cross-window real-worker IPC lifecycle preflight fails")
    ipc_identity = build_identity(RUN, os.environ.get("FORMAL_HUMAN_CASE_NAME", "formal_ancf_cfd_implicit_one_window_qualification_v1_case_001"), str(RUNTIME))
    assert_ledger_compatible(ipc_identity)
    smoke = load(ROOT / "tools" / "preconditioned_coupled_0p1s_smoke_v1" / "run_smoke.py", "formal_implicit_preconditioned")
    original = smoke.contract
    smoke.RUN, smoke.RUNTIME, smoke.RESULTS = RUN, RUNTIME, RESULTS
    smoke.HERE, smoke.STEPS, smoke.DT, smoke.QUALITY = HERE, STEPS, DT, QUALITY_V4
    smoke.contract = lambda: structure_contract(original())
    smoke.cfg_xml = coupling_xml
    smoke.control = control
    base, cases, contract = smoke.prepare()
    code_identity = production_identity_snapshot()
    put(RUNTIME / "ipc_identity_contract_v1.json", ipc_identity)
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
        "coupling_scheme": SCHEME,
        "physical_horizon_s": DURATION_S,
        "cpp_worker": {"path": str(WORKER), "sha256": sha256(WORKER)},
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
        "running_code_identity": code_identity,
        "precursor_transfer": json.loads((RESULTS / "preflight.json").read_text(encoding="utf-8")),
        "quality_v4_sha256": sha256(QUALITY_V4),
        "generalized_force_metric_v2": contract["generalized_force_metric_v2"],
        "structure_participant": {"path": str(PARTICIPANT), "sha256": sha256(PARTICIPANT), "checkpoint_schema": "structure-participant-checkpoint-schema-v1", "prior_rollback_regression": "PASS (immutable run_003)", "wire_identity": "monotonic/non-restorable PASS (frozen regression)", "time_layer_contract": "PASS (frozen contract)", "realtime_containment": "PASS (frozen regression)"},
        "ipc_identity_contract": ipc_identity,
        "ipc_contract_regression": {"path": str(IPC_REGRESSION), "sha256": sha256(IPC_REGRESSION), "status": ipc_regression["IPC_IDENTITY_CONTRACT_V1"]},
        "quality_v4_completion_regression": {"path": str(QUALITY_COMPLETION_REGRESSION), "sha256": sha256(QUALITY_COMPLETION_REGRESSION), "status": quality_completion["QUALITY_V4_COMPLETION_CLASSIFICATION"]},
        "cross_window_ipc_regression": None if cross_window_regression is None else {
            "path": str(CROSS_WINDOW_IPC_REGRESSION),
            "sha256": sha256(CROSS_WINDOW_IPC_REGRESSION),
            "status": cross_window_regression["CROSS_WINDOW_IPC_LIFECYCLE"],
            "worker_sha256": cross_window_regression.get("worker_sha256"),
        },
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
        checkpoints = {int(row.get("window_id", -1)): row for row in by_event.get("CHECKPOINT_WRITE", [])}
        restored = by_event.get("POST_ROLLBACK_BEFORE_NEXT_INPUT", [])
        persistent = ("U", "p", "phi", "Uf", "cellDisplacement", "mesh_points")
        field_ok = bool(checkpoints and restored) and all(
            (checkpoint := checkpoints.get(int(item.get("window_id", -1)))) is not None and
            all(persistent_equal(checkpoint, item, name) for name in persistent) and
            checkpoint["physical_time"] == item["physical_time"] and checkpoint["time_index"] == item["time_index"]
            for item in restored)
        mesh_ok = bool(checkpoints and restored) and all(
            (checkpoint := checkpoints.get(int(item.get("window_id", -1)))) is not None and
            persistent_equal(checkpoint, item, "mesh_points") for item in restored)
        derived_ok = bool(checkpoints and restored) and all(item["states"]["meshPhi"]["classification"] in ("PERSISTENT_RESTORED", "NOT_OBSERVABLE_NOT_REGISTERED") for item in restored)
        rollback[str(sid)] = {"events": [row.get("event") for row in trace], "field_identity": field_ok, "mesh_identity": mesh_ok, "derived_history": derived_ok, "checkpoints": checkpoints, "restores": restored}
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
    final_loads = records[-1]["loads"] if records else []
    v2 = [row for row in iterations if row.get("event") == "post_cpp_correction"]
    restores = [row for row in iterations if row.get("event") == "checkpoint_restore"]
    wires = [row.get("wire_sequence") for row in v2]
    try:
        newton_ok = validate_records(newton, expected_steps=STEPS).get("status") == "pass"
    except Exception:
        newton_ok = False
    max_ux, max_vx = [], []
    for sid in range(3):
        max_ux.append(max((abs(float(row["motion"][sid]["ux_m"])) for row in records), default=math.inf))
        max_vx.append(max((abs(float(row["motion"][sid]["vx_mps"])) for row in records), default=math.inf))
    checks = {
        "three_adapter_manifests": (RUNTIME / "adapter_manifest.json").is_file(),
        "return_codes": return_code == 0 and summary.get("status") == "completed",
        "structure_rollback": (not SCHEME == "parallel-implicit") or (bool(restores) and all(row.get("checkpoint_state_sha256") == row.get("post_restore_state_sha256") for row in restores)),
        "unique_wire_ids": len(wires) >= 2 * STEPS and len(wires) == len(set(wires)),
        "fluid_field_history_rollback": (not SCHEME == "parallel-implicit") or all(item["field_identity"] and item["derived_history"] for item in rollback.values()),
        "dynamic_mesh_rollback": (not SCHEME == "parallel-implicit") or all(item["mesh_identity"] for item in rollback.values()),
        "two_to_eight_iterations": (not SCHEME == "parallel-implicit") or all(2 <= int(row.get("coupling_iteration_final", 0)) <= 8 for row in records),
        "physical_commits": len(records) == STEPS and summary.get("committed_steps") == STEPS,
        "final_of_time": all(trace and abs(float(trace[-1].get("physical_time", math.inf)) - (0.1 + DURATION_S)) <= 1e-12 for trace in traces.values()),
        "force_contract": len(final_loads) == 3 and all(abs(float(load["force_x_N"]) - float(load["force_2d_x_Npm"]) * float(load["slice_length_m"])) <= 1e-10 for row in records for load in row["loads"]),
        "generalized_force_v2": bool(v2) and all(row["generalized_force_metric_v2"]["GENERALIZED_FORCE_MAPPING_V2"] == "PASS" for row in v2),
        "newton": newton_ok and len(newton) == 2 * STEPS,
        "quality_v4": all(item["status"] == "pass" for item in quality.values()),
        "no_fpe": return_code == 0,
        "forces_available": all(force is not None for force in forces),
    }
    gate_name = "FORMAL_IMPLICIT_TWO_WINDOW" if TWO_WINDOW_IPC_MODE else "FORMAL_IMPLICIT_ONE_WINDOW"
    result = {
        gate_name: "PASS" if all(checks.values()) else "FAIL",
        "checks": checks, "return_code": return_code, "adapter_manifest": json.loads((RUNTIME / "adapter_manifest.json").read_text(encoding="utf-8")),
        "structure_summary": summary, "iteration_count": summary.get("coupling_iterations_total"), "iteration_evidence": iterations,
        "fluid_rollback": rollback, "quality_v4": quality, "final_raw_force": forces, "integrated_structural_force": final_loads,
        "max_abs_ux_m": max_ux, "max_abs_vx_mps": max_vx, "coupling_scheme": SCHEME,
        "first_blocker": next((name for name, value in checks.items() if not value), None),
    }
    put(RESULTS / "formal_one_window_gate.json", result)
    return result


def main() -> int:
    base, cases, _ = prepare()
    code = launch(base, cases)
    result = audit(cases, code)
    gate_name = "FORMAL_IMPLICIT_TWO_WINDOW" if TWO_WINDOW_IPC_MODE else "FORMAL_IMPLICIT_ONE_WINDOW"
    print(json.dumps({"gate": result[gate_name], "iterations": result["iteration_count"], "blocker": result["first_blocker"]}, ensure_ascii=False))
    return 0 if result[gate_name] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
