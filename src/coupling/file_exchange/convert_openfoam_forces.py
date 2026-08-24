#!/usr/bin/env python3
"""Convert OpenFOAM forces.dat into the stage-two integrated-load CSV."""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path

from csv_contract import atomic_write_csv, validate_load_csv


FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
FIELDS = (
    "schema_version",
    "step",
    "coupling_iteration",
    "time_s",
    "slice_id",
    "s_ref_m",
    "force_representation",
    "unit_span_m",
    "slice_length_m",
    "force_x_N",
    "force_y_N",
    "force_z_N",
    "pressure_force_x_N",
    "pressure_force_y_N",
    "pressure_force_z_N",
    "viscous_force_x_N",
    "viscous_force_y_N",
    "viscous_force_z_N",
    "moment_x_Nm",
    "moment_y_Nm",
    "moment_z_Nm",
    "cfd_time_step_s",
    "status",
)


def vectors(line: str) -> list[list[float]]:
    groups = []
    for text in re.findall(r"\(([^()]*)\)", line):
        values = [float(item) for item in re.findall(FLOAT, text)]
        if len(values) == 3:
            groups.append(values)
    return groups


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forces", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slice-length-m", type=float, default=1.0)
    parser.add_argument("--unit-span-m", type=float, default=1.0)
    parser.add_argument("--s-ref-m", type=float, default=0.0)
    parser.add_argument("--dt", type=float, required=True)
    args = parser.parse_args()
    if args.slice_length_m <= 0 or args.unit_span_m <= 0 or args.dt <= 0:
        raise SystemExit("lengths and dt must be positive")

    rows = []
    for raw in args.forces.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        values = [float(item) for item in re.findall(FLOAT, line)]
        groups = vectors(line)
        if not values or len(groups) < 2:
            continue
        pressure, viscous = groups[0], groups[1]
        pressure_moment = groups[2] if len(groups) >= 3 else [0.0] * 3
        viscous_moment = groups[3] if len(groups) >= 4 else [0.0] * 3
        factor = args.slice_length_m / args.unit_span_m
        pressure = [value * factor for value in pressure]
        viscous = [value * factor for value in viscous]
        force = [pressure[i] + viscous[i] for i in range(3)]
        moment = [
            (pressure_moment[i] + viscous_moment[i]) * factor
            for i in range(3)
        ]
        if not all(math.isfinite(value) for value in (*pressure, *viscous, *force, *moment)):
            raise SystemExit("forces.dat contains NaN/Inf")
        rows.append(
            {
                "schema_version": "0.1.0",
                "step": len(rows),
                "coupling_iteration": 0,
                "time_s": values[0],
                "slice_id": 0,
                "s_ref_m": args.s_ref_m,
                "force_representation": "integrated_N",
                "unit_span_m": args.unit_span_m,
                "slice_length_m": args.slice_length_m,
                "force_x_N": force[0],
                "force_y_N": force[1],
                "force_z_N": force[2],
                "pressure_force_x_N": pressure[0],
                "pressure_force_y_N": pressure[1],
                "pressure_force_z_N": pressure[2],
                "viscous_force_x_N": viscous[0],
                "viscous_force_y_N": viscous[1],
                "viscous_force_z_N": viscous[2],
                "moment_x_Nm": moment[0],
                "moment_y_Nm": moment[1],
                "moment_z_Nm": moment[2],
                "cfd_time_step_s": args.dt,
                "status": "complete",
            }
        )
    if len(rows) < 2:
        raise SystemExit(f"too few force rows in {args.forces}")
    atomic_write_csv(args.output, FIELDS, rows)
    validate_load_csv(args.output)
    print(f"wrote {len(rows)} validated load rows to {args.output}")


if __name__ == "__main__":
    main()
