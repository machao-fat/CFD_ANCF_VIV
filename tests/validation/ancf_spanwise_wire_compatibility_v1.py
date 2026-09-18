"""Offline worker/wire compatibility check for the additive SLD1 contract."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (  # noqa: E402
    HEADER,
    KernelModel,
    KernelStepRequest,
    SPANWISE_LOAD_EXTENSION_MARKER,
    decode_kernel_response,
    encode_kernel_request,
    validate_kernel_response,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import (  # noqa: E402
    MESSAGE_SHUTDOWN,
    encode_control,
)


def make_request(model: KernelModel, sequence: int, distributed: bool) -> KernelStepRequest:
    q = [0.0] * model.ndof
    for node in range(model.elements + 1):
        q[6 * node + 2] = node * model.length_m / model.elements
        q[6 * node + 5] = 1.0
    common = dict(
        sequence=sequence,
        global_step=sequence,
        case_local_bridge_step=sequence,
        integer_tick=sequence * 1_000_000,
        time_s=sequence * 0.001,
        dt_s=0.001,
        request_id=30_000 + sequence,
        transaction_id=40_000 + sequence,
        run_id="spanwise_wire_audit",
        case_id="spanwise_wire_audit_case",
        model=model,
        q=tuple(q),
        qdot=(0.0,) * model.ndof,
        qddot=(0.0,) * model.ndof,
        base_load=(0.0,) * model.ndof,
    )
    if distributed:
        common["spanwise_line_force_Npm"] = (0.0,) * (3 * model.slices)
        common["slice_force"] = ()
    else:
        common["slice_force"] = (0.0,) * (3 * model.slices)
    return KernelStepRequest(**common)


def round_trip(worker: Path, request: KernelStepRequest) -> None:
    process = subprocess.Popen(
        [str(worker)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env={**os.environ, "CFD_ANCF_OFFLINE_DIRECT_WORKER": "1"})
    try:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(encode_kernel_request(request))
        process.stdin.flush()
        header = process.stdout.read(HEADER.size)
        if len(header) != HEADER.size:
            raise RuntimeError("worker returned no response header")
        body = process.stdout.read(HEADER.unpack(header)[1])
        response = decode_kernel_response(header + body)
        validate_kernel_response(request, response)
        if not response.finite_value_audit:
            raise RuntimeError("worker response finite audit failed")
        process.stdin.write(encode_control(MESSAGE_SHUTDOWN))
        process.stdin.flush()
        process.stdin.close()
        process.wait(timeout=5)
        if process.returncode != 0:
            raise RuntimeError(f"worker return code {process.returncode}")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: ancf_spanwise_wire_compatibility_v1.py <worker>")
    worker = Path(sys.argv[1]).resolve()
    if not worker.is_file():
        raise RuntimeError(f"worker not found: {worker}")
    common = dict(
        length_m=10.0,
        diameter_m=1.0,
        inner_diameter_m=0.9,
        elements=2,
        slices=3,
        slice_positions_m=(1.0, 4.0, 8.0),
        top_tension_N=0.0,
        gravity=0.0,
        newton_tolerance=1.0e-4,
    )
    legacy_model = KernelModel(**common)
    distributed_model = KernelModel(
        **common,
        spanwise_load_reconstruction="piecewise_linear_distributed",
        spanwise_active_s_min_m=0.5,
        spanwise_active_s_max_m=9.0,
    )
    legacy_bytes = legacy_model.bytes()
    distributed_bytes = distributed_model.bytes()
    if SPANWISE_LOAD_EXTENSION_MARKER.to_bytes(4, "little") in legacy_bytes:
        raise RuntimeError("legacy model unexpectedly contains SLD1 extension")
    marker = SPANWISE_LOAD_EXTENSION_MARKER.to_bytes(4, "little")
    if not distributed_bytes.startswith(legacy_bytes) or distributed_bytes.count(marker) != 1:
        raise RuntimeError("distributed model is not an additive SLD1 extension")
    round_trip(worker, make_request(legacy_model, 1, False))
    round_trip(worker, make_request(distributed_model, 1, True))
    print("WIRE_SCHEMA=UNCHANGED")
    print("LEGACY_REQUEST_REPLAY=PASS")
    print("DISTRIBUTED_SLD1_REQUEST_REPLAY=PASS")
    print("OLD_PAYLOAD_SEMANTICS=INTEGRATED_FORCE_N")
    print("NEW_PAYLOAD_SEMANTICS=SECTIONAL_LINE_FORCE_NPM")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
