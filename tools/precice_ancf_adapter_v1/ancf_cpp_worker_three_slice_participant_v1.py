"""Three-slice preCICE coordinator backed by one persistent C++ ANCF worker."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import subprocess
import time
from pathlib import Path

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    KernelModel, KernelStepRequest, decode_kernel_response, encode_kernel_request,
    validate_kernel_response,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    HEADER, MAGIC, MESSAGE_INITIALIZE, MESSAGE_INITIALIZE_ACK, MESSAGE_SHUTDOWN,
    encode_control,
)


def force_sum(value: object, n: int = 604) -> tuple[float, float, float]:
    try:
        rows = value.tolist()
    except AttributeError:
        rows = value
    if not isinstance(rows, list) or len(rows) != n:
        raise RuntimeError("force vertex count mismatch")
    result = [0.0, 0.0, 0.0]
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise RuntimeError("force row dimension mismatch")
        for axis in range(2):
            component = float(row[axis])
            if not math.isfinite(component):
                raise RuntimeError("non-finite force")
            result[axis] += component
    return tuple(result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", nargs=3, required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--barrier-log", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--dt", type=float, default=0.005)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-id", required=True)
    args = parser.parse_args()
    if args.steps != 8 or args.dt != 0.005:
        raise SystemExit("Stage 293 requires exactly 8 steps and dt=0.005")
    try:
        import precice  # type: ignore
    except ImportError as exc:
        raise SystemExit(f"pyprecice unavailable: {exc}")
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    model = KernelModel(
        length_m=float(fixture["length_m"]), diameter_m=float(fixture["diameter_m"]),
        inner_diameter_m=float(fixture["inner_diameter_m"]), elements=int(fixture["elements"]),
        slices=3, top_tension_N=float(fixture["top_tension_N"]), youngs_modulus_Pa=float(fixture["youngs_modulus_Pa"]),
        material_density=float(fixture["material_density"]), fluid_density=float(fixture["fluid_density"]),
        gravity=float(fixture["gravity"]), beta=float(fixture["beta"]), gamma=float(fixture["gamma"]),
        newton_tolerance=float(fixture["newton_tolerance"]), damping_alpha=float(fixture["damping_alpha"]),
        damping_beta=float(fixture["damping_beta"]), gauss_order=int(fixture["gauss_order"]),
        max_newton=int(fixture["max_newton"]), slice_positions_m=tuple(float(x) for x in fixture["slice_positions_m"]),
    )
    worker = subprocess.Popen([args.worker], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    worker_start_ns = time.time_ns()
    assert worker.stdin is not None and worker.stdout is not None
    worker.stdin.write(encode_control(MESSAGE_INITIALIZE)); worker.stdin.flush()
    hello = worker.stdout.read(HEADER.size)
    if len(hello) != HEADER.size:
        raise RuntimeError("worker initialize response missing")
    magic, length, message_type = HEADER.unpack(hello)
    if magic != MAGIC or message_type != MESSAGE_INITIALIZE_ACK or len(worker.stdout.read(length)) != length:
        raise RuntimeError("worker initialize response invalid")

    participants = []
    mesh_ids = []
    n = 604
    vertices = [(0.5 * math.cos(2.0 * math.pi * i / n), 0.5 * math.sin(2.0 * math.pi * i / n)) for i in range(n)]
    records: list[dict[str, object]] = []
    barriers: list[dict[str, object]] = []
    q = tuple(float(x) for x in fixture["q"])
    qdot = tuple(float(x) for x in fixture["qdot"])
    qddot = tuple(float(x) for x in fixture["qddot"])
    error: str | None = None
    start_ns = time.time_ns()
    try:
        for index, config in enumerate(args.config):
            participant = precice.Participant(f"Structure_{index:04d}", config, 0, 1)
            participants.append(participant)
            mesh_ids.append(participant.set_mesh_vertices("Structure-Mesh", vertices))
        for participant in participants:
            participant.initialize()
        for step in range(1, args.steps + 1):
            time_s = step * args.dt
            tick = int(round(time_s * 1.0e9))
            # q transverse coordinates at the three slice positions are used
            # as the explicit interface projection for the next CFD advance.
            displacement_y = [q[1], q[7], q[13]]
            if any(not math.isfinite(float(value)) for value in displacement_y):
                raise RuntimeError("non-finite worker interface displacement")
            for index, participant in enumerate(participants):
                displacement = [[0.0, displacement_y[index]] for _ in vertices]
                participant.write_data("Structure-Mesh", "Displacement", mesh_ids[index], displacement)
            for participant in participants:
                participant.advance(args.dt)
            slice_forces = []
            for index, participant in enumerate(participants):
                fx, fy, fz = force_sum(participant.read_data("Structure-Mesh", "Force", mesh_ids[index], 0.0))
                slice_forces.extend((fx, fy, fz))
                records.append({"sequence": step, "global_step": step, "case_local_bridge_step": step,
                                "time_s": time_s, "integer_tick": tick, "slice_id": f"slice_{index:04d}",
                                "request_id": f"{args.run_id}:slice_{index:04d}:request:{step}",
                                "transaction_id": f"{args.run_id}:slice_{index:04d}:transaction:{step}",
                                "displacement_y": displacement_y[index], "force_sum": [fx, fy, fz],
                                "force_payload_sha256": hashlib.sha256(struct.pack("<3d", fx, fy, fz)).hexdigest(),
                                "ack": "consumed"})
            request = KernelStepRequest(
                sequence=step, global_step=step, case_local_bridge_step=step, integer_tick=tick,
                time_s=time_s, dt_s=args.dt, request_id=910000 + step, transaction_id=91000000 + step,
                run_id=args.run_id, case_id=args.case_id, model=model, q=q, qdot=qdot, qddot=qddot,
                base_load=tuple(float(x) for x in fixture["base_load"]), slice_force=tuple(slice_forces),
            )
            worker.stdin.write(encode_kernel_request(request)); worker.stdin.flush()
            header = worker.stdout.read(HEADER.size)
            if len(header) != HEADER.size:
                raise RuntimeError(f"worker response header missing at step {step}")
            body_len = struct.unpack_from("<I", header, 8)[0]
            body = worker.stdout.read(body_len)
            if len(body) != body_len:
                raise RuntimeError(f"worker response truncated at step {step}")
            response = decode_kernel_response(header + body)
            validate_kernel_response(request, response)
            q, qdot, qddot = response.q, response.qdot, response.qddot
            barriers.append({"global_step": step, "case_local_bridge_step": step, "time_s": time_s,
                             "integer_tick": tick, "slices_ready": [f"slice_{i:04d}" for i in range(3)],
                             "worker_sequence": response.sequence, "committed": True})
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        for participant in participants:
            try:
                participant.finalize()
            except Exception as exc:
                error = error or f"participant_finalize: {type(exc).__name__}: {exc}"
        try:
            if worker.poll() is None:
                worker.stdin.write(encode_control(MESSAGE_SHUTDOWN)); worker.stdin.flush(); worker.stdin.close()
            worker.wait(timeout=10)
        except Exception:
            if worker.poll() is None:
                worker.kill(); worker.wait(timeout=10)
    stderr = worker.stderr.read().decode("utf-8", errors="replace") if worker.stderr else ""
    output = {"schema_version": 1, "run_id": args.run_id, "case_id": args.case_id,
              "slice_ids": [f"slice_{i:04d}" for i in range(3)], "participant": "StructureCoordinator",
              "vertices": n, "dt_s": args.dt, "steps": len(barriers), "records": records,
              "barriers": barriers, "start_time_ns": start_ns, "end_time_ns": time.time_ns(),
              "finalized": error is None and len(barriers) == args.steps,
              "worker": {"pid": worker.pid, "creation_time_ns": worker_start_ns, "path": args.worker,
                         "owned": True, "return_code": worker.returncode, "closed": worker.poll() is not None,
                         "stderr": stderr}, "error": error,
              "projection_contract": "worker q[1],q[7],q[13] -> slice displacement; three preCICE force sums -> worker slice_force[0:9]"}
    Path(args.log).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.barrier_log).write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in barriers) + "\n", encoding="utf-8")
    return 0 if output["finalized"] and worker.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
