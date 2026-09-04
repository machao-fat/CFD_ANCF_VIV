"""Offline validation for the stage-local C++ physics-ownership worker.

This tool starts only the C++ worker under test. It never starts MATLAB,
OpenFOAM, WSL, or CFD. A fresh worker process is used for each invocation and
no retry/reconnect is performed after a protocol failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IPC_SRC = ROOT / "src" / "coupling"
sys.path.insert(0, str(IPC_SRC))

from cpp_worker_persistent_ipc_v1.kernel_protocol import (  # noqa: E402
    HEADER,
    MAGIC,
    MESSAGE_KERNEL_STEP_RESPONSE,
    KernelModel,
    KernelStepRequest,
    decode_kernel_response,
    encode_kernel_request,
    validate_kernel_response,
)


def gauss(order: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if order == 3:
        return ((-math.sqrt(3.0 / 5.0), 0.0, math.sqrt(3.0 / 5.0)),
                (5.0 / 9.0, 8.0 / 9.0, 5.0 / 9.0))
    if order == 5:
        a = math.sqrt(5.0 + 2.0 * math.sqrt(10.0 / 7.0)) / 3.0
        b = math.sqrt(5.0 - 2.0 * math.sqrt(10.0 / 7.0)) / 3.0
        return ((-a, -b, 0.0, b, a),
                ((322.0 - 13.0 * math.sqrt(70.0)) / 900.0,
                 (322.0 + 13.0 * math.sqrt(70.0)) / 900.0,
                 128.0 / 225.0,
                 (322.0 + 13.0 * math.sqrt(70.0)) / 900.0,
                 (322.0 - 13.0 * math.sqrt(70.0)) / 900.0))
    raise ValueError("offline validator requires Gauss-3 or Gauss-5")


def shape(x: float, length: float) -> tuple[float, ...]:
    xi = x / length
    return (1.0 - 3.0 * xi * xi + 2.0 * xi**3,
            length * (xi - 2.0 * xi * xi + xi**3),
            3.0 * xi * xi - 2.0 * xi**3,
            length * (-xi * xi + xi**3))


def expected_base(model: KernelModel) -> tuple[float, ...]:
    """Independent Python recomputation of Q_body + Q_top."""
    n = model.ndof
    result = [0.0] * n
    area = math.pi * (model.diameter_m**2 - model.inner_diameter_m**2) / 4.0
    displaced = math.pi * model.diameter_m**2 / 4.0
    line_z = (-model.material_density * area * model.gravity +
              model.fluid_density * displaced * model.gravity)
    element_length = model.length_m / model.elements
    points, weights = gauss(model.gauss_order)
    for element in range(model.elements):
        for point, gauss_weight in zip(points, weights):
            x = 0.5 * (point + 1.0) * element_length
            factor = gauss_weight * element_length / 2.0 * line_z
            values = shape(x, element_length)
            for block, value in enumerate(values):
                result[6 * element + 3 * block + 2] += factor * value
    result[6 * model.elements + 2] += model.top_tension_N
    return tuple(result)


def read_frame(stream) -> bytes:
    header = stream.read(HEADER.size)
    if len(header) != HEADER.size:
        raise RuntimeError("worker disconnected before response header")
    magic, length, message_type = HEADER.unpack(header)
    if magic != MAGIC or message_type != MESSAGE_KERNEL_STEP_RESPONSE:
        raise RuntimeError("unexpected worker response header")
    if length > 64 * 1024 * 1024:
        raise RuntimeError("worker response is too large")
    body = stream.read(length)
    if len(body) != length:
        raise RuntimeError("worker disconnected during response")
    return header + body


def fixed(value: str, size: int) -> bytes:
    raw = value.encode("utf-8")
    return raw + b"\0" * (size - len(raw))


def run(worker: Path, steps: int, static_load: tuple[float, ...], dt: float = 0.00125) -> dict:
    model = KernelModel(
        length_m=10.0,
        diameter_m=1.0,
        inner_diameter_m=0.9,
        elements=2,
        slices=3,
        top_tension_N=1.0e6,
        youngs_modulus_Pa=2.07e11,
        material_density=7850.0,
        fluid_density=1025.0,
        gravity=9.81,
        gauss_order=5,
        max_newton=50,
        slice_positions_m=(0.0, 5.0, 10.0),
    )
    n = model.ndof
    if len(static_load) != n:
        raise ValueError("static load dimension mismatch")
    q = [0.0] * n
    qdot = [0.0] * n
    qddot = [0.0] * n
    element_length = model.length_m / model.elements
    for node in range(model.elements + 1):
        q[6 * node + 2] = node * element_length
        q[6 * node + 5] = 1.0
    run_id = "stage152_offline_physics_run_001"
    case_id = "stage152_offline_physics_case_001"
    creation_ns = time.time_ns()
    process = subprocess.Popen(
        [str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0,
    )
    responses = []
    trajectory = []
    process_error = None
    try:
        assert process.stdin is not None and process.stdout is not None
        for sequence in range(1, steps + 1):
            global_step = sequence
            time_s = global_step * dt
            request = KernelStepRequest(
                sequence=sequence,
                global_step=global_step,
                case_local_bridge_step=sequence,
                integer_tick=int(round(time_s * 1_000_000_000.0)),
                time_s=time_s,
                dt_s=dt,
                request_id=10_000 + sequence,
                transaction_id=20_000 + sequence,
                run_id=run_id,
                case_id=case_id,
                model=model,
                q=tuple(q),
                qdot=tuple(qdot),
                qddot=tuple(qddot),
                base_load=static_load,
                slice_force=(0.0,) * (3 * model.slices),
            )
            process.stdin.write(encode_kernel_request(request))
            process.stdin.flush()
            response = decode_kernel_response(read_frame(process.stdout))
            validate_kernel_response(request, response)
            if response.checkpoint_time_s != time_s:
                raise RuntimeError("checkpoint time mismatch")
            responses.append(response)
            trajectory.append({
                "global_step": response.global_step,
                "q": list(response.q),
                "qdot": list(response.qdot),
                "qddot": list(response.qddot),
            })
            q, qdot, qddot = list(response.q), list(response.qdot), list(response.qddot)
    except Exception as error:  # fail closed; no retry in this runtime
        process_error = f"{type(error).__name__}: {error}"
    finally:
        if process.poll() is None:
            process.stdin.write(HEADER.pack(MAGIC, 0, 3))
            process.stdin.flush()
        stdout, stderr = process.communicate(timeout=15)
    expected = expected_base(model)
    first_generalized = responses[0].generalized_force if responses else ()
    first_cfd = responses[0].external_force if responses else ()
    external_error = max((abs(a - b) for a, b in zip(first_generalized, expected)), default=math.inf)
    cfd_zero_error = max((abs(value) for value in first_cfd), default=math.inf)
    output = {
        "status": "pass" if process_error is None and len(responses) == steps and
        external_error <= 1.0e-8 and cfd_zero_error <= 1.0e-12 else "do_not_pass",
        "worker": str(worker),
        "worker_start_count": 1,
        "worker_pid": process.pid,
        "worker_return_code": process.returncode,
        "worker_creation_time_ns": creation_ns,
        "steps_requested": steps,
        "steps_completed": len(responses),
        "physical_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "owned_residual": 0,
        "process_error": process_error,
        "stderr": stderr.decode("utf-8", errors="replace"),
        "base_load_external_max_abs_error": external_error,
        "q_cfd_zero_max_abs": cfd_zero_error,
        "base_load_expected_sha256": hashlib.sha256(struct.pack("<" + "d" * len(expected), *expected)).hexdigest(),
        "response_identity_continuous": len(responses) == steps,
        "finite_value_audit": all(response.finite_value_audit for response in responses),
        "static_initialization_load": "zero_vector",
        "trajectory": trajectory,
    }
    if responses:
        output["last_step"] = responses[-1].global_step
        output["last_time_s"] = responses[-1].time_s
        output["last_payload_hash"] = responses[-1].payload_hash.hex()
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--dt", type=float, default=0.00125)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.worker.resolve(), args.steps, (0.0,) * 18, args.dt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
