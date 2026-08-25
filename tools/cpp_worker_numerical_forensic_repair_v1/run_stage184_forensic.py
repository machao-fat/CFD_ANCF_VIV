"""Stage184 offline forensic audit and fixed-force replay.

The script consumes the existing read-only MATLAB golden JSONL and fixture,
starts only the freshly built local C++ worker, and records a fail-closed
result. It never starts MATLAB, OpenFOAM, WSL, or CFD.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
from pathlib import Path

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    HEADER, KernelModel, KernelStepRequest, decode_kernel_response,
    encode_kernel_request, validate_kernel_response,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import MESSAGE_INITIALIZE, MESSAGE_SHUTDOWN, encode_control


def _error(left, right):
    errors = [abs(float(a) - float(b)) for a, b in zip(left, right)]
    scales = [max(1.0, abs(float(a)), abs(float(b))) for a, b in zip(left, right)]
    rel = [e / s for e, s in zip(errors, scales)]
    i = max(range(len(errors)), key=errors.__getitem__) if errors else 0
    r = max(range(len(rel)), key=rel.__getitem__) if rel else 0
    return {
        "max_abs": errors[i] if errors else 0.0,
        "max_relative": rel[r] if rel else 0.0,
        "max_abs_index_zero_based": i,
        "max_relative_index_zero_based": r,
    }


def _read_lines(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_replay(worker: Path, fixture: dict, golden: list[dict], outdir: Path):
    n = len(fixture["q"])
    model = KernelModel(
        length_m=float(fixture["length_m"]), diameter_m=float(fixture["diameter_m"]),
        inner_diameter_m=float(fixture["inner_diameter_m"]), elements=int(fixture["elements"]),
        slices=int(fixture["slices"]), top_tension_N=float(fixture["top_tension_N"]),
        youngs_modulus_Pa=float(fixture["youngs_modulus_Pa"]), material_density=float(fixture["material_density"]),
        fluid_density=float(fixture["fluid_density"]), gravity=float(fixture["gravity"]),
        beta=float(fixture["beta"]), gamma=float(fixture["gamma"]),
        newton_tolerance=float(fixture["newton_tolerance"]), damping_alpha=float(fixture["damping_alpha"]),
        damping_beta=float(fixture["damping_beta"]), gauss_order=int(fixture["gauss_order"]),
        max_newton=int(fixture["max_newton"]),
        slice_positions_m=tuple(float(x) for x in fixture["slice_positions_m"]),
    )
    source = {name: tuple(float(x) for x in fixture[name]) for name in ("q", "qdot", "qddot")}
    process = subprocess.Popen([str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    records = []
    failures = []
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(encode_control(MESSAGE_INITIALIZE)); process.stdin.flush()
        for index, reference in enumerate(golden, start=1):
            request = KernelStepRequest(
                sequence=index, global_step=int(reference["global_step"]),
                case_local_bridge_step=int(reference["case_local_bridge_step"]),
                integer_tick=int(reference["integer_tick"]), time_s=float(reference["time_s"]),
                dt_s=float(fixture["dt_s"]), request_id=1840000 + index,
                transaction_id=2840000 + index, run_id="stage184_cpp_forensic_replay",
                case_id="stage184_cpp_forensic_case", model=model,
                q=source["q"], qdot=source["qdot"], qddot=source["qddot"],
                base_load=tuple(float(x) for x in fixture["base_load"]),
                slice_force=tuple(float(x) for x in fixture["slice_force"]),
                mass_matrix=tuple(float(x) for x in fixture["mass_matrix"]),
            )
            try:
                process.stdin.write(encode_kernel_request(request)); process.stdin.flush()
                header = process.stdout.read(HEADER.size)
                if len(header) != HEADER.size:
                    raise RuntimeError("worker response header missing")
                length = int.from_bytes(header[8:12], "little")
                frame = header + process.stdout.read(length)
                response = decode_kernel_response(frame)
                validate_kernel_response(request, response)
                fields = {}
                for name in ("q", "qdot", "qddot", "internal_force", "external_force",
                             "generalized_force", "predictor", "corrector"):
                    fields[name] = _error(reference[name], getattr(response, name))
                fields["residual"] = _error([float(reference["residual"])], [response.residual])
                records.append({"step": int(reference["global_step"]), "fields": fields,
                                "iterations": response.iterations})
                source = {"q": response.q, "qdot": response.qdot, "qddot": response.qddot}
            except Exception as exc:  # fail closed; no retry in this runtime
                failures.append({"step": int(reference["global_step"]), "error": str(exc)})
                break
        if process.poll() is None:
            process.stdin.write(encode_control(MESSAGE_SHUTDOWN)); process.stdin.flush()
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=5)
    max_fields = {}
    for record in records:
        for name, value in record["fields"].items():
            current = max_fields.setdefault(name, {"max_abs": 0.0, "max_relative": 0.0})
            current["max_abs"] = max(current["max_abs"], value["max_abs"])
            current["max_relative"] = max(current["max_relative"], value["max_relative"])
    result = {
        "steps_total": len(golden), "steps_processed": len(records),
        "steps_passed_engineering": len(records) if not failures else max(0, len(records) - len(failures)),
        "first_failed_step": failures[0]["step"] if failures else None,
        "failures": failures, "max_error_by_field": max_fields,
        "worker_start_count": 1, "worker_return_code": process.returncode,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
    }
    (outdir / "replay_40step_audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (outdir / "replay_10step_audit.json").write_text(json.dumps({**result, "steps_total": 10,
        "steps_processed": min(10, len(records)), "records": records[:10]}, indent=2), encoding="utf-8")
    return result, records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    golden = _read_lines(args.golden)
    if len(golden) < 40:
        raise RuntimeError("golden fixture has fewer than 40 records")
    # The C++ trace is generated by the forensic executable outside this
    # script. Preserve its hash and explicitly report that no MATLAB
    # intermediate trace is present in the protected read-only evidence.
    import hashlib
    trace_hash = hashlib.sha256(args.trace.read_bytes()).hexdigest()
    contract = {
        "stage_id": "stage4f_d_cpp_worker_numerical_forensic_repair_v1_stage184",
        "run_id": "cpp_worker_numerical_forensic_repair_184_001",
        "case_id": "cpp_worker_numerical_forensic_repair_stage184_case_001",
        "source_step": int(fixture["source_step"]), "target_step": int(golden[0]["global_step"]),
        "source_time_s": float(fixture["source_time_s"]), "target_time_s": float(golden[0]["time_s"]),
        "global_dt_s": float(fixture["dt_s"]), "gauss_order": int(fixture["gauss_order"]),
        "max_newton": int(fixture["max_newton"]), "newton_tolerance": float(fixture["newton_tolerance"]),
        "matlab_golden_readonly": True, "matlab_intermediate_trace_available": False,
        "protected_contract_changed": False,
    }
    (args.outdir / "numerical_contract_manifest.json").write_text(json.dumps(contract, indent=2), encoding="utf-8")
    replay, records = _run_replay(args.worker, fixture, golden[:40], args.outdir)
    direct = {
        "source_step": int(fixture["source_step"]), "target_step": int(golden[0]["global_step"]),
        "cpp_trace_sha256": trace_hash,
        "matlab_intermediate_comparison": "not_evaluable_without_existing_matlab_intermediate_fixture",
        "target_q_aggregate_reference": "Stage169 read-only evidence reports max_abs=2.9103830456733704e-11",
        "worker_replay_step560": records[0] if records else None,
    }
    (args.outdir / "step560_intermediate_comparison.json").write_text(json.dumps(direct, indent=2), encoding="utf-8")
    forensic = {
        "trace_format": "line-oriented lossless float64",
        "trace_sha256": trace_hash,
        "points_expected": int(fixture["elements"]) * int(fixture["gauss_order"]),
        "points_observed": sum(1 for line in args.trace.read_text(encoding="utf-8").splitlines() if line.startswith("point ")),
        "first_matlab_intermediate_difference": None,
        "status": "not_evaluable_matlab_intermediate_fixture_missing",
    }
    (args.outdir / "internal_force_forensic_audit.json").write_text(json.dumps(forensic, indent=2), encoding="utf-8")
    repair = {
        "candidate_change": "recompute accepted qddot/qd after Newton and reuse dt^2 temporary",
        "physics_or_thresholds_modified": False, "matlab_reference_modified": False,
        "confirmed_first_difference_fixed": False,
        "status": "do_not_pass_until_matlab_intermediate_trace_is_available",
    }
    (args.outdir / "numerical_repair_manifest.json").write_text(json.dumps(repair, indent=2), encoding="utf-8")
    gate = {
        "stage_id": contract["stage_id"], "gate": "STAGE4F_D_CPP_WORKER_NUMERICAL_FORENSIC_REPAIR_V1_GATE: do_not_pass",
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "reason": "first intermediate MATLAB/C++ difference is not proven; strict equivalence remains unvalidated",
        "replay_40_steps_processed": replay["steps_processed"],
        "real_process_starts": replay["real_process_starts"], "owned_residual": 0,
    }
    (args.outdir / "independent_gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
    print(json.dumps(gate, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
