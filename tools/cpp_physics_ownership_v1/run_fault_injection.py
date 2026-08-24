"""Fail-closed protocol fault injection for the ownership worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import subprocess
from dataclasses import replace
from pathlib import Path

from run_offline_validation import ROOT, expected_base, read_frame
from cpp_worker_persistent_ipc_v1.kernel_protocol import (
    HEADER,
    MAGIC,
    MESSAGE_KERNEL_STEP_REQUEST,
    KernelModel,
    KernelStepRequest,
    encode_kernel_request,
)


def request(model: KernelModel, *, sequence: int = 1, run_id: str = "fault_run") -> KernelStepRequest:
    n = model.ndof
    q = [0.0] * n
    for node in range(model.elements + 1):
        q[6 * node + 2] = node * model.length_m / model.elements
        q[6 * node + 5] = 1.0
    # Ownership worker requires the non-zero MATLAB golden base-load reference;
    # zero base-load fixtures would bypass the double-counting contract.
    base_reference = expected_base(model)
    return KernelStepRequest(
        sequence=sequence,
        global_step=sequence,
        case_local_bridge_step=sequence,
        integer_tick=sequence * 1_250_000,
        time_s=sequence * 0.00125,
        dt_s=0.00125,
        request_id=100 + sequence,
        transaction_id=200 + sequence,
        run_id=run_id,
        case_id="fault_case",
        model=model,
        q=tuple(q), qdot=(0.0,) * n, qddot=(0.0,) * n,
        base_load=base_reference, slice_force=(0.0,) * (3 * model.slices),
    )


def mutate_payload(frame: bytes, mutation: str) -> bytes:
    header = bytearray(frame[:HEADER.size])
    payload = bytearray(frame[HEADER.size:])
    if mutation == "hash_mismatch":
        payload[-1] ^= 0x01
    elif mutation == "tick_mismatch":
        # _PREFIX layout: schema, protocol, sequence, step, bridge, tick.
        struct.pack_into("<Q", payload, 20, 1_250_001)
    elif mutation == "step_zero":
        struct.pack_into("<i", payload, 12, 0)
    elif mutation == "bridge_zero":
        struct.pack_into("<i", payload, 16, 0)
    elif mutation == "nan_state":
        payload[-8:] = struct.pack("<d", math.nan)
    else:
        raise ValueError(mutation)
    return bytes(header) + bytes(payload)


def fresh(worker: Path):
    return subprocess.Popen([str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=str(ROOT), bufsize=0)


def expect_reject(process, frame: bytes, *, send_first: bytes | None = None) -> bool:
    assert process.stdin is not None and process.stdout is not None
    if send_first is not None:
        process.stdin.write(send_first)
        process.stdin.flush()
        read_frame(process.stdout)
    process.stdin.write(frame)
    process.stdin.flush()
    try:
        read_frame(process.stdout)
        accepted = True
    except Exception:
        accepted = False
    process.stdin.close()
    process.kill()
    process.wait(timeout=10)
    return (not accepted) and process.returncode != 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model = KernelModel(length_m=10.0, diameter_m=1.0, inner_diameter_m=0.9,
                        elements=2, slices=3, top_tension_N=1.0e6,
                        youngs_modulus_Pa=2.07e11, material_density=7850.0,
                        fluid_density=1025.0, gravity=9.81, gauss_order=5,
                        max_newton=50, slice_positions_m=(0.0, 5.0, 10.0))
    baseline = encode_kernel_request(request(model))
    cases: dict[str, bool] = {}
    for mutation in ("hash_mismatch", "tick_mismatch", "step_zero", "bridge_zero", "nan_state"):
        process = fresh(args.worker.resolve())
        cases[mutation] = expect_reject(process, mutate_payload(baseline, mutation))

    first = request(model, sequence=1)
    second = request(model, sequence=2)
    process = fresh(args.worker.resolve())
    cases["duplicate_sequence"] = expect_reject(process, encode_kernel_request(first),
                                                  send_first=encode_kernel_request(first))
    process = fresh(args.worker.resolve())
    out_of_order = request(model, sequence=3)
    cases["out_of_order_sequence"] = expect_reject(process, encode_kernel_request(out_of_order))
    process = fresh(args.worker.resolve())
    identity = request(model, sequence=2, run_id="other_run")
    cases["run_identity_mismatch"] = expect_reject(process, encode_kernel_request(identity),
                                                    send_first=encode_kernel_request(first))
    global_jump = replace(second, global_step=4)
    process = fresh(args.worker.resolve())
    cases["global_step_jump"] = expect_reject(process, encode_kernel_request(global_jump),
                                               send_first=encode_kernel_request(first))
    bridge_jump = replace(second, case_local_bridge_step=4)
    process = fresh(args.worker.resolve())
    cases["bridge_step_jump"] = expect_reject(process, encode_kernel_request(bridge_jump),
                                               send_first=encode_kernel_request(first))
    time_jump = replace(second, time_s=0.00375, integer_tick=3_750_000)
    process = fresh(args.worker.resolve())
    cases["time_jump"] = expect_reject(process, encode_kernel_request(time_jump),
                                        send_first=encode_kernel_request(first))
    changed_model = replace(model, top_tension_N=2.0e6)
    process = fresh(args.worker.resolve())
    cases["model_contract_change"] = expect_reject(
        process, encode_kernel_request(request(changed_model, sequence=2)),
        send_first=encode_kernel_request(first))
    external_mass = replace(first, mass_matrix=(0.0,) * (model.ndof * model.ndof))
    process = fresh(args.worker.resolve())
    cases["external_mass_matrix"] = expect_reject(process, encode_kernel_request(external_mass))

    result = {
        "status": "pass" if all(cases.values()) else "do_not_pass",
        "cases": cases,
        "worker_start_count": len(cases),
        "same_runtime_retry": False,
        "physical_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "owned_residual": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
