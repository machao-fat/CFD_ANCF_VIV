"""Checkpoint-aware production structure participant for preCICE parallel-implicit FSI.

Physical ANCF state is restored on a preCICE rollback; transport identities are
deliberately never restored.  This file is separate from the frozen explicit
participant so the explicit path remains an independently reproducible binary
input to its historical evidence.
"""
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
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest
from coupling.moment_mapping_audit_v1.audit import audit as moment_audit
from coupling.multi_slice_mapping.mapping import (LoadRecord, SliceDefinition,
    SliceManifest, build_H_for_manifest, map_integrated_slice_forces,
    motion_from_ancf_state)
from coupling.three_slice_force_contract_smoke_v1.contract import bounded_midpoint_voronoi
from coupling.ancf_newton_evidence_v1 import make_record, validate_records
from coupling.generalized_force_metric_v2 import evaluate as evaluate_gf_v2


def canonical(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                       allow_nan=False).encode("utf-8")).hexdigest()


# Structure-Mesh is the frozen 2D x/y preCICE interface.  z remains part of
# the full ANCF state, but is not an exchanged Displacement component.
INTERFACE_COMPONENTS = ("ux_m", "uy_m")
INITIAL_INTERFACE_ZERO_TOLERANCE_M = 1.0e-12


def validate_frozen_no_flow_state(state: dict[str, object], state_path: Path,
                                  expected_sha256: str) -> None:
    """Validate the complete frozen ANCF state independently of its interface projection."""
    if state.get("equilibrated") is not True:
        raise RuntimeError("NO_FLOW_EQUILIBRIUM state is not marked equilibrated")
    if hashlib.sha256(state_path.read_bytes()).hexdigest() != expected_sha256:
        # This protects all physical DOFs, including untransmitted z, against
        # silently substituting a state to satisfy an interface-only guard.
        raise RuntimeError("frozen no-flow ANCF state provenance/hash mismatch")
    for name in ("q", "qdot", "qddot"):
        values = state.get(name)
        if not isinstance(values, list) or not values or not all(math.isfinite(float(value)) for value in values):
            raise RuntimeError(f"frozen no-flow ANCF {name} is absent or non-finite")


def projected_interface_payload(motion: object, vertex_count: int) -> list[list[float]]:
    """Project a full ANCF motion onto the actual 2D Structure-Mesh contract."""
    if vertex_count <= 0:
        raise RuntimeError("Structure-Mesh vertex count must be positive")
    values = [[float(getattr(motion, component)) for component in INTERFACE_COMPONENTS]
              for _ in range(vertex_count)]
    if len(values) != vertex_count or any(len(row) != 2 or not all(math.isfinite(item) for item in row) for row in values):
        raise RuntimeError("initial Displacement shape/dtype/finite validation fails")
    return values


