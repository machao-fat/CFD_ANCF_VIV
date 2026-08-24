#!/usr/bin/env python3
"""Generate ANCF-compatible single-slice prescribed-motion request files."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from csv_contract import MOTION_REQUIRED, atomic_write_csv, validate_motion_csv


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--amplitude", type=float, required=True)
    parser.add_argument("--frequency", type=float, required=True)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--dt", type=float, default=0.0025)
    parser.add_argument("--s-ref-m", type=float, default=0.0)
    args = parser.parse_args()
    if args.amplitude <= 0 or args.frequency <= 0 or args.duration <= 0 or args.dt <= 0:
        raise SystemExit("amplitude, frequency, duration and dt must be positive")

    args.output.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    n_steps = int(round(args.duration / args.dt))
    omega = 2.0 * math.pi * args.frequency
    for step in range(n_steps + 1):
        time = step * args.dt
        y = args.amplitude * math.sin(omega * time)
        vy = args.amplitude * omega * math.cos(omega * time)
        ay = -args.amplitude * omega * omega * math.sin(omega * time)
        row = {
            "schema_version": "0.1.0",
            "step": step,
            "coupling_iteration": 0,
            "time_s": time,
            "slice_id": 0,
            "s_ref_m": args.s_ref_m,
            "x_m": 0.0,
            "y_m": y,
            "z_m": 0.0,
            "vx_mps": 0.0,
            "vy_mps": vy,
            "vz_mps": 0.0,
            "ax_mps2": 0.0,
            "ay_mps2": ay,
            "az_mps2": 0.0,
        }
        request = args.output / f"motion_{step:08d}.csv"
        atomic_write_csv(request, MOTION_REQUIRED, [row])
        validate_motion_csv(request, expected_s_ref_m=[args.s_ref_m])
        manifest_rows.append(row)

    atomic_write_csv(args.output / "motion_manifest.csv", MOTION_REQUIRED, manifest_rows)
    print(f"generated {n_steps + 1} validated motion snapshots in {args.output}")


if __name__ == "__main__":
    main()
