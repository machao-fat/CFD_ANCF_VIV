"""Single-slice preCICE participant backed by the persistent C++ ANCF worker.

This is a bounded interface qualification.  The OpenFOAM force on the one
preCICE slice is reduced to the worker's first slice-force triplet; the other
two worker slice slots are zero.  The mapping is explicit in the audit record
and does not claim formal multi-slice physics equivalence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import subprocess
import time
from pathlib import Path

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    KernelModel,
    KernelStepRequest,
    decode_kernel_response,
    encode_kernel_request,
    validate_kernel_response,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    HEADER,
    MAGIC,
    MESSAGE_INITIALIZE,
    MESSAGE_INITIALIZE_ACK,
    MESSAGE_SHUTDOWN,
    encode_control,
)


def _worker_start(path: str) -> tuple[subprocess.Popen[bytes], int]:
    started_ns = time.time_ns()
    process = subprocess.Popen([path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(encode_control(MESSAGE_INITIALIZE))
    process.stdin.flush()
    header = process.stdout.read(HEADER.size)
    if len(header) != HEADER.size:
        raise RuntimeError("C++ worker initialize acknowledgement header missing")
    magic, length, message_type = HEADER.unpack(header)
    if magic != MAGIC or message_type != MESSAGE_INITIALIZE_ACK:
        raise RuntimeError("C++ worker initialize acknowledgement identity mismatch")
    body = process.stdout.read(length)
    if len(body) != length:
        raise RuntimeError("C++ worker initialize acknowledgement malformed")
    return process, started_ns


def _close_worker(process: subprocess.Popen[bytes]) -> dict[str, object]:
    try:
        if process.poll() is None and process.stdin is not None:
            process.stdin.write(encode_control(MESSAGE_SHUTDOWN))
            process.stdin.flush()
            process.stdin.close()
        process.wait(timeout=10)
    except Exception:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    return {"return_code": process.returncode, "stderr": stderr, "closed": process.poll() is not None}


def _force_triplet(force: object) -> tuple[float, float, float]:
    try:
        rows = force.tolist()  # numpy array from pyprecice
    except AttributeError:
        rows = force
    if not isinstance(rows, list) or len(rows) != 604:
        raise RuntimeError("preCICE force vertex count mismatch")
    sums = [0.0, 0.0]
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise RuntimeError("preCICE force dimension mismatch")
        for index in range(2):
            value = float(row[index])
            if not math.isfinite(value):
                raise RuntimeError("non-finite preCICE force")
            sums[index] += value
    return sums[0], sums[1], 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--dt", type=float, default=0.005)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-id", required=True)
    args = parser.parse_args()
    if args.steps != 40 or args.dt != 0.005:
        raise SystemExit("Stage 290 requires exactly 40 steps and dt=0.005")
    try:
        import precice  # type: ignore
    except ImportError as exc:
        raise SystemExit(f"pyprecice unavailable: {exc}")

    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
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
    worker, worker_start_ns = _worker_start(args.worker)
    participant = precice.Participant("Structure", args.config, 0, 1)
    n = 604
    vertices = [(0.5 * math.cos(2.0 * math.pi * i / n), 0.5 * math.sin(2.0 * math.pi * i / n)) for i in range(n)]
    ids = participant.set_mesh_vertices("Structure-Mesh", vertices)
    initialized_dt = participant.initialize()
    max_dt = float(initialized_dt) if initialized_dt is not None else args.dt
    q = tuple(float(x) for x in fixture["q"])
    qdot = tuple(float(x) for x in fixture["qdot"])
    qddot = tuple(float(x) for x in fixture["qddot"])
    records: list[dict[str, object]] = []
    start_ns = time.time_ns()
    error: str | None = None
    try:
        assert worker.stdin is not None and worker.stdout is not None
        for index in range(1, args.steps + 1):
            # The ANCF endpoint coordinates are represented by the first two
            # components of each element's q block; this is an interface
            # projection only and is audited separately from numerical proof.
            y = q[1] if len(q) > 1 else 0.0
            if not math.isfinite(y):
                raise RuntimeError("non-finite ANCF interface displacement")
            displacement = [[0.0, y] for _ in vertices]
            participant.write_data("Structure-Mesh", "Displacement", ids, displacement)
            participant.advance(args.dt)
            force = participant.read_data("Structure-Mesh", "Force", ids, 0.0)
            fx, fy, fz = _force_triplet(force)
            global_step = index
            bridge_step = index
            time_s = index * args.dt
            tick = int(round(time_s * 1.0e9))
            slice_force = [0.0] * (3 * model.slices)
            slice_force[0:3] = [fx, fy, fz]
            request = KernelStepRequest(
                sequence=index, global_step=global_step, case_local_bridge_step=bridge_step,
                integer_tick=tick, time_s=time_s, dt_s=args.dt, request_id=900000 + index,
                transaction_id=90000000 + index, run_id=args.run_id, case_id=args.case_id,
                model=model, q=q, qdot=qdot, qddot=qddot,
                base_load=tuple(float(x) for x in fixture["base_load"]), slice_force=tuple(slice_force),
            )
            worker.stdin.write(encode_kernel_request(request))
            worker.stdin.flush()
            header = worker.stdout.read(HEADER.size)
            if len(header) != HEADER.size:
                raise RuntimeError(f"C++ worker response header missing at step {index}")
            length = struct.unpack_from("<I", header, 8)[0]
            body = worker.stdout.read(length)
            if len(body) != length:
                raise RuntimeError(f"C++ worker response truncated at step {index}")
            response = decode_kernel_response(header + body)
            validate_kernel_response(request, response)
            q, qdot, qddot = response.q, response.qdot, response.qddot
            response_hash = response.payload_hash.hex()
            records.append({
                "sequence": index, "global_step": global_step, "case_local_bridge_step": bridge_step,
                "time_s": time_s, "integer_tick": tick,
                "request_id": request.request_id, "transaction_id": request.transaction_id,
                "worker_pid": worker.pid, "worker_return_code": response.return_code,
                "force_sum": [fx, fy, fz], "force_payload_sha256": hashlib.sha256(
                    json.dumps([[fx, fy] for _ in range(n)], separators=(",", ":")).encode("utf-8")).hexdigest(),
                "worker_response_payload_sha256": response_hash, "ack": response.ack,
                "finite_audit": response.finite_value_audit,
            })
            if not participant.is_coupling_ongoing() and index != args.steps:
                raise RuntimeError("preCICE ended before authorized 40 steps")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            participant.finalize()
        except Exception as exc:
            error = error or f"participant_finalize: {type(exc).__name__}: {exc}"
        worker_audit = _close_worker(worker)
    output = {
        "schema_version": 1, "run_id": args.run_id, "case_id": args.case_id, "slice_id": "slice_0000",
        "participant": "Structure", "vertices": n, "dt_s": args.dt, "steps": len(records),
        "records": records, "start_time_ns": start_ns, "end_time_ns": time.time_ns(),
        "max_dt_s": max_dt, "finalized": error is None, "worker": {
            "pid": worker.pid, "creation_time_ns": worker_start_ns, "path": args.worker,
            "owned": True, **worker_audit,
        }, "error": error,
        "projection_contract": "single preCICE slice force -> worker slice 0 triplet; worker q[1] -> all interface y",
    }
    Path(args.log).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if error is None and len(records) == args.steps and worker_audit["return_code"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
