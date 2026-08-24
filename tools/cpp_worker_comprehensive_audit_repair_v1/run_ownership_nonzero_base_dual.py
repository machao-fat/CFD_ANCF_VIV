"""Bounded offline ownership-worker replay using a non-zero MATLAB base-load reference."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src" / "coupling"))
sys.path.insert(0, str(ROOT / "src"))

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
from coupling.cpp_worker_comprehensive_audit_repair_v1.mapping_contract import (  # noqa: E402
    DEFAULT_STEP559_MAPPING,
)


def expected_base(model: KernelModel) -> tuple[float, ...]:
    from tools.cpp_physics_ownership_v1.run_offline_validation import expected_base as reference

    return tuple(reference(model))


def read_frame(stream) -> bytes:
    header = stream.read(HEADER.size)
    if len(header) != HEADER.size:
        raise RuntimeError("worker disconnected before response header")
    magic, length, message_type = HEADER.unpack(header)
    if magic != MAGIC or message_type != MESSAGE_KERNEL_STEP_RESPONSE or length > 64 * 1024 * 1024:
        raise RuntimeError("invalid worker response header")
    body = stream.read(length)
    if len(body) != length:
        raise RuntimeError("worker disconnected during response")
    return header + body


def max_error(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        return math.inf
    return max((abs(a - b) for a, b in zip(left, right)), default=0.0)


def run(worker: Path, output: Path, steps: int = 40) -> int:
    model = KernelModel(
        length_m=10.0, diameter_m=1.0, inner_diameter_m=0.9,
        elements=2, slices=3, top_tension_N=1.0e6,
        youngs_modulus_Pa=2.07e11, material_density=7850.0,
        fluid_density=1025.0, gravity=9.81, gauss_order=5,
        max_newton=50, slice_positions_m=(0.0, 5.0, 10.0),
    )
    base_reference = expected_base(model)
    n = model.ndof
    q = [0.0] * n
    qdot = [0.0] * n
    qddot = [0.0] * n
    for node in range(model.elements + 1):
        q[6 * node + 2] = node * model.length_m / model.elements
        q[6 * node + 5] = 1.0

    process = subprocess.Popen(
        [str(worker.resolve())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0,
    )
    errors: list[str] = []
    responses = 0
    hashes: list[str] = []
    max_external_error = 0.0
    max_generalized_error = 0.0
    try:
        assert process.stdin is not None and process.stdout is not None
        for index in range(steps):
            sequence = index + 1
            global_step = 560 + index
            time_s = 2.2075 + 0.00125 * sequence
            request = KernelStepRequest(
                sequence=sequence, global_step=global_step,
                case_local_bridge_step=sequence,
                integer_tick=int(round(time_s * 1.0e9)), time_s=time_s,
                dt_s=0.00125, request_id=153000 + sequence,
                transaction_id=153000000 + sequence,
                run_id="stage153_nonzero_base_run_001",
                case_id="stage153_nonzero_base_case_001", model=model,
                q=tuple(q), qdot=tuple(qdot), qddot=tuple(qddot),
                # This is the non-zero MATLAB golden reference. The worker
                # must verify it, not add it a second time.
                base_load=base_reference,
                slice_force=(0.0,) * (3 * model.slices),
            )
            DEFAULT_STEP559_MAPPING.target(
                global_step=global_step,
                case_local_bridge_step=sequence,
                time_s=time_s,
                integer_tick=request.integer_tick,
            )
            process.stdin.write(encode_kernel_request(request))
            process.stdin.flush()
            response = decode_kernel_response(read_frame(process.stdout))
            validate_kernel_response(request, response)
            max_external_error = max(max_external_error, max_error(response.external_force, base_reference))
            max_generalized_error = max(max_generalized_error, max_error(response.generalized_force, base_reference))
            q, qdot, qddot = list(response.q), list(response.qdot), list(response.qddot)
            hashes.append(response.payload_hash.hex())
            responses += 1
        process.stdin.write(HEADER.pack(MAGIC, 0, 3))
        process.stdin.flush()
        process.stdin.close()
        process.wait(timeout=10)
    except Exception as exc:  # fail closed; no same-runtime retry
        errors.append(f"{type(exc).__name__}: {exc}")
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    result = {
        "status": "pass" if responses == steps and not errors and process.returncode == 0 and
        max_external_error <= 1.0e-8 and max_generalized_error <= 1.0e-8 else "do_not_pass",
        "requested_steps": steps,
        "processed_steps": responses,
        "worker_start_count": 1,
        "worker_return_code": process.returncode,
        "nonzero_matlab_base_load_reference": True,
        "base_load_reference_max_abs": max(abs(value) for value in base_reference),
        "base_load_reference_sha256": hashlib.sha256(struct.pack("<" + "d" * n, *base_reference)).hexdigest(),
        "max_external_force_error": max_external_error,
        "max_generalized_force_error": max_generalized_error,
        "errors": errors,
        "stderr": stderr,
        "physical_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0 if process.poll() is not None else 1,
        "last_payload_hash": hashes[-1] if hashes else None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=40)
    args = parser.parse_args()
    raise SystemExit(run(args.worker, args.output, args.steps))
