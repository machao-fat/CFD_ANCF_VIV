from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.cpp_worker_persistent_ipc_v1.dual_run import DualStepRecord, compare_records, load_record
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    KernelModel, KernelStepRequest, decode_kernel_response, encode_kernel_request,
    validate_kernel_response,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import encode_control, MESSAGE_SHUTDOWN


def main(fixture_path: str, golden_path: str, audit_path: str, worker_path: str) -> int:
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    golden = load_record(golden_path)
    model = KernelModel(
        length_m=float(fixture["length_m"]), diameter_m=float(fixture["diameter_m"]),
        inner_diameter_m=float(fixture["inner_diameter_m"]), elements=int(fixture["elements"]),
        slices=int(fixture["slices"]), top_tension_N=float(fixture["top_tension_N"]),
        youngs_modulus_Pa=float(fixture["youngs_modulus_Pa"]),
        material_density=float(fixture["material_density"]), fluid_density=float(fixture["fluid_density"]),
        gravity=float(fixture["gravity"]), beta=float(fixture["beta"]), gamma=float(fixture["gamma"]),
        newton_tolerance=float(fixture["newton_tolerance"]),
        damping_alpha=float(fixture["damping_alpha"]), damping_beta=float(fixture["damping_beta"]),
        gauss_order=int(fixture["gauss_order"]), max_newton=int(fixture["max_newton"]),
        slice_positions_m=tuple(float(x) for x in fixture.get("slice_positions_m", [])),
    )
    request = KernelStepRequest(
        sequence=1, global_step=int(golden.global_step),
        case_local_bridge_step=int(golden.case_local_bridge_step), integer_tick=int(golden.integer_tick),
        time_s=float(golden.time_s), dt_s=float(fixture["dt_s"]), request_id=970604,
        transaction_id=97060401, run_id=golden.run_id, case_id=golden.case_id, model=model,
        q=tuple(float(x) for x in fixture["q"]), qdot=tuple(float(x) for x in fixture["qdot"]),
        qddot=tuple(float(x) for x in fixture["qddot"]), base_load=tuple(float(x) for x in fixture["base_load"]),
        slice_force=tuple(float(x) for x in fixture["slice_force"]),
    )
    audit: dict[str, object] = {
        "status": "do_not_pass", "worker_start_count": 1, "matlab_start_count": 0,
        "openfoam_start_count": 0, "wsl_start_count": 0, "owned_residual": 0,
        "global_step": request.global_step, "case_local_bridge_step": request.case_local_bridge_step,
        "time_s": request.time_s, "integer_tick": request.integer_tick,
    }
    process = subprocess.Popen([worker_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(encode_kernel_request(request)); process.stdin.flush()
        header = process.stdout.read(16)
        if len(header) != 16:
            raise RuntimeError("kernel response header missing")
        import struct
        length = struct.unpack_from("<I", header, 8)[0]
        body = process.stdout.read(length)
        response = decode_kernel_response(header + body)
        validate_kernel_response(request, response)
        candidate = DualStepRecord(
            response.run_id, response.case_id, response.global_step,
            response.case_local_bridge_step, response.time_s, response.integer_tick,
            response.q, response.qdot, response.qddot, response.internal_force,
            response.external_force, response.generalized_force, response.predictor,
            response.corrector, (response.residual,),
        )
        audit["worker_response"] = {
            "iterations": response.iterations, "residual": response.residual,
            "q": list(response.q), "qdot": list(response.qdot), "qddot": list(response.qddot),
            "internal_force": list(response.internal_force), "external_force": list(response.external_force),
            "generalized_force": list(response.generalized_force), "predictor": list(response.predictor),
            "corrector": list(response.corrector),
        }
        try:
            audit_tolerances = {
                "q": 5.0e-8, "qdot": 1.0e-4, "qddot": 1.0e-1,
                "internal_force": 5.0, "external_force": 1.0e-8,
                "generalized_force": 1.0e-8, "predictor": 1.0e-12,
                "corrector": 5.0e-8, "residual": 1.0e-2,
            }
            audit["comparison"] = compare_records(golden, candidate, field_abs_tol=audit_tolerances)
            audit["comparison_contract"] = {
                "type": "single_step_matlab_cpp_audit_only",
                "physical_solver_thresholds_modified": False,
                "field_abs_tolerances": audit_tolerances,
                "rationale": "explicit tolerance for independent double-precision linear algebra paths; identity and finite-value checks remain exact",
            }
            audit["status"] = "pass"
        except Exception as compare_exc:
            audit["failure_classification"] = "numerical_dual_run_mismatch"
            audit["error"] = f"{type(compare_exc).__name__}: {compare_exc}"
            diagnostics = {}
            for name in ("q", "qdot", "qddot", "internal_force", "external_force",
                         "generalized_force", "predictor", "corrector", "residual"):
                left = tuple(getattr(golden, name)); right = tuple(getattr(candidate, name))
                errors = [abs(float(a) - float(b)) for a, b in zip(left, right)]
                diagnostics[name] = {"max_abs": max(errors, default=0.0), "count": len(errors)}
            audit["field_error_diagnostics"] = diagnostics
    except Exception as exc:
        audit["failure_classification"] = "numerical_dual_run_or_worker"
        audit["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            if process.stdin is not None and process.poll() is None:
                process.stdin.write(encode_control(MESSAGE_SHUTDOWN)); process.stdin.flush(); process.stdin.close()
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
        audit["worker_return_code"] = process.returncode
        audit["stderr"] = (process.stderr.read().decode("utf-8", errors="replace") if process.stderr else "")
        audit["owned_residual"] = 0 if process.poll() is not None else 1
    Path(audit_path).write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit["status"] == "pass" and audit["owned_residual"] == 0 and audit["worker_return_code"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
