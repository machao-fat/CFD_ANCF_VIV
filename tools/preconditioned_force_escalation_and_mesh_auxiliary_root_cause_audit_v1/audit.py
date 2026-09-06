"""Read-only ledger plus ANCF recorded-load replay for the preconditioned 0.1 s run.

The coupled source runtime is never opened for writing.  The replay owns a new
runtime and uses the identical predictor/corrector sequence, force history and
initial C++ state recorded by the coupled run.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "three_slice_force_contract_smoke_v1"))

from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker
from coupling.cpp_worker_confirm_v1.cpp_adapter import CppKernelCampaignAdapter
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest
from coupling.multi_slice_mapping.mapping import (SliceDefinition, SliceManifest,
    build_H_for_manifest, motion_from_ancf_state)
from coupling.slice_independence_audit_v1.audit import parse_forces
from coupling.openfoam_numerical_quality_contract_v2.audit import audit_log
from coupling.openfoam_numerical_quality_contract_v3.audit import evaluate_quality_v3

from structure_participant import model_from_contract

RUN = "preconditioned_coupled_0p1s_smoke_v1_run_003"
SOURCE = ROOT / "runtime" / RUN
CONTRACT = ROOT / "tools/preconditioned_coupled_0p1s_smoke_v1/preconditioned_coupled_0p1s_smoke_v1_contract.json"
STATE = ROOT / "runtime/stage4f_d_cpp_worker_initialization_v1/run_20260827_cpp_only/ancf_t0_state_cpp.json"
WORKER = ROOT / "runtime/292_cpp_worker_linux_build_v1/cfd_ancf_ancf_kernel_worker"
QUALITY = ROOT / "tools/precursor_transfer_and_structural_mean_load_closure_v1/openfoam_quality_contract_v3.json"
OUT = ROOT / "results/preconditioned_force_escalation_and_mesh_auxiliary_root_cause_audit_v1_run_001"
REPLAY = ROOT / "runtime/preconditioned_force_escalation_force_replay_v1_run_002"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def read_records() -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in (SOURCE / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    if len(rows) != 20 or [int(row["global_step"]) for row in rows] != list(range(1, 21)):
        raise RuntimeError("immutable coupled source does not contain exactly 20 contiguous records")
    return rows


def definitions(contract: dict[str, Any]) -> tuple[SliceManifest, tuple[Any, ...], tuple[Any, ...]]:
    items = contract["slices"]["items"]
    length = float(contract["ANCF"]["length_m"])
    # The frozen midpoint/Voronoi partition is exactly the recorded contract.
    boundaries = (0.0, 16.666666666666668, 33.33333333333333, length)
    defs = tuple(SliceDefinition(int(item["slice_id"]), float(item["s_ref_m"]),
                                 boundaries[index + 1] - boundaries[index], float(item["unit_span_m"]))
                 for index, item in enumerate(items))
    manifest = SliceManifest("0.2.1", str(contract["case_id"]), length, length, defs)
    nodes = tuple(length * index / int(contract["ANCF"]["elements"]) for index in range(int(contract["ANCF"]["elements"]) + 1))
    return manifest, defs, build_H_for_manifest(manifest, nodes)


def corrected_motion(manifest: SliceManifest, defs: tuple[Any, ...], H: tuple[Any, ...], row: dict[str, Any]) -> list[dict[str, float]]:
    state = row["ancf_state"]
    result = []
    for sid in range(3):
        motion = motion_from_ancf_state(manifest, sid, H[sid], state["q"], state["qdot"], state["qddot"],
                                        step=int(row["global_step"]), time_s=float(row["time_s"]),
                                        reference_position_m=(0.0, 0.0, defs[sid].s_ref_m))
        result.append(motion.to_dict())
    return result


def ledger() -> dict[str, Any]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    rows = read_records()
    manifest, defs, H = definitions(contract)
    qcontract = json.loads(QUALITY.read_text(encoding="utf-8"))
    force_paths = [list((SOURCE / "cases" / f"slice_{sid:04d}" / "postProcessing/cylinderForces").glob("*/forces.dat")) for sid in range(3)]
    if any(len(paths) != 1 for paths in force_paths):
        raise RuntimeError(f"force-file identity is not unique: {force_paths}")
    forces = [parse_forces(paths[0]) for paths in force_paths]
    output: list[dict[str, Any]] = []
    for row in rows:
        step = int(row["global_step"]); tau = float(row["time_s"]); tof = 0.1 + tau
        corrected = corrected_motion(manifest, defs, H, row)
        entry: dict[str, Any] = {"global_step": step, "coupling_tau_s": tau, "openfoam_physical_time_s": tof,
                                  "slices": []}
        for sid in range(3):
            load = row["loads"][sid]; raw = forces[sid].get(round(tof, 9))
            if raw is None:
                raise RuntimeError(f"raw force missing at {tof:g} s for slice {sid}")
            predicted = row["motion"][sid]
            corr = corrected[sid]
            entry["slices"].append({
                "slice_id": sid,
                "raw_pressure_force_N": raw["pressure_N"], "raw_viscous_force_N": raw["viscous_N"],
                "raw_total_force_N": raw["total_N"],
                "adapter_raw_force_N": [load["openfoam_force_x_N"], load["openfoam_force_y_N"], load["openfoam_force_z_N"]],
                "integrated_structural_force_N": [load["force_x_N"], load["force_y_N"], load["force_z_N"]],
                "prediction": {key: predicted[key] for key in ("ux_m", "uy_m", "vx_mps", "vy_mps", "ax_mps2", "ay_mps2")},
                "correction": {key: corr[key] for key in ("ux_m", "uy_m", "vx_mps", "vy_mps", "ax_mps2", "ay_mps2")},
            })
        output.append(entry)
    quality: dict[str, Any] = {}
    for sid in range(3):
        case = SOURCE / "cases" / f"slice_{sid:04d}"
        parsed = audit_log(SOURCE / "logs" / f"fluid_{sid:04d}.stdout", case / "system/fvSolution")
        quality[str(sid)] = {"audit": parsed, "v3": evaluate_quality_v3(parsed, qcontract)}
    result = {"schema_version": "preconditioned-force-escalation-ledger-v1", "source_run": RUN,
              "source_records_sha256": hashlib.sha256((SOURCE / "records.jsonl").read_bytes()).hexdigest(),
              "ledger": output, "quality": quality,
              "reference_normal_integrated_Fx_per_slice_N": 22503.305595427,
              "time_relation": "openfoam_physical_time_s = 0.100 + coupling_tau_s"}
    write_json(OUT / "causal_ledger.json", result)
    return result


def replay_structure() -> dict[str, Any]:
    if REPLAY.exists():
        raise RuntimeError(f"refusing to reuse replay runtime: {REPLAY}")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8")); initial = json.loads(STATE.read_text(encoding="utf-8")); rows = read_records()
    manifest, defs, H = definitions(contract); model = model_from_contract(contract)
    q, qdot, qddot = (tuple(float(value) for value in initial[key]) for key in ("q", "qdot", "qddot"))
    mass = tuple(float(value) for value in initial["mass_matrix"]); base = tuple(float(value) for value in initial["base_load"])
    model_hash = hashlib.sha256(model.bytes() + struct.pack("<" + "d" * len(mass), *mass)).hexdigest()
    worker = KernelWorker(WORKER, REPLAY / "cpp_worker", "preconditioned_force_history_replay_v1_run_001",
                          "preconditioned_force_history_replay_v1_case_001", expected_model_contract_sha256=model_hash)
    adapter = CppKernelCampaignAdapter(worker=worker, model=model, request_factory=KernelStepRequest,
        run_id="preconditioned_force_history_replay_v1_run_001", case_id="preconditioned_force_history_replay_v1_case_001",
        source_global_step=0, source_time_s=0.0, source_tick=0, dt_s=float(contract["dt_s"]),
        q=q, qdot=qdot, qddot=qddot, base_load=base, mass_matrix=mass, slice_count=3,
        strict_numerical_contract=True, expected_model_contract_sha256=model_hash)
    replay_rows: list[dict[str, Any]] = []; prior = [(0.0, 0.0, 0.0)] * 3
    try:
        adapter.start()
        for source in rows:
            step = int(source["global_step"]); time_s = float(source["time_s"])
            prediction, _ = adapter.predict(step, time_s, prior)
            pred = [motion_from_ancf_state(manifest, sid, H[sid], prediction["predictor"], prediction["predictor_qdot"], prediction["predictor_qddot"],
                                           step=step, time_s=time_s, reference_position_m=(0.0, 0.0, defs[sid].s_ref_m)).to_dict() for sid in range(3)]
            loads = [[float(load["force_x_N"]), float(load["force_y_N"]), float(load["force_z_N"])] for load in source["loads"]]
            correction, _ = adapter.correct(step, time_s, loads)
            state = adapter.state_view()
            corr = [motion_from_ancf_state(manifest, sid, H[sid], state["q"], state["qdot"], state["qddot"],
                                            step=step, time_s=time_s, reference_position_m=(0.0, 0.0, defs[sid].s_ref_m)).to_dict() for sid in range(3)]
            replay_rows.append({"global_step": step, "time_s": time_s, "prediction": pred, "correction": corr,
                                "source_prediction": source["motion"], "source_correction_state": source["ancf_state"],
                                "loads_N": loads, "worker_correction": correction})
            prior = loads; adapter.finalize_committed()
    finally:
        adapter.shutdown()
    errors = []
    for row in replay_rows:
        for sid in range(3):
            for field in ("ux_m", "uy_m", "vx_mps", "vy_mps", "ax_mps2", "ay_mps2"):
                errors.append(abs(float(row["prediction"][sid][field]) - float(row["source_prediction"][sid][field])))
    # Compare every replay correction state to its recorded state explicitly.
    state_errors = []
    for replay, source in zip(replay_rows, rows):
        # correction motion is the comparable local representation; source q is held in the detailed record.
        source_corr = corrected_motion(manifest, defs, H, source)
        for sid in range(3):
            for field in ("ux_m", "uy_m", "vx_mps", "vy_mps", "ax_mps2", "ay_mps2"):
                state_errors.append(abs(float(replay["correction"][sid][field]) - float(source_corr[sid][field])))
    result = {"STRUCTURE_PATH_REPLAY": "PASS" if max(errors + state_errors, default=math.inf) <= 1e-12 else "FAIL",
              "max_prediction_local_motion_error": max(errors, default=math.inf),
              "max_correction_local_motion_error": max(state_errors, default=math.inf),
              "steps": len(replay_rows), "worker_audit": worker.audit,
              "source_records_sha256": hashlib.sha256((SOURCE / "records.jsonl").read_bytes()).hexdigest()}
    write_json(OUT / "ancf_recorded_force_replay.json", result)
    write_json(REPLAY / "replay_rows.json", replay_rows)
    return result


if __name__ == "__main__":
    print(json.dumps({"ledger": ledger(), "structure_replay": replay_structure()}, ensure_ascii=False))
