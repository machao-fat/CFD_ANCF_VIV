"""Prescribed-displacement Structure participant for the authorized 8-step smoke."""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()
    try:
        import precice  # type: ignore
    except ImportError as exc:
        raise SystemExit(f"pyprecice unavailable: {exc}")
    participant = precice.Participant("Structure", args.config, 0, 1)
    n = 604
    dt = 0.005
    vertices = [(0.5 * math.cos(2.0 * math.pi * i / n), 0.5 * math.sin(2.0 * math.pi * i / n)) for i in range(n)]
    ids = participant.set_mesh_vertices("Structure-Mesh", vertices)
    # pyprecice 3.x may expose initialize() as a void call; the pinned
    # coupling window remains the authoritative timestep in that case.
    initialized_dt = participant.initialize()
    max_dt = float(initialized_dt) if initialized_dt is not None else dt
    records = []
    try:
        for step in range(8):
            # Tiny prescribed transverse motion exercises the displacement path without ANCF dynamics.
            y = 1.0e-4 * math.sin(2.0 * math.pi * 0.15 * step * dt)
            displacement = [[0.0, y] for _ in vertices]
            participant.write_data("Structure-Mesh", "Displacement", ids, displacement)
            participant.advance(dt)
            force = participant.read_data("Structure-Mesh", "Force", ids, 0.0)
            try:
                force = force.tolist()
            except AttributeError:
                pass
            records.append({"step": step, "time_s": (step + 1) * dt, "max_dt_s": max_dt, "force_size": len(force)})
            if not participant.is_coupling_ongoing():
                break
    finally:
        participant.finalize()
    Path(args.log).write_text(json.dumps({"participant": "Structure", "vertices": n, "dt_s": dt, "records": records, "finalized": True}, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
