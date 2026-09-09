"""Prepare and run the one-window W10 predictor-force identity replay.

The immutable 0.05 s formal run ended after Structure rejected W10/trial 3.
This tool never reads its rejected 0.150 s state.  It reconstructs the W10
predictor from the committed W9 C++ checkpoint and uses a fresh, one-window
preCICE prescribed-motion run starting from the accepted OpenFOAM 0.145 write.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "runtime/formal_three_slice_implicit_0p05s_owned_mesh_history_v1_run_001"
# run_001 is retained as an aborted Windows-host preparation attempt and
# run_002 as an aborted direct-W10 worker-frame attempt. Neither started CFD.
TARGET = ROOT / "runtime/window10_predictor_force_identity_replay_v1_run_003"
CONTRACT = SOURCE / "preconditioned_coupled_0p1s_smoke_v1_contract.json"
INITIAL_STATE = ROOT / "runtime/stage4f_d_cpp_worker_initialization_v1/run_20260827_cpp_only/ancf_t0_state_cpp.json"
WORKER = ROOT / "runtime/implicit_cross_window_ipc_lifecycle_closure_v1/cpp_worker_build_001/cfd_ancf_ancf_kernel_worker"
ORIGINAL_CHECKPOINT = SOURCE / "checkpoints/window_000010_checkpoint.cpp.json"
ORIGINAL_PHYSICAL = SOURCE / "checkpoints/window_000010_checkpoint.json"
EXPECTED_PREDICTION_HASH = "53bb18a01d709d5c21218729630e2955bdf2e69046d6a63d3d70191d8eb6c411"
DT = 0.005
VERTEX_COUNT = 40
TRANSACTION_ID = "WINDOW10_PREDICTOR_FORCE_IDENTITY_REPLAY_V1/run_001"


def canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def wsl(path: Path) -> str:
    resolved = str(path.resolve()).replace("\\", "/")
    if resolved.startswith("/mnt/"):
        return resolved
    if len(resolved) < 3 or resolved[1] != ":":
        raise RuntimeError(f"not a Windows drive path: {path}")
    return "/mnt/" + resolved[0].lower() + resolved[2:]


def participant_module() -> Any:
    path = ROOT / "tools/checkpoint_aware_structure_participant_and_one_window_implicit_qualification_v1/implicit_structure_participant.py"
    spec = importlib.util.spec_from_file_location("formal_structure_participant", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen Structure participant helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trace_rows(slice_id: int) -> list[dict[str, Any]]:
    path = SOURCE / f"fluid_{slice_id:04d}_adapter_trace.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def original_w10_trace_identity() -> dict[str, Any]:
    responses = json.loads((SOURCE / "structure_summary.json").read_text(encoding="utf-8"))["adapter_responses"]
    matches = [row for row in responses if row.get("phase") == "prediction" and row.get("step") == 10]
    hashes = {row.get("payload_hash") for row in matches}
    if hashes != {EXPECTED_PREDICTION_HASH}:
        raise RuntimeError(f"original W10 predictor response hash is not unique/pinned: {hashes}")
    restored: dict[str, Any] = {}
    for sid in range(3):
        rows = trace_rows(sid)
        candidates = [row for row in rows if row.get("event") == "POST_ROLLBACK_BEFORE_NEXT_INPUT"
                      and row.get("window_id") == 10 and row.get("physical_time") == 0.14500000000000005]
        if not candidates:
            raise RuntimeError(f"slice {sid} lacks a W10 restored checkpoint trace")
        state = candidates[-1].get("states", {})
        required = ("U", "Uf", "pointDisplacement", "mesh_points", "owner_mesh_history")
        if not all(name in state for name in required):
            raise RuntimeError(f"slice {sid} W10 restored trace lacks required fields")
        restored[str(sid)] = {name: state[name] for name in required}
    return {"original_w10_prediction_response_hash": EXPECTED_PREDICTION_HASH,
            "prediction_response_count": len(matches), "restored_w9_state_trace": restored}


def build_payloads() -> dict[str, Any]:
    """Recreate the formal W10 predictor and prove its response identity."""
    sys.path.insert(0, str(ROOT / "src"))
    from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker
    from coupling.cpp_worker_confirm_v1.cpp_adapter import CppKernelCampaignAdapter
    from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest
    from coupling.multi_slice_mapping.mapping import (SliceDefinition, SliceManifest,
        build_H_for_manifest, motion_from_ancf_state)
    from coupling.three_slice_force_contract_smoke_v1.contract import bounded_midpoint_voronoi

    participant = participant_module()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    physical = json.loads(ORIGINAL_PHYSICAL.read_text(encoding="utf-8"))
    checkpoint = json.loads(ORIGINAL_CHECKPOINT.read_text(encoding="utf-8"))
    if physical["physical"]["adapter_state"] != checkpoint["state_view"]:
        raise RuntimeError("W9 physical and C++ checkpoint states disagree")
    if canonical(physical["physical"]) != physical["physical_state_sha256"]:
        raise RuntimeError("W9 physical checkpoint digest disagrees")
    if physical["physical"]["committed_steps"] != 9 or checkpoint["committed_global_step"] != 9:
        raise RuntimeError("W9 checkpoint is not the accepted boundary before W10")
    prior = physical["physical"]["previous_slice_forces_N"]
    state = json.loads(INITIAL_STATE.read_text(encoding="utf-8"))
    model = participant.model_from_contract(contract)
    import struct
    mass = tuple(float(x) for x in state["mass_matrix"])
    model_hash = hashlib.sha256(model.bytes() + struct.pack("<" + "d" * len(mass), *mass)).hexdigest()
    worker = KernelWorker(WORKER, TARGET / "cpp_predictor_worker", str(contract["run_id"]),
                          str(contract["case_id"]), expected_model_contract_sha256=model_hash,
                          allow_implicit_retry=True)
    # A resident worker starts a new transport segment at sequence/bridge 1.
    # Its physical request still has global step 10 and W9 q/qdot/qddot; these
    # are the only state inputs to the predictor. Transport identity is
    # deliberately excluded from the old physical checkpoint contract.
    state_w9 = checkpoint["state_view"]
    adapter = CppKernelCampaignAdapter(worker=worker, model=model, request_factory=KernelStepRequest,
        run_id=str(contract["run_id"]), case_id=str(contract["case_id"]), source_global_step=9,
        source_time_s=0.045, source_tick=45_000_000, dt_s=DT,
        q=tuple(float(x) for x in state_w9["q"]), qdot=tuple(float(x) for x in state_w9["qdot"]),
        qddot=tuple(float(x) for x in state_w9["qddot"]), base_load=tuple(float(x) for x in state["base_load"]),
        mass_matrix=mass, strict_numerical_contract=True, expected_model_contract_sha256=model_hash,
        implicit_rollback_transport=True)
    try:
        adapter.start()
        if adapter.state_view() != physical["physical"]["adapter_state"]:
            raise RuntimeError("new W9 worker segment does not exactly reproduce saved ANCF state")
        prediction, _ = adapter.predict(10, 0.05, prior)
    finally:
        adapter.shutdown()
    if prediction["payload_hash"] != EXPECTED_PREDICTION_HASH:
        raise RuntimeError("regenerated W10 predictor response does not equal immutable formal response")

    items = contract["slices"]["items"]
    length, elements = float(contract["ANCF"]["length_m"]), int(contract["ANCF"]["elements"])
    partition = bounded_midpoint_voronoi([x["s_ref_m"] for x in items], contract["slices"]["represented_interval_m"])
    definitions = tuple(SliceDefinition(int(x["slice_id"]), float(x["s_ref_m"]), right-left,
                                        float(x["unit_span_m"])) for x, (left, _, right) in zip(items, partition))
    manifest = SliceManifest("0.2.1", str(contract["case_id"]), length, length, definitions)
    H = build_H_for_manifest(manifest, tuple(length * i / elements for i in range(elements + 1)))
    current = physical["physical"]["adapter_state"]
    initial: dict[str, list[list[float]]] = {}
    predictor: dict[str, list[list[float]]] = {}
    motion_summary: dict[str, dict[str, float]] = {}
    for sid, definition in enumerate(definitions):
        accepted = motion_from_ancf_state(manifest, sid, H[sid], current["q"], current["qdot"],
            current["qddot"], step=9, time_s=0.045, reference_position_m=(0.0, 0.0, definition.s_ref_m))
        trial = motion_from_ancf_state(manifest, sid, H[sid], prediction["predictor"],
            prediction["predictor_qdot"], prediction["predictor_qddot"], step=10, time_s=0.05,
            reference_position_m=(0.0, 0.0, definition.s_ref_m))
        initial[str(sid)] = [[float(accepted.ux_m), float(accepted.uy_m)] for _ in range(VERTEX_COUNT)]
        predictor[str(sid)] = [[float(trial.ux_m), float(trial.uy_m)] for _ in range(VERTEX_COUNT)]
        motion_summary[str(sid)] = {"accepted_ux_m": float(accepted.ux_m),
                                    "accepted_uy_m": float(accepted.uy_m),
                                    "predictor_ux_m": float(trial.ux_m),
                                    "predictor_uy_m": float(trial.uy_m),
                                    "predictor_vx_mps": float(trial.vx_mps),
                                    "predictor_vy_mps": float(trial.vy_mps)}
    return {"schema_version": "window10-predictor-input-v1", "transaction_id": TRANSACTION_ID,
            "checkpoint": {"path": str(ORIGINAL_CHECKPOINT), "sha256": sha256(ORIGINAL_CHECKPOINT),
                           "physical_sha256": physical["physical_state_sha256"]},
            "prior_accepted_slice_forces_N": prior,
            "original_prediction_response_hash": EXPECTED_PREDICTION_HASH,
            "regenerated_prediction_response_hash": prediction["payload_hash"],
            "full_predictor_state_sha256": canonical({"q": prediction["predictor"],
                                                        "qdot": prediction["predictor_qdot"],
                                                        "qddot": prediction["predictor_qddot"]}),
            "projection_contract": "frozen motion_from_ancf_state + repeated 40x [ux,uy] Structure-Mesh order",
            "initial_payload": initial, "predictor_payload": predictor,
            "initial_payload_sha256": {sid: canonical(value) for sid, value in initial.items()},
            "predictor_payload_sha256": {sid: canonical(value) for sid, value in predictor.items()},
            "motion_summary": motion_summary}


def require_restart_artifacts() -> dict[str, Any]:
    required = ("U", "Uf", "p", "phi", "meshPhi", "pointDisplacement", "cellDisplacement")
    evidence: dict[str, Any] = {}
    for sid in range(3):
        case = SOURCE / f"cases/slice_{sid:04d}"
        time_dir = case / "0.145"
        missing = [name for name in required if not (time_dir / name).is_file()]
        points = time_dir / "polyMesh/points"
        if missing or not points.is_file():
            raise RuntimeError(f"slice {sid} lacks W9 restart artifacts: fields={missing}, points={points.exists()}")
        evidence[str(sid)] = {"time": "0.145", "field_sha256": {name: sha256(time_dir / name) for name in required},
                              "polyMesh_points_sha256": sha256(points)}
    return evidence


def make_config(source: str, exchange_directory: str) -> str:
    if '<max-time value="0.05"/>' not in source:
        raise RuntimeError("frozen preCICE max-time literal not found")
    result = source.replace('<max-time value="0.05"/>', '<max-time value="0.005"/>')
    old = '/mnt/d/研二文件/开题准备/CFD_ANCF_VIV/runtime/formal_three_slice_implicit_0p05s_owned_mesh_history_v1_run_001/precice-sockets'
    if old not in result:
        raise RuntimeError("frozen preCICE exchange directory literal not found")
    return result.replace(old, exchange_directory)


def make_control(source: str) -> str:
    old = 'startFrom startTime; startTime 0.1; stopAt endTime; endTime 0.15; deltaT 0.005;'
    new = 'startFrom startTime; startTime 0.145; stopAt endTime; endTime 0.15; deltaT 0.005;'
    if old not in source:
        raise RuntimeError("frozen control time literal not found")
    return source.replace(old, new)


def prepare() -> None:
    if os.name == "nt":
        raise RuntimeError("prepare must run under WSL: the pinned ANCF worker is a Linux ELF binary")
    if TARGET.exists():
        raise RuntimeError(f"refusing to reuse replay runtime: {TARGET}")
    if not all(path.is_file() for path in (CONTRACT, INITIAL_STATE, WORKER, ORIGINAL_CHECKPOINT, ORIGINAL_PHYSICAL)):
        raise RuntimeError("required immutable source artifact is missing")
    restart = require_restart_artifacts()
    trace_identity = original_w10_trace_identity()
    TARGET.mkdir(parents=True)
    payloads = build_payloads()
    for sid in range(3):
        src = SOURCE / f"cases/slice_{sid:04d}"
        dst = TARGET / "cases" / f"slice_{sid:04d}"
        for name in ("0.145", "constant", "system"):
            shutil.copytree(src / name, dst / name)
        control = dst / "system/controlDict"
        control.write_text(make_control(control.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
        config = dst / "precice-config.xml"
        config.write_text(make_config((src / "precice-config.xml").read_text(encoding="utf-8"),
                                      wsl(TARGET / "precice-sockets")), encoding="utf-8", newline="\n")
    put_json(TARGET / "payloads.json", payloads)
    preflight = {"schema_version": "window10-predictor-force-identity-preflight-v1",
                 "status": "PASS", "transaction_id": TRANSACTION_ID,
                 "source_runtime": str(SOURCE), "source_runtime_sha256": None,
                 "restart_scope": "accepted W9 0.145 disk restart; current Euler/non-subcycled lazy-history semantics only",
                 "restart_artifacts": restart, "trace_identity": trace_identity,
                 "predictor_identity": {key: payloads[key] for key in ("checkpoint", "prior_accepted_slice_forces_N",
                     "original_prediction_response_hash", "regenerated_prediction_response_hash",
                     "full_predictor_state_sha256", "projection_contract", "predictor_payload_sha256")},
                 "test_only_changes": ["fresh runtime", "preCICE max-time 0.005 only", "OpenFOAM startTime 0.145 only",
                     "fresh preCICE socket directory"],
                 "prohibited_source": "no source 0.150 field, mesh, or Structure state is copied"}
    put_json(TARGET / "preflight.json", preflight)
    launcher = f'''set -o pipefail
export ZSH_NAME=
source '{wsl(ROOT / "tools/of10_owned_atomic_mesh_history_restore_prototype_v1/prototype_env.sh")}' '/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/owner_diagnostic_abi_build_001'
export LD_LIBRARY_PATH='/home/machao/OpenFOAM/of10_owned_atomic_mesh_history_restore_prototype_v1/adapter_owner_diagnostic_build_001/lib':$LD_LIBRARY_PATH
export PYTHONPATH='{wsl(ROOT / "src")}:{wsl(ROOT / "runtime/284_precice_single_slice_smoke_real_v1/python_deps")}'
'''
    for sid in range(3):
        launcher += f"python3 '{wsl(Path(__file__))}' participant --slice {sid} --config '{wsl(TARGET / f'cases/slice_{sid:04d}/precice-config.xml')}' --payloads '{wsl(TARGET / 'payloads.json')}' --evidence '{wsl(TARGET / f'structure_{sid:04d}_transaction.json')}' & s{sid}=$!\n"
    for sid in range(3):
        case = TARGET / "cases" / f"slice_{sid:04d}"
        launcher += f"(cd '{wsl(case)}' && PRECICE_ADAPTER_ROLLBACK_DIAGNOSTICS_PATH='{wsl(TARGET / f'fluid_{sid:04d}_adapter_trace.jsonl')}' PRECICE_ADAPTER_BUILD_SHA256='c8bb6fd83be795834dcdfcae0f8b8606ba09b546611a33fb0ddfa379e47e8f17' pimpleFoam > '{wsl(TARGET / f'fluid_{sid:04d}.stdout')}' 2> '{wsl(TARGET / f'fluid_{sid:04d}.stderr')}') & f{sid}=$!\n"
    launcher += "wait $s0; r_s0=$?; wait $s1; r_s1=$?; wait $s2; r_s2=$?; wait $f0; r_f0=$?; wait $f1; r_f1=$?; wait $f2; r_f2=$?\nprintf 'structure=%s,%s,%s fluid=%s,%s,%s\\n' $r_s0 $r_s1 $r_s2 $r_f0 $r_f1 $r_f2 > '" + wsl(TARGET / "returns.txt") + "'\n[ $r_s0 -eq 0 ] && [ $r_s1 -eq 0 ] && [ $r_s2 -eq 0 ] && [ $r_f0 -eq 0 ] && [ $r_f1 -eq 0 ] && [ $r_f2 -eq 0 ]\n"
    (TARGET / "launch.sh").write_text(launcher, encoding="utf-8", newline="\n")


def participant(slice_id: int, config: Path, payload_path: Path, evidence: Path) -> None:
    try:
        import precice  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyprecice is unavailable in the selected replay environment") from exc
    payloads = json.loads(payload_path.read_text(encoding="utf-8"))
    initial = payloads["initial_payload"][str(slice_id)]
    predictor = payloads["predictor_payload"][str(slice_id)]
    if len(initial) != VERTEX_COUNT or len(predictor) != VERTEX_COUNT:
        raise RuntimeError("replay payload vertex count mismatch")
    import math
    vertices = [(.5 * math.cos(2 * math.pi * i / VERTEX_COUNT), .5 * math.sin(2 * math.pi * i / VERTEX_COUNT))
                for i in range(VERTEX_COUNT)]
    name = f"Structure_{slice_id:04d}"
    part = precice.Participant(name, str(config), 0, 1)
    mesh = part.set_mesh_vertices("Structure-Mesh", vertices)
    rows: list[dict[str, Any]] = []
    try:
        requested = part.requires_initial_data()
        if requested:
            part.write_data("Structure-Mesh", "Displacement", mesh, initial)
        rows.append({"event": "INITIAL_ACCEPTED_W9_DISPLACEMENT", "transaction_id": TRANSACTION_ID,
                     "requested": requested, "payload_sha256": canonical(initial), "vertices": VERTEX_COUNT,
                     "components": ["x", "y"], "units": "m"})
        part.initialize()
        iteration = 0
        while part.is_coupling_ongoing():
            if part.requires_writing_checkpoint():
                rows.append({"event": "CHECKPOINT_CALLBACK", "transaction_id": TRANSACTION_ID,
                             "iteration": iteration, "physical_time_s": 0.0})
            part.write_data("Structure-Mesh", "Displacement", mesh, predictor)
            iteration += 1
            part.advance(DT)
            raw = part.read_data("Structure-Mesh", "Force", mesh, 0.0)
            values = raw.tolist() if hasattr(raw, "tolist") else raw
            force = [sum(float(row[d]) for row in values) for d in range(2)]
            rows.append({"event": "STRUCTURE_RECEIVE_RAW_FORCE", "transaction_id": TRANSACTION_ID,
                         "iteration": iteration, "physical_time_s": DT, "force_vertices": len(values),
                         "components": ["x", "y"], "units": "N", "payload_sha256": canonical(values),
                         "sum_force_xy_N": force, "predictor_payload_sha256": canonical(predictor)})
            if part.requires_reading_checkpoint():
                rows.append({"event": "ROLLBACK_CALLBACK", "transaction_id": TRANSACTION_ID,
                             "iteration": iteration, "physical_time_s": 0.0})
                continue
            rows.append({"event": "PARTICIPANT_FINALIZED_WITHOUT_ANCF_CORRECTION", "transaction_id": TRANSACTION_ID,
                         "iteration": iteration, "physical_time_s": DT})
            break
    finally:
        part.finalize()
    put_json(evidence, {"schema_version": "window10-replay-structure-transaction-v1", "slice_id": slice_id,
                        "transaction_id": TRANSACTION_ID, "rows": rows,
                        "contains_ancf_correction": False, "contains_physical_commit": False})


def execute() -> None:
    if not (TARGET / "preflight.json").is_file() or not (TARGET / "payloads.json").is_file():
        raise RuntimeError("run prepare successfully before the one authorized execution")
    if (TARGET / "returns.txt").exists():
        raise RuntimeError("replay execution evidence already exists; automatic rerun is forbidden")
    command = (["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", wsl(TARGET / "launch.sh")]
               if os.name == "nt" else ["bash", wsl(TARGET / "launch.sh")])
    done = subprocess.run(command,
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    (TARGET / "launcher.stdout").write_text(done.stdout, encoding="utf-8", newline="\n")
    (TARGET / "launcher.stderr").write_text(done.stderr, encoding="utf-8", newline="\n")
    if done.returncode != 0:
        raise RuntimeError(f"controlled replay failed with launcher return {done.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    participant_parser = sub.add_parser("participant")
    participant_parser.add_argument("--slice", required=True, type=int, choices=(0, 1, 2))
    participant_parser.add_argument("--config", required=True, type=Path)
    participant_parser.add_argument("--payloads", required=True, type=Path)
    participant_parser.add_argument("--evidence", required=True, type=Path)
    sub.add_parser("execute")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "participant":
        participant(args.slice, args.config, args.payloads, args.evidence)
    else:
        execute()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