def validate_zero_projected_initial_interface(payload: object, vertex_ids: object,
                                              expected_vertex_count: int) -> None:
    """Enforce zero only for the transmitted x/y initial Displacement array."""
    if not isinstance(payload, list) or not hasattr(vertex_ids, "__len__"):
        raise RuntimeError("initial Displacement payload/vertex IDs are malformed")
    if len(payload) != expected_vertex_count or len(vertex_ids) != expected_vertex_count:
        raise RuntimeError("initial Displacement vertex count/order mismatch")
    for row in payload:
        if not isinstance(row, list) or len(row) != 2 or not all(math.isfinite(float(item)) for item in row):
            raise RuntimeError("initial Displacement shape/dtype/finite validation fails")
        if max(abs(float(item)) for item in row) > INITIAL_INTERFACE_ZERO_TOLERANCE_M:
            raise RuntimeError("NO_FLOW_EQUILIBRIUM does not map to zero projected x/y interface displacement")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as out:
        json.dump(value, out, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        out.write("\n"); out.flush(); os.fsync(out.fileno())
    os.replace(tmp, path)


def append_jsonl(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as out:
        out.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        out.flush(); os.fsync(out.fileno())


def force_sum(value: object, count: int) -> tuple[float, float, float]:
    rows = value.tolist() if hasattr(value, "tolist") else value
    if not isinstance(rows, list) or len(rows) != count:
        raise RuntimeError(f"preCICE Force vertex count mismatch: expected {count}")
    answer = [0.0, 0.0, 0.0]
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise RuntimeError("preCICE Force row is not a 2D vector")
        for i, item in enumerate(row):
            item = float(item)
            if not math.isfinite(item): raise RuntimeError("preCICE force contains NaN/Inf")
            answer[i] += item
    return tuple(answer)


def model_from_contract(contract: dict[str, object]):
    ancf, cfd, slices = contract["ANCF"], contract["CFD"], contract["slices"]
    from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelModel
    assert isinstance(ancf, dict) and isinstance(cfd, dict) and isinstance(slices, dict)
    items = slices["items"]; assert isinstance(items, list)
    return KernelModel(length_m=float(ancf["length_m"]), diameter_m=float(ancf["diameter_m"]),
        inner_diameter_m=float(ancf["inner_diameter_m"]), elements=int(ancf["elements"]), slices=len(items),
        top_tension_N=float(ancf["top_tension_N"]), youngs_modulus_Pa=float(ancf["youngs_modulus_Pa"]),
        material_density=float(ancf["material_density_kgpm3"]), fluid_density=float(cfd["fluid_density_kgpm3"]),
        gravity=float(ancf["gravity_mps2"]), beta=float(ancf["newmark_beta"]), gamma=float(ancf["newmark_gamma"]),
        newton_tolerance=float(ancf["newton_tolerance"]), damping_alpha=float(ancf["damping_alpha"]),
        damping_beta=float(ancf["damping_beta"]), gauss_order=int(ancf["gauss_order"]),
        mass_gauss_order=int(ancf["mass_gauss_order"]), max_newton=int(ancf["max_newton_iterations"]),
        slice_positions_m=tuple(float(x["s_ref_m"]) for x in items))


class PhysicalCheckpoint:
    """Physical state only.  The adapter monotonic wire sequence is excluded."""
    schema = "structure-participant-checkpoint-schema-v1"
    def __init__(self, runtime: Path, adapter: CppKernelCampaignAdapter):
        self.runtime, self.adapter = runtime, adapter
        self.value: dict[str, object] | None = None
        self.path: Path | None = None

    def write(self, window: int, tau: float, prior: list[tuple[float, float, float]],
              committed_steps: int, local: dict[str, object]) -> dict[str, object]:
        if self.value is not None: raise RuntimeError("checkpoint already active in physical window")
        checkpoint_id = f"window_{window:06d}_checkpoint"
        self.path = self.runtime / "checkpoints" / f"{checkpoint_id}.cpp.json"
        self.adapter.save_checkpoint(self.path)
        physical = {"adapter_state": self.adapter.state_view(), "previous_slice_forces_N": prior,
                    "committed_steps": committed_steps, "coupling_tau_s": tau, "window_local": local}
        self.value = {"schema_version": self.schema, "checkpoint_id": checkpoint_id,
                      "window_index": window, "physical": physical,
                      "physical_state_sha256": canonical(physical),
                      "non_restorable_identity": ["wire_request_id", "transaction_id", "transport_sequence", "attempt_id"]}
        write_json(self.runtime / "checkpoints" / f"{checkpoint_id}.json", self.value)
        return self.value

    def restore(self) -> dict[str, object]:
        if self.value is None or self.path is None: raise RuntimeError("preCICE requested restore without checkpoint")
        before = self.adapter.state_view(); self.adapter.load_checkpoint(self.path)
        physical = self.value["physical"]; assert isinstance(physical, dict)
        restored = self.adapter.state_view(); expected = physical["adapter_state"]
        if restored != expected: raise RuntimeError("C++ physical state differs after checkpoint restore")
        return {"before_restore_state_sha256": canonical(before),
                "checkpoint_state_sha256": canonical(expected), "post_restore_state_sha256": canonical(restored),
                "physical": physical}

    def commit(self) -> None:
        if self.value is None: raise RuntimeError("committing implicit window without checkpoint")
        self.value = None; self.path = None


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--contract", required=True); p.add_argument("--state", required=True)
    p.add_argument("--worker", required=True); p.add_argument("--runtime", required=True)
    p.add_argument("--config", required=True, nargs=3); p.add_argument("--vertex-count", required=True, type=int)
    args = p.parse_args(); contract = json.loads(Path(args.contract).read_text(encoding="utf-8")); state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    dt, steps = float(contract["dt_s"]), int(contract["number_of_steps"])
    if steps != 1 or abs(float(contract["duration_s"])-dt) > 1e-12: raise RuntimeError("one-window contract required")
    validate_frozen_no_flow_state(state, Path(args.state), str(contract["ANCF"]["initial_state"]["sha256"]))
    items = contract["slices"]["items"]; assert isinstance(items, list)
    partition = bounded_midpoint_voronoi([x["s_ref_m"] for x in items], contract["slices"]["represented_interval_m"])
    definitions = tuple(SliceDefinition(int(x["slice_id"]), float(x["s_ref_m"]), right-left, float(x["unit_span_m"])) for x, (left, _, right) in zip(items, partition))
    length, elements = float(contract["ANCF"]["length_m"]), int(contract["ANCF"]["elements"])
    manifest = SliceManifest("0.2.1", str(contract["case_id"]), length, length, definitions)
    H = build_H_for_manifest(manifest, tuple(length * i / elements for i in range(elements+1)))
    model = model_from_contract(contract); q, qdot, qddot = (tuple(float(x) for x in state[k]) for k in ("q", "qdot", "qddot"))
    mass, base = tuple(float(x) for x in state["mass_matrix"]), tuple(float(x) for x in state["base_load"])
    model_hash = hashlib.sha256(model.bytes()+struct.pack("<"+"d"*len(mass), *mass)).hexdigest()
    runtime = Path(args.runtime); runtime.mkdir(parents=True, exist_ok=True)
    worker = KernelWorker(Path(args.worker), runtime/"cpp_worker", str(contract["run_id"]), str(contract["case_id"]), expected_model_contract_sha256=model_hash, allow_implicit_retry=True)
    adapter = CppKernelCampaignAdapter(worker=worker, model=model, request_factory=KernelStepRequest, run_id=str(contract["run_id"]), case_id=str(contract["case_id"]), source_global_step=0, source_time_s=0., source_tick=0, dt_s=dt, q=q, qdot=qdot, qddot=qddot, base_load=base, mass_matrix=mass, strict_numerical_contract=True, expected_model_contract_sha256=model_hash, implicit_rollback_transport=True)
    import precice  # deployed 3.4 binding; required checkpoint methods are API-audited before launch
    vertices=[(.5*math.cos(2*math.pi*i/args.vertex_count), .5*math.sin(2*math.pi*i/args.vertex_count)) for i in range(args.vertex_count)]
    participants=[]; meshids=[]; evidence=[]; records=[]; newton=[]; prior=[(0.,0.,0.)]*3; cp=PhysicalCheckpoint(runtime, adapter); error=None; window=1; iteration=0
    try:
        adapter.start()
        for sid, config in enumerate(args.config):
            participant=precice.Participant(f"Structure_{sid:04d}", config, 0, 1); participants.append(participant); meshids.append(participant.set_mesh_vertices("Structure-Mesh",vertices))
        # preCICE initial data is a separate protocol layer.  It is derived
        # from the frozen no-flow state rather than from a later prediction or
        # an uninitialised transport buffer.
        initial_motion = [motion_from_ancf_state(
            manifest, sid, H[sid], q, qdot, qddot, step=0, time_s=0.0,
            reference_position_m=(0.0, 0.0, definitions[sid].s_ref_m),
        ) for sid in range(3)]
        initial_state_sha256 = hashlib.sha256(Path(args.state).read_bytes()).hexdigest()
        for sid, participant in enumerate(participants):
            motion0 = initial_motion[sid]
            values = projected_interface_payload(motion0, args.vertex_count)
            # The zero-geometry precursor has a 2D x/y interface.  Keep the
            # full-state z component observable, but do not treat it as a
            # third transmitted interface component.
            validate_zero_projected_initial_interface(values, meshids[sid], args.vertex_count)
            required = participant.requires_initial_data()
            initial_evidence = {"event":"initial_data_write","slice_id":sid,"required":required,
                "mesh_name":"Structure-Mesh","data_name":"Displacement","units":"m",
                "vertex_count":args.vertex_count,"components":2,"vertex_order":"registered Structure-Mesh order",
                "initial_state_sha256":initial_state_sha256,"displacement_xy_m":values[0],
                "untransmitted_uz_m":float(motion0.uz_m),"projection":"P_xy[r(q)-r_reference]",
                "payload_sha256":canonical(values)}
            if required:
                participant.write_data("Structure-Mesh","Displacement",meshids[sid],values)
                initial_evidence["written"] = True
            else:
                initial_evidence["written"] = False
            append_jsonl(runtime/"initial_data_evidence.jsonl", initial_evidence)
        for participant in participants: participant.initialize()
        while any(participant.is_coupling_ongoing() for participant in participants):
            flags_w=[participant.requires_writing_checkpoint() for participant in participants]
            flags_r=[participant.requires_reading_checkpoint() for participant in participants]
            if len(set(flags_w)) != 1 or len(set(flags_r)) != 1: raise RuntimeError("slice checkpoint requests disagree")
            if flags_w[0]:
                checkpoint=cp.write(window, 0., prior, len(records), {"iteration_before_write": iteration})
                append_jsonl(runtime/"implicit_iterations.jsonl", {"event":"checkpoint_write","window_index":window,"iteration_index":iteration,"checkpoint":checkpoint})
            if cp.value is None: raise RuntimeError("implicit trial without physical checkpoint")
            iteration += 1; before=adapter.state_view(); predicted,_=adapter.predict(window, dt, prior)
            pq,pv,pa=(tuple(predicted[k]) for k in ("predictor","predictor_qdot","predictor_qddot"))
            motion=[motion_from_ancf_state(manifest,sid,H[sid],pq,pv,pa,step=window,time_s=dt,reference_position_m=(0.,0.,definitions[sid].s_ref_m)) for sid in range(3)]
            for sid,participant in enumerate(participants): participant.write_data("Structure-Mesh","Displacement",meshids[sid],[[motion[sid].ux_m,motion[sid].uy_m] for _ in vertices])
            for participant in participants: participant.advance(dt)
            loads=[]
            for sid,participant in enumerate(participants):
                raw=force_sum(participant.read_data("Structure-Mesh","Force",meshids[sid],0.0),args.vertex_count)
                loads.append(LoadRecord.from_conversion(case_id=manifest.case_id,step=window,time_s=dt,slice_definition=definitions[sid],unit_span_m=definitions[sid].unit_span_m,openfoam_force_N=raw,cfd_time_step_s=dt,R_GL=manifest.R_GL))
            mapping=map_integrated_slice_forces(manifest,H,{x.slice_id:x for x in loads},delta_q=tuple(pq[i]-before["q"][i] for i in range(len(pq))))
            pre={"event":"pre_cpp_correction","window_index":window,"iteration_index":iteration,"physical_tau_target_s":dt,"state_sha256":canonical(before),"prediction_state_sha256":canonical({"q":pq,"qdot":pv,"qddot":pa}),"forces_N":[list(x.force_N) for x in loads],"H_by_slice":{str(s):[list(r) for r in H[s]] for s in range(3)},"Q_formal_N":list(mapping.generalized_force),"checkpoint_id":cp.value["checkpoint_id"]}
            append_jsonl(runtime/"implicit_iterations.jsonl",pre)
            correction,_=adapter.correct(window,dt,[x.force_N for x in loads])
            qcpp=tuple(float(x)-base[i] for i,x in enumerate(correction["generalized_force"])); metric=evaluate_gf_v2(mapping.generalized_force,qcpp,mapping.slice_contributions,contract=contract["generalized_force_metric_v2"])
            attempt={**pre,"event":"post_cpp_correction","wire_request_id":correction["request_id"],"wire_sequence":correction["wire_sequence"],"transport_sequence":correction["transport_sequence"],"Q_cpp_cfd_N":list(qcpp),"generalized_force_metric_v2":metric,"post_trial_state_sha256":canonical(adapter.state_view()),"rollback_requested":None}
            append_jsonl(runtime/"implicit_iterations.jsonl",attempt)
            if metric["GENERALIZED_FORCE_MAPPING_V2"] != "PASS": raise RuntimeError("Generalized Force Metric V2 fails")
            flags_r=[participant.requires_reading_checkpoint() for participant in participants]
            if len(set(flags_r)) != 1: raise RuntimeError("slice rollback requests disagree")
            if flags_r[0]:
                restored=cp.restore(); attempt["rollback_requested"]=True; attempt.update(restored); append_jsonl(runtime/"implicit_iterations.jsonl",{**attempt,"event":"checkpoint_restore"})
                physical=restored["physical"]; assert isinstance(physical,dict); prior=[tuple(x) for x in physical["previous_slice_forces_N"]]
                continue
            if iteration < int(contract["implicit_convergence"]["min_iterations"]): raise RuntimeError("preCICE converged before frozen minimum implicit iterations")
            if iteration > int(contract["implicit_convergence"]["max_iterations"]): raise RuntimeError("implicit iteration exceeded frozen maximum")
            corrected=adapter.state_view(); audit=moment_audit(pq,[x.force_N for x in loads],positions_m=[x.s_ref_m for x in definitions],length_m=length,elements=elements,delta_q=tuple(pq[i]-before["q"][i] for i in range(len(pq))),compensated=True)
            pred_n=make_record(run_id=str(contract["run_id"]),case_id=str(contract["case_id"]),global_step=window,time_s=dt,integer_tick=int(predicted["integer_tick"]),phase="prediction",transport_sequence=int(predicted["transport_sequence"]),correction_sequence=None,diagnostics=predicted,state={"q":pq,"qdot":pv,"qddot":pa},max_newton_iterations=int(contract["ANCF"]["max_newton_iterations"]))
            corr_n=make_record(run_id=str(contract["run_id"]),case_id=str(contract["case_id"]),global_step=window,time_s=dt,integer_tick=int(correction["integer_tick"]),phase="correction",transport_sequence=int(correction["transport_sequence"]),correction_sequence=int(correction["transport_sequence"]),diagnostics=correction,state=corrected,max_newton_iterations=int(contract["ANCF"]["max_newton_iterations"]))
            row={"global_step":window,"time_s":dt,"integer_tick":int(round(dt*1e9)),"implicit_iteration_final":iteration,"motion":[x.to_dict() for x in motion],"loads":[x.to_dict() for x in loads],"mapping":mapping.to_dict(),"moment_audit":audit,"prediction":predicted,"correction":correction,"ancf_state":corrected,"newton_evidence":[pred_n,corr_n],"committed":True}
            append_jsonl(runtime/"records.jsonl",row); append_jsonl(runtime/"newton_evidence.jsonl",pred_n); append_jsonl(runtime/"newton_evidence.jsonl",corr_n); records.append(row); newton += [pred_n,corr_n]; prior=[x.force_N for x in loads]; adapter.finalize_committed(); cp.commit()
            break
    except Exception as exc: error=f"{type(exc).__name__}: {exc}"
    finally:
        for participant in participants:
            try: participant.finalize()
            except Exception as exc: error=error or f"preCICE finalize: {exc}"
        adapter.shutdown()
    try: newton_status=validate_records(newton,expected_steps=1)
    except Exception as exc: newton_status={"status":"fail","error":str(exc)}
    write_json(runtime/"structure_summary.json",{"status":"completed" if error is None and len(records)==1 else "failed","error":error,"committed_steps":len(records),"coupling_iterations":iteration,"checkpoint_schema":PhysicalCheckpoint.schema,"wire_identity_policy":"monotonic and non-restorable across rollback","adapter_responses":adapter.responses,"cpp_worker":worker.audit,"newton_evidence":newton_status})
    return 0 if error is None and len(records)==1 else 1

if __name__ == "__main__": raise SystemExit(main())
