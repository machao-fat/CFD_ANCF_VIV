"""Fresh, fail-closed preCICE structure participant for the 1 s force contract smoke."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
from pathlib import Path

from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker
from coupling.cpp_worker_confirm_v1.cpp_adapter import CppKernelCampaignAdapter
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelModel, KernelStepRequest
from coupling.moment_mapping_audit_v1.audit import audit as moment_audit
from coupling.multi_slice_mapping.mapping import (SliceDefinition, SliceManifest, LoadRecord,
    build_H_for_manifest, map_integrated_slice_forces, motion_from_ancf_state)
from coupling.three_slice_force_contract_smoke_v1.contract import bounded_midpoint_voronoi, finite_rows
from coupling.ancf_newton_evidence_v1 import make_record as make_newton_record, validate_records as validate_newton_records


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    temp.replace(path)


def append_jsonl(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def force_sum(value: object, count: int) -> tuple[float, float, float]:
    rows = value.tolist() if hasattr(value, "tolist") else value
    if not isinstance(rows, list) or len(rows) != count:
        raise RuntimeError(f"preCICE Force vertex count mismatch: expected {count}")
    result = [0.0, 0.0, 0.0]
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise RuntimeError("preCICE Force row is not a 2D vector")
        for component, item in enumerate(row):
            value_f = float(item)
            if not math.isfinite(value_f):
                raise RuntimeError("preCICE Force contains NaN/Inf")
            result[component] += value_f
    return tuple(result)


def model_from_contract(contract: dict[str, object]) -> KernelModel:
    ancf, cfd, slices = contract["ANCF"], contract["CFD"], contract["slices"]
    assert isinstance(ancf, dict) and isinstance(cfd, dict) and isinstance(slices, dict)
    items = slices["items"]
    assert isinstance(items, list)
    return KernelModel(length_m=float(ancf["length_m"]), diameter_m=float(ancf["diameter_m"]),
        inner_diameter_m=float(ancf["inner_diameter_m"]), elements=int(ancf["elements"]), slices=len(items),
        top_tension_N=float(ancf["top_tension_N"]), youngs_modulus_Pa=float(ancf["youngs_modulus_Pa"]),
        material_density=float(ancf["material_density_kgpm3"]), fluid_density=float(cfd["fluid_density_kgpm3"]),
        gravity=float(ancf["gravity_mps2"]), beta=float(ancf["newmark_beta"]), gamma=float(ancf["newmark_gamma"]),
        newton_tolerance=float(ancf["newton_tolerance"]), damping_alpha=float(ancf["damping_alpha"]),
        damping_beta=float(ancf["damping_beta"]), gauss_order=int(ancf["gauss_order"]),
        mass_gauss_order=int(ancf["mass_gauss_order"]), max_newton=int(ancf["max_newton_iterations"]),
        slice_positions_m=tuple(float(item["s_ref_m"]) for item in items))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True); parser.add_argument("--state", required=True)
    parser.add_argument("--worker", required=True); parser.add_argument("--runtime", required=True)
    parser.add_argument("--config", nargs=3, required=True); parser.add_argument("--vertex-count", type=int, required=True)
    args = parser.parse_args()
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    steps = contract.get("number_of_steps")
    dt_s = contract.get("dt_s")
    duration_s = contract.get("duration_s")
    if (isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0 or
            isinstance(dt_s, bool) or not isinstance(dt_s, (int, float)) or float(dt_s) <= 0.0 or
            isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)) or
            abs(float(duration_s) - int(steps) * float(dt_s)) > 1e-12 or state.get("equilibrated") is not True):
        raise RuntimeError("frozen run contract or fresh static state is invalid")
    if hashlib.sha256(Path(args.state).read_bytes()).hexdigest() != contract["ANCF"]["initial_state"]["sha256"]:
        raise RuntimeError("initial static state hash differs from frozen contract")
    items = contract["slices"]["items"]
    partition = bounded_midpoint_voronoi([item["s_ref_m"] for item in items], contract["slices"]["represented_interval_m"])
    definitions = tuple(SliceDefinition(int(item["slice_id"]), float(item["s_ref_m"]), right-left, float(item["unit_span_m"]))
                        for item, (left, _, right) in zip(items, partition))
    length_m, elements = float(contract["ANCF"]["length_m"]), int(contract["ANCF"]["elements"])
    manifest = SliceManifest("0.2.1", str(contract["case_id"]), length_m, length_m, definitions)
    H = build_H_for_manifest(manifest, tuple(length_m * index / elements for index in range(elements + 1)))
    model = model_from_contract(contract)
    q, qdot, qddot = (tuple(float(x) for x in state[key]) for key in ("q", "qdot", "qddot"))
    mass = tuple(float(x) for x in state["mass_matrix"]); base = tuple(float(x) for x in state["base_load"])
    model_hash = hashlib.sha256(model.bytes() + struct.pack("<" + "d" * len(mass), *mass)).hexdigest()
    runtime = Path(args.runtime); runtime.mkdir(parents=True, exist_ok=True)
    worker = KernelWorker(Path(args.worker), runtime / "cpp_worker", str(contract["run_id"]), str(contract["case_id"]),
                          expected_model_contract_sha256=model_hash)
    adapter = CppKernelCampaignAdapter(worker=worker, model=model, request_factory=KernelStepRequest,
        run_id=str(contract["run_id"]), case_id=str(contract["case_id"]), source_global_step=0, source_time_s=0.0,
        source_tick=0, dt_s=float(contract["dt_s"]), q=q, qdot=qdot, qddot=qddot, base_load=base,
        mass_matrix=mass, strict_numerical_contract=True, expected_model_contract_sha256=model_hash)
    import precice  # type: ignore
    radius = 0.5
    vertices = [(radius * math.cos(2.0 * math.pi * i / args.vertex_count), radius * math.sin(2.0 * math.pi * i / args.vertex_count)) for i in range(args.vertex_count)]
    participants = []; mesh_ids = []; records: list[dict[str, object]] = []; newton_records: list[dict[str, object]] = []; prior = [(0.0, 0.0, 0.0)] * 3
    error: str | None = None
    try:
        # ``CppKernelCampaignAdapter.start`` owns the only permissible worker start.
        adapter.start()
        for sid, config in enumerate(args.config):
            participant = precice.Participant(f"Structure_{sid:04d}", config, 0, 1)
            participants.append(participant); mesh_ids.append(participant.set_mesh_vertices("Structure-Mesh", vertices))
        for participant in participants: participant.initialize()
        for step in range(1, int(steps) + 1):
            time_s = step * float(dt_s); before = adapter.state_view()
            prediction, _ = adapter.predict(step, time_s, prior)
            predicted_q = tuple(prediction["predictor"]); predicted_qdot = tuple(prediction["predictor_qdot"]); predicted_qddot = tuple(prediction["predictor_qddot"])
            motion = [motion_from_ancf_state(manifest, sid, H[sid], predicted_q, predicted_qdot, predicted_qddot,
                      step=step, time_s=time_s, reference_position_m=(0.0, 0.0, definitions[sid].s_ref_m)) for sid in range(3)]
            for sid, participant in enumerate(participants):
                participant.write_data("Structure-Mesh", "Displacement", mesh_ids[sid], [[motion[sid].ux_m, motion[sid].uy_m] for _ in vertices])
            for participant in participants: participant.advance(float(dt_s))
            loads = []
            for sid, participant in enumerate(participants):
                raw = force_sum(participant.read_data("Structure-Mesh", "Force", mesh_ids[sid], 0.0), args.vertex_count)
                loads.append(LoadRecord.from_conversion(case_id=manifest.case_id, step=step, time_s=time_s,
                    slice_definition=definitions[sid], unit_span_m=definitions[sid].unit_span_m,
                    openfoam_force_N=raw, cfd_time_step_s=float(dt_s), R_GL=manifest.R_GL))
            mapping = map_integrated_slice_forces(manifest, H, {item.slice_id: item for item in loads},
                delta_q=tuple(predicted_q[i] - before["q"][i] for i in range(len(predicted_q))))
            audit = moment_audit(predicted_q, [item.force_N for item in loads], positions_m=[item.s_ref_m for item in definitions],
                length_m=length_m, elements=elements, delta_q=tuple(predicted_q[i] - before["q"][i] for i in range(len(predicted_q))), compensated=True)
            correction, _ = adapter.correct(step, time_s, [item.force_N for item in loads])
            # v1 C++ protocol labels this slot ``generalized_force``, but its
            # frozen wire semantics are total Qext = base_load + H^T F_CFD.
            # Compare like-with-like, and retain both representations.
            cpp_cfd_generalized_force = tuple(float(value) - base[index] for index, value in enumerate(correction["generalized_force"]))
            correction["cpp_generalized_force_semantics"] = "total_Qext_N=base_load_N+H_transpose_integrated_slice_force_N"
            correction["cpp_cfd_generalized_force_N"] = list(cpp_cfd_generalized_force)
            if max(abs(a-b) for a, b in zip(mapping.generalized_force, cpp_cfd_generalized_force)) > 1e-8:
                raise RuntimeError("C++ generalized force differs from formal H^T mapping")
            for record in motion:
                if max(abs(record.x_m-record.x_ref_m-record.ux_m), abs(record.y_m-record.y_ref_m-record.uy_m), abs(record.z_m-record.z_ref_m-record.uz_m)) > 1e-12:
                    raise RuntimeError("absolute position/reference/displacement identity failed")
            prediction_newton = make_newton_record(run_id=str(contract["run_id"]), case_id=str(contract["case_id"]),
                global_step=step, time_s=time_s, integer_tick=int(prediction["integer_tick"]), phase="prediction",
                transport_sequence=int(prediction["transport_sequence"]), correction_sequence=None, diagnostics=prediction,
                state={"q": predicted_q, "qdot": predicted_qdot, "qddot": predicted_qddot},
                max_newton_iterations=int(contract["ANCF"]["max_newton_iterations"]))
            corrected_state = adapter.state_view()
            correction_newton = make_newton_record(run_id=str(contract["run_id"]), case_id=str(contract["case_id"]),
                global_step=step, time_s=time_s, integer_tick=int(correction["integer_tick"]), phase="correction",
                transport_sequence=int(correction["transport_sequence"]), correction_sequence=int(correction["transport_sequence"]), diagnostics=correction,
                state=corrected_state, max_newton_iterations=int(contract["ANCF"]["max_newton_iterations"]))
            row = {"global_step": step, "case_local_step": step, "time_s": time_s, "integer_tick": int(round(time_s*1e9)),
                "motion": [item.to_dict() for item in motion], "loads": [item.to_dict() for item in loads],
                "mapping": mapping.to_dict(), "moment_audit": audit, "prediction": prediction, "correction": correction,
                "ancf_state": corrected_state, "newton_evidence": [prediction_newton, correction_newton], "committed": True}
            append_jsonl(runtime / "records.jsonl", row)
            append_jsonl(runtime / "newton_evidence.jsonl", prediction_newton)
            append_jsonl(runtime / "newton_evidence.jsonl", correction_newton)
            records.append(row); newton_records.extend((prediction_newton, correction_newton)); prior = [item.force_N for item in loads]; adapter.finalize_committed()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        for participant in participants:
            try: participant.finalize()
            except Exception as exc: error = error or f"preCICE finalize: {exc}"
        adapter.shutdown()
    try:
        newton_validation = validate_newton_records(newton_records, expected_steps=int(steps))
    except Exception as exc:
        newton_validation = {"status": "fail", "error": f"{type(exc).__name__}: {exc}"}
        error = error or f"Newton evidence validation: {newton_validation['error']}"
    atomic_json(runtime / "structure_summary.json", {"run_id": contract["run_id"], "case_id": contract["case_id"],
        "status": "completed" if error is None and len(records) == int(steps) else "failed", "error": error,
        "committed_steps": len(records), "slice_record_counts": {
            str(sid): sum(1 for row in records if any(int(load["slice_id"]) == sid for load in row["loads"]))
            for sid in range(3)
        },
        "cpp_worker": worker.audit, "adapter_responses": adapter.responses, "newton_evidence": newton_validation, "owned_residual": adapter.owned_residual,
        "tributary_partition_m": [{"slice_id": sid, "left": left, "right": right, "length": right-left} for sid,(left,_,right) in enumerate(partition)]})
    return 0 if error is None and len(records) == int(steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
