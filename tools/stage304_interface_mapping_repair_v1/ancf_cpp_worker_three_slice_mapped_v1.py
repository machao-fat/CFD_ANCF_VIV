"""Stage 296 continuation participant: source 30 s -> target 70 s."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import subprocess
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from coupling.convergence_observability_v1 import ConvergenceAccumulator, ObservationError, StepObservation
from coupling.stage303_interface_mapping_repair_v1 import diagnose_mapping, project_interface

from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (
    KernelModel, KernelStepRequest, decode_kernel_response, encode_kernel_request,
    validate_kernel_response,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import (
    HEADER, MAGIC, MESSAGE_INITIALIZE, MESSAGE_INITIALIZE_ACK, MESSAGE_SHUTDOWN,
    encode_control,
)


def force_sum(value: object, n: int = 604) -> tuple[float, float, float]:
    rows = value.tolist() if hasattr(value, "tolist") else value
    if not isinstance(rows, list) or len(rows) != n:
        raise RuntimeError("force vertex count mismatch")
    total = [0.0, 0.0, 0.0]
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise RuntimeError("force row dimension mismatch")
        for axis in range(2):
            value = float(row[axis])
            if not math.isfinite(value):
                raise RuntimeError("non-finite force")
            total[axis] += value
    return tuple(total)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", nargs=3, required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--barrier-log", required=True)
    parser.add_argument("--checkpoint-log", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--initial-state", default=None)
    parser.add_argument("--source-step", type=int, required=True)
    parser.add_argument("--source-time", type=float, required=True)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--dt", type=float, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--convergence-log", default=None,
                        help="optional JSON summary path for low-volume convergence observables")
    parser.add_argument("--diagnostic-log", required=True,
                        help="JSONL mapping/virtual-work diagnostic output")
    parser.add_argument("--progress-log", default=None,
                        help="atomic low-volume progress JSON for live monitoring")
    args = parser.parse_args()
    if args.source_step < 0 or args.source_time < 0 or args.steps <= 0 or args.dt != 0.005:
        raise SystemExit("continuation requires non-negative source identity, positive steps, and dt=0.005")
    import precice  # type: ignore

    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    initial = json.loads(Path(args.initial_state).read_text(encoding="utf-8")) if args.initial_state else fixture
    q = tuple(float(x) for x in (initial["final_q"] if "final_q" in initial else initial["q"]))
    qdot = tuple(float(x) for x in (initial["final_qdot"] if "final_qdot" in initial else initial["qdot"]))
    qddot = tuple(float(x) for x in (initial["final_qddot"] if "final_qddot" in initial else initial["qddot"]))
    model = KernelModel(
        length_m=float(fixture["length_m"]), diameter_m=float(fixture["diameter_m"]),
        inner_diameter_m=float(fixture["inner_diameter_m"]), elements=int(fixture["elements"]), slices=3,
        top_tension_N=float(fixture["top_tension_N"]), youngs_modulus_Pa=float(fixture["youngs_modulus_Pa"]),
        material_density=float(fixture["material_density"]), fluid_density=float(fixture["fluid_density"]),
        gravity=float(fixture["gravity"]), beta=float(fixture["beta"]), gamma=float(fixture["gamma"]),
        newton_tolerance=float(fixture["newton_tolerance"]), damping_alpha=float(fixture["damping_alpha"]),
        damping_beta=float(fixture["damping_beta"]), gauss_order=int(fixture["gauss_order"]),
        max_newton=int(fixture["max_newton"]), slice_positions_m=tuple(float(x) for x in fixture["slice_positions_m"]),
    )
    worker = subprocess.Popen([args.worker], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    worker_start_ns = __import__("time").time_ns()
    assert worker.stdin is not None and worker.stdout is not None
    worker.stdin.write(encode_control(MESSAGE_INITIALIZE)); worker.stdin.flush()
    header = worker.stdout.read(HEADER.size)
    if len(header) != HEADER.size:
        raise RuntimeError("worker initialize response missing")
    magic, length, message_type = HEADER.unpack(header)
    if magic != MAGIC or message_type != MESSAGE_INITIALIZE_ACK or len(worker.stdout.read(length)) != length:
        raise RuntimeError("worker initialize response invalid")
    participants = []
    mesh_ids = []
    vertices = [(0.5 * math.cos(2.0 * math.pi * i / 604), 0.5 * math.sin(2.0 * math.pi * i / 604)) for i in range(604)]
    tail: deque[dict[str, object]] = deque(maxlen=20)
    checkpoints: list[dict[str, object]] = []
    barrier_hash = hashlib.sha256()
    counts = {f"slice_{i:04d}": 0 for i in range(3)}
    convergence = ConvergenceAccumulator(dt_s=args.dt, slice_ids=tuple(counts), sample_every_steps=10)
    mapping_diagnostics: list[dict[str, object]] = []
    error: str | None = None
    start_ns = __import__("time").time_ns()
    progress_path = Path(args.progress_log) if args.progress_log else None

    def write_progress(global_step: int, time_s: float) -> None:
        if progress_path is None:
            return
        payload = {
            "schema_version": 1,
            "run_id": args.run_id,
            "case_id": args.case_id,
            "pid": os.getpid(),
            "source_global_step": args.source_step,
            "target_global_step": args.source_step + args.steps,
            "current_global_step": global_step,
            "current_time_s": time_s,
            "committed_steps": local_step,
            "slice_counts": counts,
            "checkpoint_count": len(checkpoints),
            "mapping_diagnostics_count": len(mapping_diagnostics),
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }
        tmp = progress_path.with_suffix(progress_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        tmp.replace(progress_path)
    try:
        for index, config in enumerate(args.config):
            participant = precice.Participant(f"Structure_{index:04d}", config, 0, 1)
            participants.append(participant)
            mesh_ids.append(participant.set_mesh_vertices("Structure-Mesh", vertices))
        for participant in participants:
            participant.initialize()
        for local_step in range(1, args.steps + 1):
            global_step = args.source_step + local_step
            time_s = args.source_time + local_step * args.dt
            tick = int(round(time_s * 1.0e9))
            displacement_xy, velocity_xy, projected_positions, projected_velocities = project_interface(
                q, qdot, slice_positions_m=tuple(float(value) for value in fixture["slice_positions_m"]),
                length_m=float(fixture["length_m"]), elements=int(fixture["elements"])
            )
            for index, participant in enumerate(participants):
                participant.write_data("Structure-Mesh", "Displacement", mesh_ids[index], [list(displacement_xy[index]) for _ in vertices])
            for participant in participants:
                participant.advance(args.dt)
            forces: list[float] = []
            slice_rows = []
            for index, participant in enumerate(participants):
                force = force_sum(participant.read_data("Structure-Mesh", "Force", mesh_ids[index], 0.0))
                forces.extend(force)
                sid = f"slice_{index:04d}"
                counts[sid] += 1
                slice_rows.append({"sequence": local_step, "global_step": global_step, "case_local_bridge_step": local_step, "time_s": time_s, "integer_tick": tick, "slice_id": sid, "force_sum": list(force), "force_sha256": hashlib.sha256(struct.pack("<3d", *force)).hexdigest(), "ack": "consumed"})
            audit = diagnose_mapping(
                q, qdot, [tuple(float(value) for value in row["force_sum"]) for row in slice_rows],
                slice_positions_m=tuple(float(value) for value in fixture["slice_positions_m"]),
                length_m=float(fixture["length_m"]), elements=int(fixture["elements"])
            )
            request = KernelStepRequest(sequence=local_step, global_step=global_step, case_local_bridge_step=local_step, integer_tick=tick, time_s=time_s, dt_s=args.dt, request_id=930000 + local_step, transaction_id=93000000 + local_step, run_id=args.run_id, case_id=args.case_id, model=model, q=q, qdot=qdot, qddot=qddot, base_load=tuple(float(x) for x in fixture["base_load"]), slice_force=tuple(forces))
            worker.stdin.write(encode_kernel_request(request)); worker.stdin.flush()
            response_header = worker.stdout.read(HEADER.size)
            if len(response_header) != HEADER.size:
                raise RuntimeError(f"worker response header missing at global step {global_step}")
            body_len = struct.unpack_from("<I", response_header, 8)[0]
            body = worker.stdout.read(body_len)
            if len(body) != body_len:
                raise RuntimeError(f"worker response truncated at global step {global_step}")
            response = decode_kernel_response(response_header + body)
            validate_kernel_response(request, response)
            q, qdot, qddot = response.q, response.qdot, response.qddot
            convergence.observe(StepObservation(
                global_step=global_step,
                case_local_bridge_step=local_step,
                time_s=time_s,
                integer_tick=tick,
                slice_force_y={row["slice_id"]: float(row["force_sum"][1]) for row in slice_rows},
                q_norm=math.sqrt(sum(value * value for value in q)),
                qdot_norm=math.sqrt(sum(value * value for value in qdot)),
                worker_residual=float(response.residual),
                worker_iterations=int(response.iterations),
                return_code=int(response.return_code),
                finite_value_audit=bool(response.finite_value_audit),
                virtual_work_error=audit.virtual_work_error,
            ))
            mapping_diagnostics.append({
                "global_step": global_step, "case_local_bridge_step": local_step, "time_s": time_s,
                "integer_tick": tick, "interface_positions_xy": [list(value) for value in displacement_xy],
                "interface_velocities_xy": [list(value) for value in velocity_xy],
                "fluid_resultant": list(audit.fluid_resultant), "mapped_resultant": list(audit.mapped_resultant),
                "fluid_power": audit.fluid_power, "mapped_power": audit.mapped_power,
                "virtual_work_error": audit.virtual_work_error,
                "force_balance_error": audit.force_balance_error,
                "moment_balance_error": audit.moment_balance_error,
                "force_hashes": [row["force_sha256"] for row in slice_rows],
            })
            row = {"global_step": global_step, "case_local_bridge_step": local_step, "time_s": time_s, "integer_tick": tick, "worker_sequence": response.sequence, "worker_payload_sha256": response.payload_hash.hex(), "slices": slice_rows, "committed": True}
            barrier_hash.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")); tail.append(row)
            if local_step % 100 == 0 or local_step == args.steps:
                checkpoints.append({"global_step": global_step, "case_local_bridge_step": local_step, "time_s": time_s, "integer_tick": tick, "worker_payload_sha256": response.payload_hash.hex(), "q_sha256": hashlib.sha256(struct.pack("<" + "d" * len(q), *q)).hexdigest()})
                write_progress(global_step, time_s)
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
    convergence_summary = convergence.finalize()
    output = {"schema_version": 1, "run_id": args.run_id, "case_id": args.case_id, "source_global_step": args.source_step, "source_time_s": args.source_time, "target_global_step": args.source_step + args.steps, "target_time_s": args.source_time + args.steps * args.dt, "slice_ids": [f"slice_{i:04d}" for i in range(3)], "participant": "StructureCoordinator", "dt_s": args.dt, "requested_steps": args.steps, "committed_steps": args.source_step + (args.steps if error is None else 0), "local_committed_steps": args.steps if error is None else 0, "slice_counts": counts, "tail_records": list(tail), "checkpoint_count": len(checkpoints), "mapping_diagnostics_count": len(mapping_diagnostics), "start_time_ns": start_ns, "end_time_ns": __import__("time").time_ns(), "finalized": error is None and len(checkpoints) > 0 and checkpoints[-1]["global_step"] == args.source_step + args.steps, "worker": {"pid": worker.pid, "creation_time_ns": worker_start_ns, "path": args.worker, "owned": True, "return_code": worker.returncode, "closed": worker.poll() is not None, "stderr": stderr}, "barrier_sha256": barrier_hash.hexdigest(), "error": error, "final_q": list(q), "final_qdot": list(qdot), "final_qddot": list(qddot), "convergence_observables": convergence_summary, "projection_contract": "canonical C++ H rows for both displacement and velocity; fresh source step 0"}
    Path(args.log).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.barrier_log).write_text(json.dumps({"schema_version": 1, "run_id": args.run_id, "case_id": args.case_id, "source_global_step": args.source_step, "source_time_s": args.source_time, "target_global_step": args.source_step + args.steps, "target_time_s": args.source_time + args.steps * args.dt, "committed_steps": output["committed_steps"], "local_committed_steps": output["local_committed_steps"], "slice_counts": counts, "barrier_sha256": output["barrier_sha256"], "tail_records": list(tail)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.checkpoint_log).write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in checkpoints) + "\n", encoding="utf-8")
    Path(args.diagnostic_log).write_text("\n".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in mapping_diagnostics) + "\n", encoding="utf-8")
    if args.convergence_log:
        Path(args.convergence_log).write_text(json.dumps(convergence_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if output["finalized"] and worker.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
