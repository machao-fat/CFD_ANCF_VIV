"""Bounded 10 s three-slice participant with rolling evidence storage."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import subprocess
import time
from collections import deque
from pathlib import Path

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import KernelModel, KernelStepRequest, decode_kernel_response, encode_kernel_request, validate_kernel_response
from coupling.cpp_worker_persistent_ipc_v1.protocol import HEADER, MAGIC, MESSAGE_INITIALIZE, MESSAGE_INITIALIZE_ACK, MESSAGE_SHUTDOWN, encode_control


def force_sum(value: object, n: int = 604) -> tuple[float, float, float]:
    try:
        rows = value.tolist()
    except AttributeError:
        rows = value
    if not isinstance(rows, list) or len(rows) != n:
        raise RuntimeError("force vertex count mismatch")
    total = [0.0, 0.0, 0.0]
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise RuntimeError("force row dimension mismatch")
        for axis in range(2):
            component = float(row[axis])
            if not math.isfinite(component):
                raise RuntimeError("non-finite force")
            total[axis] += component
    return tuple(total)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", nargs=3, required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--barrier-log", required=True)
    parser.add_argument("--checkpoint-log", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--dt", type=float, default=0.005)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-id", required=True)
    args = parser.parse_args()
    if args.steps != 2000 or args.dt != 0.005:
        raise SystemExit("Stage 294 requires exactly 2000 steps and dt=0.005")
    try:
        import precice  # type: ignore
    except ImportError as exc:
        raise SystemExit(f"pyprecice unavailable: {exc}")
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    model = KernelModel(length_m=float(fixture["length_m"]), diameter_m=float(fixture["diameter_m"]), inner_diameter_m=float(fixture["inner_diameter_m"]), elements=int(fixture["elements"]), slices=3, top_tension_N=float(fixture["top_tension_N"]), youngs_modulus_Pa=float(fixture["youngs_modulus_Pa"]), material_density=float(fixture["material_density"]), fluid_density=float(fixture["fluid_density"]), gravity=float(fixture["gravity"]), beta=float(fixture["beta"]), gamma=float(fixture["gamma"]), newton_tolerance=float(fixture["newton_tolerance"]), damping_alpha=float(fixture["damping_alpha"]), damping_beta=float(fixture["damping_beta"]), gauss_order=int(fixture["gauss_order"]), max_newton=int(fixture["max_newton"]), slice_positions_m=tuple(float(x) for x in fixture["slice_positions_m"]))
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
    vertices = [(0.5 * math.cos(2.0 * math.pi * i / 604), 0.5 * math.sin(2.0 * math.pi * i / 604)) for i in range(604)]
    q = tuple(float(x) for x in fixture["q"]); qdot = tuple(float(x) for x in fixture["qdot"]); qddot = tuple(float(x) for x in fixture["qddot"])
    tail: deque[dict[str, object]] = deque(maxlen=20)
    checkpoints: list[dict[str, object]] = []
    barrier_hash = hashlib.sha256(); counts = {f"slice_{i:04d}": 0 for i in range(3)}
    error: str | None = None; start_ns = time.time_ns()
    try:
        for index, config in enumerate(args.config):
            participant = precice.Participant(f"Structure_{index:04d}", config, 0, 1)
            participants.append(participant); mesh_ids.append(participant.set_mesh_vertices("Structure-Mesh", vertices))
        for participant in participants:
            participant.initialize()
        for step in range(1, args.steps + 1):
            time_s = step * args.dt; tick = int(round(time_s * 1.0e9))
            displacement_y = [q[1], q[7], q[13]]
            if any(not math.isfinite(float(v)) for v in displacement_y):
                raise RuntimeError("non-finite worker interface displacement")
            for index, participant in enumerate(participants):
                participant.write_data("Structure-Mesh", "Displacement", mesh_ids[index], [[0.0, displacement_y[index]] for _ in vertices])
            for participant in participants:
                participant.advance(args.dt)
            forces: list[float] = []
            step_rows = []
            for index, participant in enumerate(participants):
                force = force_sum(participant.read_data("Structure-Mesh", "Force", mesh_ids[index], 0.0)); forces.extend(force); sid = f"slice_{index:04d}"; counts[sid] += 1
                step_rows.append({"sequence": step, "global_step": step, "case_local_bridge_step": step, "time_s": time_s, "integer_tick": tick, "slice_id": sid, "force_sum": list(force), "force_sha256": hashlib.sha256(struct.pack("<3d", *force)).hexdigest(), "ack": "consumed"})
            request = KernelStepRequest(sequence=step, global_step=step, case_local_bridge_step=step, integer_tick=tick, time_s=time_s, dt_s=args.dt, request_id=920000 + step, transaction_id=92000000 + step, run_id=args.run_id, case_id=args.case_id, model=model, q=q, qdot=qdot, qddot=qddot, base_load=tuple(float(x) for x in fixture["base_load"]), slice_force=tuple(forces))
            worker.stdin.write(encode_kernel_request(request)); worker.stdin.flush()
            header = worker.stdout.read(HEADER.size)
            if len(header) != HEADER.size:
                raise RuntimeError(f"worker response header missing at step {step}")
            body_len = struct.unpack_from("<I", header, 8)[0]; body = worker.stdout.read(body_len)
            if len(body) != body_len:
                raise RuntimeError(f"worker response truncated at step {step}")
            response = decode_kernel_response(header + body); validate_kernel_response(request, response)
            q, qdot, qddot = response.q, response.qdot, response.qddot
            row = {"global_step": step, "case_local_bridge_step": step, "time_s": time_s, "integer_tick": tick, "worker_sequence": response.sequence, "worker_payload_sha256": response.payload_hash.hex(), "slices": step_rows, "committed": True}
            barrier_hash.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")); tail.append(row)
            if step % 100 == 0 or step == args.steps:
                checkpoints.append({"global_step": step, "case_local_bridge_step": step, "time_s": time_s, "integer_tick": tick, "worker_payload_sha256": response.payload_hash.hex(), "q_sha256": hashlib.sha256(struct.pack("<" + "d" * len(q), *q)).hexdigest()})
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        for participant in participants:
            try: participant.finalize()
            except Exception as exc: error = error or f"participant_finalize: {type(exc).__name__}: {exc}"
        try:
            if worker.poll() is None:
                worker.stdin.write(encode_control(MESSAGE_SHUTDOWN)); worker.stdin.flush(); worker.stdin.close()
            worker.wait(timeout=10)
        except Exception:
            if worker.poll() is None: worker.kill(); worker.wait(timeout=10)
    stderr = worker.stderr.read().decode("utf-8", errors="replace") if worker.stderr else ""
    output = {"schema_version": 1, "run_id": args.run_id, "case_id": args.case_id, "slice_ids": [f"slice_{i:04d}" for i in range(3)], "participant": "StructureCoordinator", "vertices": 604, "dt_s": args.dt, "requested_steps": args.steps, "committed_steps": len(checkpoints) and checkpoints[-1]["global_step"] or 0, "slice_counts": counts, "tail_records": list(tail), "checkpoint_count": len(checkpoints), "start_time_ns": start_ns, "end_time_ns": time.time_ns(), "finalized": error is None and len(checkpoints) > 0 and checkpoints[-1]["global_step"] == args.steps, "worker": {"pid": worker.pid, "creation_time_ns": worker_start_ns, "path": args.worker, "owned": True, "return_code": worker.returncode, "closed": worker.poll() is not None, "stderr": stderr}, "barrier_sha256": barrier_hash.hexdigest(), "error": error, "final_q": list(q), "final_qdot": list(qdot), "final_qddot": list(qddot), "projection_contract": "worker q[1],q[7],q[13] -> three slice displacement; three preCICE force sums -> worker slice_force[0:9]"}
    Path(args.log).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.barrier_log).write_text(json.dumps({"schema_version": 1, "run_id": args.run_id, "case_id": args.case_id, "committed_steps": output["committed_steps"], "slice_counts": counts, "barrier_sha256": output["barrier_sha256"], "tail_records": list(tail)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.checkpoint_log).write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in checkpoints) + "\n", encoding="utf-8")
    return 0 if output["finalized"] and worker.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
