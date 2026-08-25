"""Run one offline production C++ kernel request against the MATLAB trace."""
from __future__ import annotations

import argparse
import json
import struct
import subprocess
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (  # noqa: E402
    KernelModel, KernelStepRequest, decode_kernel_response, encode_kernel_request,
    validate_kernel_response,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import HEADER, encode_control, MESSAGE_SHUTDOWN  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--matlab-trace", type=Path, required=True)
    p.add_argument("--fixture", type=Path, required=True)
    p.add_argument("--worker", type=Path, required=True)
    p.add_argument("--runtime", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    matlab = json.loads(args.matlab_trace.read_text(encoding="utf-8"))
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    model = KernelModel(
        length_m=float(fixture["length_m"]), diameter_m=float(fixture["diameter_m"]),
        inner_diameter_m=float(fixture["inner_diameter_m"]), elements=int(fixture["elements"]),
        slices=int(fixture["slices"]), top_tension_N=float(fixture["top_tension_N"]),
        youngs_modulus_Pa=float(fixture["youngs_modulus_Pa"]), material_density=float(fixture["material_density"]),
        fluid_density=float(fixture["fluid_density"]), gravity=float(fixture["gravity"]),
        beta=float(fixture["beta"]), gamma=float(fixture["gamma"]),
        newton_tolerance=float(fixture["newton_tolerance"]), damping_alpha=float(fixture["damping_alpha"]),
        damping_beta=float(fixture["damping_beta"]), gauss_order=int(fixture["gauss_order"]),
        max_newton=int(fixture["max_newton"]), slice_positions_m=tuple(fixture["slice_positions_m"]),
    )
    request = KernelStepRequest(
        sequence=1, global_step=int(matlab["target_global_step"]),
        case_local_bridge_step=int(matlab["target_case_local_bridge_step"]),
        integer_tick=int(matlab["target_integer_tick"]), time_s=float(matlab["target_time_s"]),
        dt_s=float(matlab["global_dt"]), request_id=1860005601, transaction_id=1860005601,
        run_id=str(matlab["run_id"]), case_id=str(matlab["case_id"]), model=model,
        q=tuple(float(x) for x in matlab["q_source"]), qdot=tuple(float(x) for x in matlab["qdot_source"]),
        qddot=tuple(float(x) for x in matlab["qddot_source"]),
        base_load=tuple(float(x) for x in fixture["base_load"]),
        slice_force=tuple(float(x) for x in fixture["slice_force"]),
        mass_matrix=tuple(float(x) for x in fixture["mass_matrix"]),
    )
    args.runtime.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([str(args.worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    audit: dict[str, object] = {"worker_start_count": 1, "matlab_start_count": 0,
                                "openfoam_start_count": 0, "wsl_start_count": 0, "cfd_start_count": 0}
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(encode_kernel_request(request)); proc.stdin.flush()
        header = proc.stdout.read(HEADER.size)
        if len(header) != HEADER.size:
            raise RuntimeError("missing production response header")
        length = struct.unpack_from("<I", header, 8)[0]
        response = decode_kernel_response(header + proc.stdout.read(length))
        validate_kernel_response(request, response)
        def max_error(expected: list[float], actual: tuple[float, ...]) -> dict[str, object]:
            errors = [abs(float(a) - float(b)) for a, b in zip(expected, actual)]
            index = max(range(len(errors)), key=errors.__getitem__)
            return {"max_abs": errors[index], "index": index}
        fields = {}
        for name in ("q_target", "qdot_target", "qddot_target", "internal_force_target", "external_force", "generalized_force", "predictor", "corrector"):
            expected_name = name
            expected = matlab[expected_name]
            actual_name = {"q_target": "q", "qdot_target": "qdot", "qddot_target": "qddot",
                           "internal_force_target": "internal_force"}.get(name, name)
            fields[name] = max_error(expected, getattr(response, actual_name))
        audit.update({"status": "pass", "response_return_code": response.return_code,
                      "response_iterations": response.iterations, "response_residual": response.residual,
                      "field_errors": fields, "worker_pid": proc.pid})
    except Exception as exc:
        audit.update({"status": "do_not_pass", "error": f"{type(exc).__name__}: {exc}", "worker_pid": proc.pid})
    finally:
        try:
            if proc.poll() is None and proc.stdin is not None:
                proc.stdin.write(encode_control(MESSAGE_SHUTDOWN)); proc.stdin.flush(); proc.stdin.close()
        except Exception:
            pass
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
        audit["worker_return_code"] = proc.returncode
        audit["owned_residual"] = 0 if proc.poll() is not None else 1
        audit["stderr"] = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return 0 if audit["status"] == "pass" and audit["owned_residual"] == 0 and audit["worker_return_code"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
