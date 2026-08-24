from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.cpp_worker_persistent_ipc_v1.dual_run import DualStepRecord, compare_records
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelModel, KernelStepRequest, decode_kernel_response, encode_kernel_request, validate_kernel_response
from coupling.cpp_worker_persistent_ipc_v1.protocol import encode_control, MESSAGE_SHUTDOWN, HEADER

ENGINEERING_TOLERANCES = {
    # Cross-solver bounded envelope; these are audit tolerances only and do
    # not change the MATLAB/C++ Newton or physical numerical thresholds.
    "q": 1.0e-4, "qdot": 5.0e-3, "qddot": 1.0, "internal_force": 5.0e2,
    "external_force": 1.0e-8, "generalized_force": 1.0e-8, "predictor": 1.0e-4,
    "corrector": 1.0e-4, "residual": 2.0e-2,
}


def validate_fixture_source(fixture: dict[str, object]) -> None:
    if (int(fixture.get("source_step", -1)) != 559 or
            abs(float(fixture.get("source_time_s", float("nan"))) - 2.2075) > 1e-12 or
            abs(float(fixture.get("dt_s", float("nan"))) - 0.00125) > 1e-15):
        raise ValueError("dual-run fixture is not the accepted step 559/time 2.2075 source")


def validate_golden_start(golden_records: list[DualStepRecord]) -> None:
    if not golden_records or golden_records[0].global_step != 560 or golden_records[0].case_local_bridge_step != 1:
        raise ValueError("dual-run golden sequence does not start at global step 560/bridge step 1")


