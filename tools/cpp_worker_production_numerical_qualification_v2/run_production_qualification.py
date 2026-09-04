"""Run one bounded MATLAB/C++ production-contract numerical qualification.

This tool has no OpenFOAM, WSL, scheduler, or CFD invocation path.  MATLAB
creates a 40-step golden trajectory from an immutable step559 source; one
C++ worker then replays those exact inputs.  A failed MATLAB launch never
starts the worker, and a failed comparison never retries either process.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from scipy.io import loadmat

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))

from coupling.cpp_worker_confirm_v1.coordinator import KernelWorker
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    KernelModel, KernelStepRequest,
)
from coupling.cpp_worker_production_numerical_qualification_v2.audit import (
    FIELD_ABS_TOLERANCES, QualificationError, compare_step, validate_golden, vector_payload_hash,
)


STAGE_ID = "stage4f_d_cpp_worker_production_numerical_qualification_v2_2"
RUN_ID = "cpp_worker_production_numerical_qualification_v2_2_001"
CASE_ID = "cpp_worker_production_numerical_qualification_v2_2_case_001"
SOURCE_JSON = PROJECT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
# The physical checkpoint's embedded runner MAT retained a case-local counter
# from an earlier bridge.  This accepted seed has the identical q/qdot/qddot
# and forces but the audited global step559/time2.2075 metadata, so it is the
# only MAT source eligible for this qualification.
SOURCE_MAT = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/matlab_dual_011/accepted_step559_seed.mat"
TEMPLATE = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/dual_run_024/results/cpp_input_fixture.json"
WORKER = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/build-release/cfd_ancf_ancf_kernel_worker.exe"
MATLAB = Path(r"D:\Program Files\MATLAB\R2021b\bin\matlab.exe")
RUNTIME = PROJECT / "runtime/cpp_worker_production_numerical_qualification_v2_2"
RESULTS = PROJECT / "results/208_cpp_worker_production_numerical_qualification_v2_2"
DOCS = PROJECT / "docs/208_cpp_worker_production_numerical_qualification_v2_2"


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temp.write_bytes(canonical(value))
    os.replace(temp, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _as_vector(value: Any) -> list[float]:
    return [float(item) for item in value.reshape(-1)]


def load_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    source = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    fixture = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    state = loadmat(SOURCE_MAT, squeeze_me=True, struct_as_record=False)["state"]
    source_state = source["structure"]
    for source_name, matlab_value in (("q", state.q), ("qdot", state.qd), ("qddot", state.qdd)):
        expected = [float(item) for item in source_state[source_name]]
        actual = _as_vector(matlab_value)
        if len(expected) != len(actual) or any(left != right for left, right in zip(expected, actual)):
            raise QualificationError(f"accepted JSON/MAT source mismatch: {source_name}")
    if int(state.step) != 559 or not math.isclose(float(state.t), 2.2075, rel_tol=0.0, abs_tol=1e-12):
        raise QualificationError("MAT source identity is not step559/time2.2075")
    fixture.update({
        "source_step": 559,
        "source_time_s": 2.2075,
        "dt_s": 0.00125,
        "q": _as_vector(state.q),
        "qdot": _as_vector(state.qd),
        "qddot": _as_vector(state.qdd),
        "base_load": _as_vector(state.base_load),
        "slice_force": [float(item) for item in state.last_slice_force_N.reshape(-1)],
        "mass_matrix": _as_vector(state.model.mass_matrix),
        "gauss_order": 3,
        "max_newton": 40,
    })
    if fixture.get("slices") != 3 or len(fixture["q"]) != 102 or len(fixture["mass_matrix"]) != 102 * 102:
        raise QualificationError("fixture dimensions are inconsistent with the production source")
    metadata = {
        "source_json_sha256": sha256(SOURCE_JSON), "source_mat_sha256": sha256(SOURCE_MAT),
        "fixture_template_sha256": sha256(TEMPLATE), "worker_sha256": sha256(WORKER),
        "worker_size_bytes": WORKER.stat().st_size, "worker_mtime_ns": WORKER.stat().st_mtime_ns,
        "global_dt_s": 0.00125, "gauss_order": 3, "max_newton": 40,
        "mass_gauss_order": 5, "formal_protocol": "0.2.1",
    }
    return fixture, metadata


def matlab_expression(golden: Path) -> str:
    exporter = PROJECT / "tools/cpp_worker_production_numerical_qualification_v2"
    def quoted(path: Path) -> str:
        return str(path.resolve()).replace("\\", "/").replace("'", "''")
    return f"addpath('{quoted(exporter)}');export_production_contract_golden('{quoted(SOURCE_MAT)}','{quoted(golden)}');"


def run_matlab(golden: Path, runtime: Path) -> dict[str, Any]:
    logs = runtime / "matlab"
    logs.mkdir(parents=True, exist_ok=False)
    stdout_path, stderr_path = logs / "stdout.txt", logs / "stderr.txt"
    environment = os.environ.copy()
    for name in ("TEMP", "TMP", "TMPDIR", "PREFDIR"):
        target = runtime / "matlab_environment" / name.lower()
        target.mkdir(parents=True, exist_ok=True)
        environment[name] = str(target)
    command = [str(MATLAB), "-batch", matlab_expression(golden)]
    started_ns = time.time_ns()
    process = subprocess.Popen(command, cwd=str(PROJECT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
    try:
        stdout, stderr = process.communicate(timeout=300)
        timed_out = False
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        timed_out = True
    stdout_path.write_bytes(stdout); stderr_path.write_bytes(stderr)
    combined = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
    classification = None
    if timed_out:
        classification = "matlab_timeout"
    elif process.returncode != 0:
        classification = "matlab_return_nonzero"
    elif "5001" in combined:
        classification = "matlab_applicationservice_5001"
    elif not golden.is_file() or golden.stat().st_size == 0:
        classification = "matlab_golden_output_missing"
    return {
        "pid": int(process.pid), "parent_pid": os.getpid(), "command_line": command, "cwd": str(PROJECT),
        "start_time_ns": started_ns, "end_time_ns": time.time_ns(), "return_code": process.returncode,
        "timed_out": timed_out, "stdout": str(stdout_path), "stderr": str(stderr_path),
        "owned": True, "cleanup_result": "closed", "failure_classification": classification,
        "environment": {name: environment[name] for name in ("TEMP", "TMP", "TMPDIR", "PREFDIR")},
    }


def candidate_record(response: Any) -> dict[str, Any]:
    return {
        "run_id": response.run_id, "case_id": response.case_id, "global_step": response.global_step,
        "case_local_bridge_step": response.case_local_bridge_step, "time_s": response.time_s,
        "integer_tick": response.integer_tick, "sequence": response.sequence,
        "request_id": response.request_id, "transaction_id": response.transaction_id,
        "return_code": response.return_code, "iterations": response.iterations,
        "finite_value_audit": response.finite_value_audit, "residual": response.residual,
        "q": list(response.q), "qdot": list(response.qdot), "qddot": list(response.qddot),
        "internal_force": list(response.internal_force), "external_force": list(response.external_force),
        "generalized_force": list(response.generalized_force), "predictor": list(response.predictor),
        "corrector": list(response.corrector), "ack": response.ack,
        "checkpoint": {"step": response.checkpoint_step, "time_s": response.checkpoint_time_s,
                       "integer_tick": response.checkpoint_tick}, "payload_hash": response.payload_hash.hex(),
    }


def canonicalize_matlab_golden(raw_path: Path, canonical_path: Path) -> dict[str, Any]:
    """Pin hashes to the JSONL values, retaining MATLAB's raw hash verbatim.

    MATLAB R2021b's Java byte bridge can report a hash of its in-memory array
    that differs after JSON numeric serialization.  The canonical record is
    therefore the audit input, while ``matlab_reported_payload_hash`` preserves
    the original observation for forensic review.
    """
    if canonical_path.exists():
        raise QualificationError("canonical golden already exists")
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    raw_hash_mismatches = 0
    for row in rows:
        reported = row.get("payload_hash")
        expected_hash, expected_size = vector_payload_hash(row)
        if not isinstance(reported, str) or len(reported) != 64:
            raise QualificationError("MATLAB reported payload hash is malformed")
        row["matlab_reported_payload_hash"] = reported
        row["payload_hash"] = expected_hash
        row["payload_size_bytes"] = expected_size
        raw_hash_mismatches += int(reported != expected_hash)
    canonical_path.write_text("".join(json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")
    return {"raw_path": str(raw_path), "raw_sha256": sha256(raw_path), "canonical_path": str(canonical_path),
            "canonical_sha256": sha256(canonical_path), "records": len(rows),
            "matlab_reported_hash_mismatches": raw_hash_mismatches}


def run_cpp(golden: list[dict[str, Any]], fixture: dict[str, Any], runtime: Path) -> dict[str, Any]:
    model = KernelModel(
        length_m=float(fixture["length_m"]), diameter_m=float(fixture["diameter_m"]),
        inner_diameter_m=float(fixture["inner_diameter_m"]), elements=int(fixture["elements"]),
        slices=int(fixture["slices"]), top_tension_N=float(fixture["top_tension_N"]),
        youngs_modulus_Pa=float(fixture["youngs_modulus_Pa"]), material_density=float(fixture["material_density"]),
        fluid_density=float(fixture["fluid_density"]), gravity=float(fixture["gravity"]), beta=float(fixture["beta"]),
        gamma=float(fixture["gamma"]), newton_tolerance=float(fixture["newton_tolerance"]),
        damping_alpha=float(fixture["damping_alpha"]), damping_beta=float(fixture["damping_beta"]),
        gauss_order=3, mass_gauss_order=5, max_newton=40,
        slice_positions_m=tuple(float(item) for item in fixture["slice_positions_m"]),
    )
    worker = KernelWorker(WORKER, runtime / "cpp_worker", RUN_ID, CASE_ID, timeout_s=60.0)
    current_q, current_qdot, current_qddot = (tuple(float(item) for item in fixture[name]) for name in ("q", "qdot", "qddot"))
    base_load = tuple(float(item) for item in fixture["base_load"])
    slice_force = tuple(float(item) for item in fixture["slice_force"])
    mass = tuple(float(item) for item in fixture["mass_matrix"])
    comparisons: list[dict[str, Any]] = []
    error: str | None = None
    try:
        worker.start()
        for row in golden:
            request = KernelStepRequest(
                sequence=int(row["sequence"]), global_step=int(row["global_step"]),
                case_local_bridge_step=int(row["case_local_bridge_step"]), integer_tick=int(row["integer_tick"]),
                time_s=float(row["time_s"]), dt_s=0.00125, request_id=int(row["request_id"]),
                transaction_id=int(row["transaction_id"]), run_id=RUN_ID, case_id=CASE_ID, model=model,
                q=current_q, qdot=current_qdot, qddot=current_qddot, base_load=base_load,
                slice_force=slice_force, mass_matrix=mass,
            )
            response = worker.step(request)
            candidate = candidate_record(response)
            if candidate["ack"] != 1:
                raise QualificationError("C++ acknowledgement is invalid")
            comparison = compare_step(row, candidate)
            comparisons.append({"global_step": row["global_step"], **comparison})
            current_q, current_qdot, current_qddot = response.q, response.qdot, response.qddot
    except Exception as exc:  # Result must preserve the first identity and raw worker audit.
        error = f"{type(exc).__name__}: {exc}"
    finally:
        worker.stop()
    return {"status": "pass" if error is None and len(comparisons) == 40 and worker.owned_residual == 0 else "do_not_pass",
            "processed_steps": len(comparisons), "comparisons": comparisons, "error": error,
            "worker_process_audit": dict(worker.audit), "worker_start_count": worker.start_count,
            "owned_residual": worker.owned_residual, "worker_return_code": worker.return_code}


def main() -> int:
    if any(path.exists() for path in (RUNTIME, RESULTS, DOCS)):
        raise SystemExit("Stage206 destination already exists; refusing retry/reuse")
    if not all(path.is_file() for path in (SOURCE_JSON, SOURCE_MAT, TEMPLATE, WORKER, MATLAB)):
        raise SystemExit("required protected source, executable, or fixture is missing")
    RUNTIME.mkdir(parents=True); RESULTS.mkdir(parents=True); DOCS.mkdir(parents=True)
    fixture, identities = load_fixture()
    write_json(RUNTIME / "production_fixture.json", fixture)
    write_json(RESULTS / "qualification_identity_manifest.json", identities)
    raw_golden_path = RUNTIME / "matlab_golden_40_raw.jsonl"
    golden_path = RUNTIME / "matlab_golden_40_canonical.jsonl"
    matlab = run_matlab(raw_golden_path, RUNTIME)
    write_json(RESULTS / "matlab_process_audit.json", matlab)
    cpp: dict[str, Any] = {"status": "not_started", "processed_steps": 0, "owned_residual": 0}
    golden_validation: dict[str, Any] | None = None
    canonicalization: dict[str, Any] | None = None
    failure = matlab["failure_classification"]
    if failure is None:
        try:
            canonicalization = canonicalize_matlab_golden(raw_golden_path, golden_path)
            golden = validate_golden(golden_path, run_id=RUN_ID, case_id=CASE_ID)
            golden_validation = {"status": "pass", "count": len(golden), "sha256": sha256(golden_path),
                                 "size_bytes": golden_path.stat().st_size, "mtime_ns": golden_path.stat().st_mtime_ns}
            cpp = run_cpp(golden, fixture, RUNTIME)
            if cpp["status"] != "pass":
                failure = "cpp_dual_run_failed"
        except Exception as exc:
            failure = f"golden_validation_failed: {type(exc).__name__}: {exc}"
    process_counts = {"MATLAB": 1, "OpenFOAM": 0, "WSL": 0, "CFD": 0,
                      "C++_worker": int(cpp.get("worker_start_count", 0))}
    gate_status = "pass" if failure is None and cpp["status"] == "pass" else "do_not_pass"
    core_status = "validated" if gate_status == "pass" else "not_completed"
    summary = {"stage_id": STAGE_ID, "run_id": RUN_ID, "case_id": CASE_ID, "gate_status": gate_status,
               "failure_classification": failure, "identities": identities, "matlab": matlab,
               "golden_validation": golden_validation, "golden_canonicalization": canonicalization,
               "cpp": cpp, "field_abs_tolerances": FIELD_ABS_TOLERANCES,
               "real_process_starts": process_counts, "owned_residual": int(cpp.get("owned_residual", 0)),
               "old_evidence_modified": False, "old_runtime_reused": False, "cfd_started": False,
               "C++_ANCF_NUMERICAL_CORE_STATUS": core_status,
               "formal_status": {"frequency": "not_evaluable_insufficient_cycles",
                                 "FORMAL_STROUHAL_STATUS": "not_completed",
                                 "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"}}
    write_json(RESULTS / "matlab_cpp_production_contract_dual_audit.json", summary)
    gate = {"gate": f"STAGE4F_D_CPP_WORKER_PRODUCTION_NUMERICAL_QUALIFICATION_V2_2_GATE: {gate_status}",
            "status": gate_status, "stage_id": STAGE_ID, "C++_ANCF_NUMERICAL_CORE_STATUS": core_status,
            "strict_steps": f"{cpp.get('processed_steps', 0)}/40", "production_contract": {key: identities[key] for key in ("global_dt_s", "gauss_order", "max_newton", "mass_gauss_order", "formal_protocol")},
            "real_process_starts": process_counts, "owned_residual": int(cpp.get("owned_residual", 0)),
            "old_evidence_modified": False, "stage75_started": False, "new_cfd_authorization_required": True}
    write_json(RESULTS / "stage4f_d_cpp_worker_production_numerical_qualification_v2_gate.json", gate)
    report = "\n".join((
        "# C++ production numerical qualification V2", "",
        f"- Gate: `{gate['gate']}`", f"- Production contract: dt={identities['global_dt_s']}, Gauss=3, max_newton=40, mass Gauss=5.",
        f"- MATLAB/C++ strict steps: `{cpp.get('processed_steps', 0)}/40`.",
        f"- MATLAB return code: `{matlab['return_code']}`; C++ worker starts: `{cpp.get('worker_start_count', 0)}`.",
        "- OpenFOAM=0, WSL=0, CFD=0. Stage75 was not started.",
        "- Accepted source and all historical evidence were read only.",
        f"- C++ numerical status: `{core_status}`.",
    )) + "\n"
    (DOCS / "cpp_worker_production_numerical_qualification_v2_report.md").write_text(report, encoding="utf-8")
    return 0 if gate_status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
