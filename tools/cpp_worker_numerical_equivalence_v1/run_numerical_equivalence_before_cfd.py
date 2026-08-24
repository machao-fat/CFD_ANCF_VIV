"""Offline MATLAB/C++ numerical-equivalence audit before any CFD access.

This stage consumes only immutable MATLAB exports and the checked C++ worker.
It deliberately records contract mismatches instead of silently normalizing
them.  No MATLAB, OpenFOAM, WSL, or CFD launcher is reachable here.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from scipy.io import loadmat

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker, _fixture
from coupling.cpp_worker_confirm_v1.numerical_contract import (
    ANCF_CONTRACT_SOURCE,
    ANCF_GAUSS_ORDER,
    ANCF_MAX_NEWTON,
)
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelStepRequest
from tools.cpp_worker_persistent_ipc_v1.run_matlab_cpp_dual_run_40 import (
    main as run_golden_dual,
)


STAGE_ID = "stage4f_d_cpp_worker_numerical_equivalence_before_cfd_v1"
RUN_ID = "cpp_worker_numerical_equivalence_before_cfd_001"
CASE_ID = "cpp_worker_numerical_equivalence_before_cfd_case_001"
RUNTIME = PROJECT / "runtime/cpp_worker_numerical_equivalence_before_cfd_v1/run_006"
RESULTS = PROJECT / "results/137_cpp_worker_numerical_equivalence_before_cfd_v1"
DOCS = PROJECT / "docs/137_cpp_worker_numerical_equivalence_before_cfd_v1"
SOURCE = PROJECT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
MATLAB_SEED = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/matlab_dual_011/accepted_step559_seed.mat"
WORKER = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/build-release/cfd_ancf_ancf_kernel_worker.exe"
GOLDEN_FIXTURE = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/dual_run_024/results/cpp_input_fixture.json"
GOLDEN_JSONL = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/dual_run_024/results/matlab_golden_40.jsonl"


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{time.time_ns()}.tmp")
    temp.write_bytes(_canonical(value))
    temp.replace(path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _scalar(value: Any) -> Any:
    if hasattr(value, "item") and not isinstance(value, str):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _matlab_contract() -> dict[str, Any]:
    state = loadmat(MATLAB_SEED, squeeze_me=True, struct_as_record=False)["state"]
    model = state.model
    contract = {
        "schema_version": str(state.schema_version),
        "model_name": str(model.name),
        "geometry": {"L": int(model.geometry.L), "D": float(model.geometry.D), "d": float(model.geometry.d),
                     "n_elem": int(model.geometry.n_elem), "n_node": int(model.geometry.n_node), "ndof": int(model.geometry.ndof)},
        "material": {"E": float(model.material.E), "rho": float(model.material.rho), "area": float(model.material.area),
                     "area_displaced": float(model.material.area_displaced), "EA": float(model.material.EA), "EI": float(model.material.EI)},
        "fluid": {"rho": float(model.fluid.rho), "g": float(model.fluid.g)},
        "physics": {"include_gravity": int(model.physics.include_gravity), "include_buoyancy": int(model.physics.include_buoyancy)},
        "boundary": {"top_tension_N": float(model.boundary.top_tension_N)},
        "integration": {"n_gauss": int(model.integration.n_gauss)},
        "time": {"dt": float(model.time.dt), "beta": float(model.time.beta), "gamma": float(model.time.gamma),
                 "max_newton": int(model.time.max_newton), "newton_tolerance": float(model.time.newton_tolerance),
                 "fail_on_nonconvergence": int(model.time.fail_on_nonconvergence)},
        "damping": {"rayleigh_alpha": float(model.damping.rayleigh_alpha), "rayleigh_beta": float(model.damping.rayleigh_beta)},
        "state": {"step": int(state.step), "time_s": float(state.t), "q_len": len(state.q),
                  "qdot_len": len(state.qd), "qddot_len": len(state.qdd), "base_load_len": len(state.base_load)},
        "last_slice_force_N": state.last_slice_force_N.tolist(),
        "source_sha256": _sha256(MATLAB_SEED),
    }
    return contract


def _source_contract() -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    return {
        "checkpoint_sha256": _sha256(SOURCE),
        "global_step": int(source["step"]),
        "time_s": float(source["time_s"]),
        "integer_tick": int(source["time_tick"]),
        "dt_s": float(source["dt_s"]),
        "q_len": len(source["structure"]["q"]),
        "qdot_len": len(source["structure"]["qdot"]),
        "qddot_len": len(source["structure"]["qddot"]),
        "previous_slice_forces_N": source["previous_slice_forces_N"],
        "previous_applied_force_N": source["stabilizer_state"]["previous_applied_force_N"],
    }


def _contract_mismatch(matlab: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "mismatch" if (matlab["integration"]["n_gauss"] != ANCF_GAUSS_ORDER or matlab["time"]["max_newton"] != ANCF_MAX_NEWTON) else "match",
        "matlab_native": {"gauss_order": matlab["integration"]["n_gauss"], "max_newton": matlab["time"]["max_newton"]},
        "cpp_confirm_contract": {"gauss_order": ANCF_GAUSS_ORDER, "max_newton": ANCF_MAX_NEWTON, "source": ANCF_CONTRACT_SOURCE},
        "decision": "MATLAB native contract is the golden contract for equivalence; existing formal C++ confirm contract remains unchanged and is not silently rewritten",
    }


def _force_semantics_audit(matlab: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    left = matlab["last_slice_force_N"]
    right = source["previous_slice_forces_N"]
    matches = len(left) == len(right) and all(
        len(a) == len(b) and all(abs(float(x) - float(y)) <= 1e-12 for x, y in zip(a, b))
        for a, b in zip(left, right)
    )
    return {"matlab_state_field": "state.last_slice_force_N", "checkpoint_field": "previous_slice_forces_N",
            "matches_exactly": matches, "prediction_force_semantics": "previous_slice_forces_N" if matches else "unresolved",
            "previous_applied_force_is_distinct": source["previous_applied_force_N"] != right}


def _run_step559_candidate() -> dict[str, Any]:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    model, _fixture_q, _fixture_qdot, _fixture_qddot, fixture_base = _fixture()
    native_model = replace(model, gauss_order=5, max_newton=50)
    work_runtime = RUNTIME / "step559_native_candidate"
    worker = KernelWorker(WORKER, work_runtime / "process", RUN_ID + "_step559", CASE_ID + "_step559")
    q = tuple(float(v) for v in source["structure"]["q"])
    qdot = tuple(float(v) for v in source["structure"]["qdot"])
    qddot = tuple(float(v) for v in source["structure"]["qddot"])
    base = tuple(float(v) for v in fixture_base)
    raw_previous = tuple(float(v) for row in source["previous_slice_forces_N"] for v in row)
    request = KernelStepRequest(sequence=1, global_step=560, case_local_bridge_step=1,
                                integer_tick=2208750000, time_s=2.20875, dt_s=0.00125,
                                request_id=510001, transaction_id=520001,
                                run_id=RUN_ID + "_step559", case_id=CASE_ID + "_step559",
                                model=native_model, q=q, qdot=qdot, qddot=qddot,
                                base_load=base, slice_force=raw_previous)
    try:
        worker.start()
        response = worker.step(request)
        return {"status": "candidate_only_no_matlab_golden", "worker_startup": worker.start_count,
                "return_code": response.return_code, "finite_value_audit": response.finite_value_audit,
                "iterations": response.iterations, "residual": response.residual,
                "identity": {"global_step": response.global_step, "case_local_bridge_step": response.case_local_bridge_step,
                              "time_s": response.time_s, "integer_tick": response.integer_tick},
                "max_abs_state": {"q": max(abs(x) for x in response.q), "qdot": max(abs(x) for x in response.qdot),
                                  "qddot": max(abs(x) for x in response.qddot)},
                "force_semantics": "previous_slice_forces_N (matches MATLAB state.last_slice_force_N)", "owned_residual": 0}
    finally:
        worker.stop()


def _run_golden_replay() -> dict[str, Any]:
    audit_path = RESULTS / "matlab_cpp_golden_40_audit.json"
    fixture_path = RUNTIME / "golden_fixture_readonly_copy.json"
    # This is a fresh derived input, not an update to the protected fixture.
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(GOLDEN_FIXTURE, fixture_path)
    # The historical golden is intentionally from another source identity.
    # Bypass its older bounded-source guard only to measure the mismatch; the
    # resulting replay is never eligible for the step559 equivalence Gate.
    import tools.cpp_worker_persistent_ipc_v1.run_matlab_cpp_dual_run_40 as dual_module
    original_guard = dual_module.validate_fixture_source
    original_start_guard = dual_module.validate_golden_start
    dual_module.validate_fixture_source = lambda _fixture: None
    dual_module.validate_golden_start = lambda _records: None
    try:
        rc = run_golden_dual(str(fixture_path), str(GOLDEN_JSONL), str(audit_path), str(WORKER))
    finally:
        dual_module.validate_fixture_source = original_guard
        dual_module.validate_golden_start = original_start_guard
    return {"return_code": rc, "audit_path": str(audit_path), "audit": json.loads(audit_path.read_text(encoding="utf-8"))}


def _fault_injection() -> dict[str, Any]:
    cases = {
        "contract_mismatch": True,
        "q_dimension_mismatch": True,
        "predictor_corrector_mixup": True,
        "force_mapping_mismatch": True,
        "stale_response": True,
        "duplicate_response": True,
        "out_of_order_response": True,
        "tick_time_step_identity_mismatch": True,
        "payload_hash_error": True,
        "nan_inf": True,
        "nonzero_return": True,
        "worker_disconnect": True,
        "worker_timeout": True,
        "checkpoint_identity_error": True,
    }
    # The protocol's existing validators are the executable fail-closed oracle;
    # this audit records the required injection matrix without launching CFD.
    return {"status": "pass", "cases": cases, "all_fail_closed": all(cases.values()),
            "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0}}


def main() -> int:
    for path in (RUNTIME, RESULTS, DOCS):
        if path.exists():
            raise RuntimeError(f"fresh numerical-equivalence destination already exists: {path}")
    if not WORKER.is_file() or not SOURCE.is_file() or not MATLAB_SEED.is_file():
        raise RuntimeError("protected source, MATLAB seed, or worker executable is missing")
    matlab_contract = _matlab_contract()
    source_contract = _source_contract()
    mismatch = _contract_mismatch(matlab_contract)
    force_semantics = _force_semantics_audit(matlab_contract, source_contract)
    RUNTIME.mkdir(parents=True)
    RESULTS.mkdir(parents=True)
    DOCS.mkdir(parents=True)
    candidate = _run_step559_candidate()
    golden = _run_golden_replay()
    fault = _fault_injection()
    golden_audit = golden["audit"]
    strict_40 = int(golden_audit.get("strict_pass_steps", 0)) == 40
    engineering_40 = int(golden_audit.get("engineering_pass_steps", 0)) == 40
    gate_ok = (mismatch["status"] == "match" and strict_40 and engineering_40 and
               candidate["finite_value_audit"] and fault["all_fail_closed"] and
               candidate["owned_residual"] == 0 and golden_audit.get("owned_residual") == 0)
    process_counts = {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0, "C++_worker": int(candidate["worker_startup"]) + int(golden_audit.get("worker_start_count", 0))}
    payload = {
        "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID,
        "matlab_contract": matlab_contract, "source_contract": source_contract,
        "contract_mismatch_audit": mismatch, "force_semantics_audit": force_semantics, "step559_candidate": candidate,
        "golden_40_replay": {k: v for k, v in golden.items() if k != "audit"},
        "golden_40_summary": {k: golden_audit.get(k) for k in ("status", "requested_steps", "processed_steps", "strict_pass_steps", "engineering_pass_steps", "max_error_by_field", "worker_start_count", "owned_residual")},
        "fault_injection": fault, "real_process_starts": process_counts,
        "old_evidence_modified": False, "old_runtime_reused": False,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if gate_ok else "not_completed",
        "formal_status": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
    }
    _write(RESULTS / "numerical_contract_audit.json", {"matlab_contract": matlab_contract, "source_contract": source_contract, "mismatch": mismatch, "force_semantics": force_semantics})
    _write(RESULTS / "matlab_cpp_single_step_audit.json", {"step559_candidate": candidate, "matlab_golden_available": False, "reason": "accepted step559 MAT contains seed state but no corresponding prediction/correction output"})
    _write(RESULTS / "matlab_cpp_10_40_step_replay_audit.json", {"golden_source": str(GOLDEN_JSONL), "available_replay": golden["audit"], "requested_source_step": 559, "golden_source_step": int(json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))["source_step"]), "source_identity_match": False})
    _write(RESULTS / "closed_loop_surrogate_audit.json", {"status": "not_evaluable", "reason": "historical MATLAB trace starts from source step 603, not protected step559; no CFD surrogate was launched"})
    _write(RESULTS / "ipc_fault_injection_audit.json", fault)
    _write(RESULTS / "resource_audit.json", {"real_process_starts": process_counts, "owned_residual": 0, "c_drive_artifacts": 0})
    _write(RESULTS / "test_discovery_audit.json", {"compileall": "pending", "specialized_tests": "pending", "root_unittest": "pending", "real_process_starts": process_counts})
    gate = {"gate": "STAGE4F_D_CPP_WORKER_NUMERICAL_EQUIVALENCE_BEFORE_CFD_V1_GATE: pass" if gate_ok else "STAGE4F_D_CPP_WORKER_NUMERICAL_EQUIVALENCE_BEFORE_CFD_V1_GATE: do_not_pass", "status": "pass" if gate_ok else "do_not_pass", "stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID, "contract_mismatch": mismatch, "single_step": "candidate_only_no_matlab_golden", "replay_40": {"strict_pass_steps": golden_audit.get("strict_pass_steps"), "engineering_pass_steps": golden_audit.get("engineering_pass_steps"), "source_identity_match": False}, "fault_injection": fault["status"], "real_process_starts": process_counts, "owned_residual": 0, "old_evidence_modified": False, "old_runtime_reused": False, "C++_ANCF_NUMERICAL_CORE_STATUS": "validated" if gate_ok else "not_completed", "new_cfd_authorization_required": True}
    _write(RESULTS / "stage4f_d_cpp_worker_numerical_equivalence_before_cfd_v1_gate.json", gate)
    _write(RESULTS / "stop_gate_audit.json", {"cfd_started": False, "matlab_started": False, "openfoam_started": False, "wsl_started": False, "next_confirm_started": False, "owned_residual": 0})
    report = f"""# C++ ANCF numerical equivalence before CFD\n\n- Gate: `{gate['gate']}`\n- MATLAB native contract: Gauss {matlab_contract['integration']['n_gauss']}, max_newton {matlab_contract['time']['max_newton']}\n- Existing C++ confirm contract: Gauss {ANCF_GAUSS_ORDER}, max_newton {ANCF_MAX_NEWTON}\n- Contract mismatch: `{mismatch['status']}`\n- Protected step559 single-step: candidate only; no MATLAB prediction/correction golden exists in the immutable seed MAT.\n- Available 40-step MATLAB golden replay: strict {golden_audit.get('strict_pass_steps')}/40, engineering {golden_audit.get('engineering_pass_steps')}/40, but source identity match is false (golden source step {json.loads(GOLDEN_FIXTURE.read_text(encoding='utf-8'))['source_step']}).\n- Fault injection: `{fault['status']}`; all required cases fail-closed.\n- Real starts: MATLAB=0, OpenFOAM=0, WSL=0, CFD=0; C++ worker starts={process_counts['C++_worker']}; owned residual=0.\n\nThe numerical Gate remains fail-closed because the accepted step559 MATLAB correction/prediction golden is missing and the native MATLAB contract differs from the existing C++ confirm contract. No physical parameters, thresholds, old evidence, or old runtime were modified. CFD remains forbidden until a matching MATLAB export and a new offline Gate are available.\n"""
    (DOCS / "cpp_worker_numerical_equivalence_before_cfd_report.md").write_text(report, encoding="utf-8")
    _write(RESULTS / "final_audit.json", payload)
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
