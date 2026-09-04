"""Deterministic ANCF interface fixture for Stage 286; no MATLAB or CFD launch."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--dt", type=float, default=0.005)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--case-id", required=True)
    args = parser.parse_args()
    if args.steps != 40 or args.dt != 0.005:
        raise SystemExit("Stage 286 requires exactly 40 steps and dt=0.005")
    try:
        import precice  # type: ignore
    except ImportError as exc:
        raise SystemExit(f"pyprecice unavailable: {exc}")
    participant = precice.Participant("Structure", args.config, 0, 1)
    n = 604
    vertices = [(0.5 * math.cos(2.0 * math.pi * i / n), 0.5 * math.sin(2.0 * math.pi * i / n)) for i in range(n)]
    ids = participant.set_mesh_vertices("Structure-Mesh", vertices)
    initialized_dt = participant.initialize()
    max_dt = float(initialized_dt) if initialized_dt is not None else args.dt
    records = []
    start_ns = time.time_ns()
    try:
        for step in range(args.steps):
            # The displacement is the ANCF interface fixture: all wire fields are
            # deterministic and finite, while the numerical ANCF core remains offline.
            t = (step + 1) * args.dt
            y = 1.0e-4 * math.sin(2.0 * math.pi * 0.15 * t)
            displacement = [[0.0, y] for _ in vertices]
            participant.write_data("Structure-Mesh", "Displacement", ids, displacement)
            participant.advance(args.dt)
            force = participant.read_data("Structure-Mesh", "Force", ids, 0.0)
            try:
                force = force.tolist()
            except AttributeError:
                pass
            if not isinstance(force, list) or len(force) != n:
                raise RuntimeError("force output size mismatch")
            if any(not math.isfinite(float(value)) for row in force for value in row):
                raise RuntimeError("non-finite force output")
            request_id = f"{args.run_id}:slice_0000:request:{step}"
            transaction_id = f"{args.run_id}:slice_0000:transaction:{step}"
            payload_hash = hashlib.sha256(json.dumps(force, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            records.append({"global_step": step, "case_local_bridge_step": step, "time_s": t,
                            "integer_tick": int(round(t * 1.0e9)), "request_id": request_id,
                            "transaction_id": transaction_id, "sequence": step + 1,
                            "displacement_vertices": n, "force_vertices": len(force),
                            "force_payload_sha256": payload_hash, "ack": "consumed"})
            if not participant.is_coupling_ongoing() and step + 1 != args.steps:
                raise RuntimeError("preCICE ended before authorized 40 steps")
    finally:
        participant.finalize()
    output = {"schema_version": 1, "run_id": args.run_id, "case_id": args.case_id,
              "slice_id": "slice_0000", "participant": "Structure", "vertices": n,
              "dt_s": args.dt, "steps": len(records), "records": records,
              "start_time_ns": start_ns, "end_time_ns": time.time_ns(),
              "max_dt_s": max_dt, "finalized": True, "owned": True}
    Path(args.log).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