def main(fixture_path: str, golden_jsonl: str, audit_path: str, worker_path: str) -> int:
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    validate_fixture_source(fixture)
    golden_records = [load_record_line(line) for line in Path(golden_jsonl).read_text(encoding="utf-8").splitlines() if line.strip()]
    validate_golden_start(golden_records)
    model = KernelModel(
        length_m=float(fixture["length_m"]), diameter_m=float(fixture["diameter_m"]), inner_diameter_m=float(fixture["inner_diameter_m"]),
        elements=int(fixture["elements"]), slices=int(fixture["slices"]), top_tension_N=float(fixture["top_tension_N"]),
        youngs_modulus_Pa=float(fixture["youngs_modulus_Pa"]), material_density=float(fixture["material_density"]), fluid_density=float(fixture["fluid_density"]),
        gravity=float(fixture["gravity"]), beta=float(fixture["beta"]), gamma=float(fixture["gamma"]), newton_tolerance=float(fixture["newton_tolerance"]),
        damping_alpha=float(fixture["damping_alpha"]), damping_beta=float(fixture["damping_beta"]), gauss_order=int(fixture["gauss_order"]),
        max_newton=int(fixture["max_newton"]), slice_positions_m=tuple(float(x) for x in fixture.get("slice_positions_m", [])),
    )
    audit: dict[str, object] = {
        "status": "do_not_pass", "requested_steps": len(golden_records), "processed_steps": 0,
        "strict_pass_steps": 0, "engineering_pass_steps": 0, "worker_start_count": 1,
        "matlab_start_count": 0, "openfoam_start_count": 0, "wsl_start_count": 0, "owned_residual": 0,
        "engineering_tolerances": ENGINEERING_TOLERANCES,
        "max_error_by_field": {}, "strict_failure_count": 0,
    }
    process_started_ns = time.time_ns()
    process = subprocess.Popen([worker_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               cwd=str(Path(audit_path).resolve().parent))
    audit["worker_process_audit"] = {
        "pid": int(process.pid), "parent_pid": os.getpid(), "creation_time_ns": process_started_ns,
        "command_line": [str(Path(worker_path).resolve())],
        "cwd": str(Path(audit_path).resolve().parent), "owned": True,
    }
    current_q = tuple(float(x) for x in fixture["q"])
    current_qdot = tuple(float(x) for x in fixture["qdot"])
    current_qddot = tuple(float(x) for x in fixture["qddot"])
    try:
        assert process.stdin is not None and process.stdout is not None
        for index, golden in enumerate(golden_records, start=1):
            request = KernelStepRequest(
                sequence=index, global_step=golden.global_step, case_local_bridge_step=golden.case_local_bridge_step,
                integer_tick=golden.integer_tick, time_s=golden.time_s, dt_s=float(fixture["dt_s"]),
                request_id=970000 + index, transaction_id=97000000 + index, run_id=golden.run_id, case_id=golden.case_id,
            model=model, q=current_q, qdot=current_qdot, qddot=current_qddot,
                base_load=tuple(float(x) for x in fixture["base_load"]),
                slice_force=tuple(float(x) for x in fixture["slice_force"]),
                mass_matrix=tuple(float(x) for x in fixture.get("mass_matrix", [])),
            )
            process.stdin.write(encode_kernel_request(request)); process.stdin.flush()
            header = process.stdout.read(HEADER.size)
            if len(header) != HEADER.size: raise RuntimeError(f"missing response header at index {index}")
            length = struct.unpack_from("<I", header, 8)[0]
            response = decode_kernel_response(header + process.stdout.read(length))
            validate_kernel_response(request, response)
            candidate = DualStepRecord(response.run_id, response.case_id, response.global_step, response.case_local_bridge_step,
                                       response.time_s, response.integer_tick, response.q, response.qdot, response.qddot,
                                       response.internal_force, response.external_force, response.generalized_force,
                                       response.predictor, response.corrector, (response.residual,))
            try:
                compare_records(golden, candidate)
                audit["strict_pass_steps"] = int(audit["strict_pass_steps"]) + 1
            except Exception as strict_exc:
                audit["strict_failure_count"] = int(audit["strict_failure_count"]) + 1
                audit.setdefault("strict_failure_examples", []).append(
                    {"step": golden.global_step, "error": str(strict_exc)})
            for name in ("q", "qdot", "qddot", "internal_force", "external_force",
                         "generalized_force", "predictor", "corrector", "residual"):
                left, right = tuple(getattr(golden, name)), tuple(getattr(candidate, name))
                errors = [abs(float(a) - float(b)) for a, b in zip(left, right)]
                scales = [max(1.0, abs(float(a)), abs(float(b))) for a, b in zip(left, right)]
                entry = audit["max_error_by_field"].setdefault(name, {"max_abs": 0.0, "max_relative": 0.0})
                entry["max_abs"] = max(float(entry["max_abs"]), max(errors, default=0.0))
                entry["max_relative"] = max(float(entry["max_relative"]),
                                               max((e / s for e, s in zip(errors, scales)), default=0.0))
            compare_records(golden, candidate, field_abs_tol=ENGINEERING_TOLERANCES)
            audit["engineering_pass_steps"] = int(audit["engineering_pass_steps"]) + 1
            audit["processed_steps"] = index
            current_q, current_qdot, current_qddot = response.q, response.qdot, response.qddot
        audit["status"] = "pass_with_engineering_tolerance"
    except Exception as exc:
        audit["failure_classification"] = "dual_run_sequence_or_numerical_mismatch"
        audit["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if process.poll() is None:
                process.stdin.write(encode_control(MESSAGE_SHUTDOWN)); process.stdin.flush(); process.stdin.close()
        except Exception:
            pass
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        audit["worker_return_code"] = process.returncode
        audit["worker_process_audit"].update({"end_time_ns": time.time_ns(),
            "return_code": process.returncode,
            "cleanup_result": "closed" if process.returncode == 0 else "closed_nonzero"})
        audit["stderr"] = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        audit["owned_residual"] = 0 if process.poll() is not None else 1
    Path(audit_path).write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit["status"] == "pass_with_engineering_tolerance" and audit["owned_residual"] == 0 and audit["worker_return_code"] == 0 else 1


def load_record_line(line: str) -> DualStepRecord:
    return DualStepRecord.from_mapping(json.loads(line))


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
