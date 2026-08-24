#!/usr/bin/env python3
"""Validate ANCF motion snapshots and emit an OpenFOAM-readable sample table.

The prescribed-motion ALE case uses OpenFOAM's analytic oscillating motion
function. This converter is the file-exchange seam for later CFD-driven motion:
it checks every ANCF snapshot and writes a time-ordered table that can be
consumed by a custom OpenFOAM boundary/motion function without changing the
CSV contract.
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .csv_contract import validate_motion_csv
except ImportError:  # pragma: no cover - direct script execution
    from csv_contract import validate_motion_csv


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="snapshot directory or one CSV")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slice-id", type=int, default=0, help="single rigid slice used by tabulated6DoFMotion")
    args = parser.parse_args()
    if args.input.is_dir():
        files = sorted(args.input.glob("motion_[0-9]*.csv"))
    else:
        files = [args.input]
    if not files:
        raise SystemExit(f"no motion snapshots found in {args.input}")

    records = []
    expected_s = None
    previous_time = None
    for path in files:
        rows = validate_motion_csv(path, expected_s_ref_m=expected_s)
        if expected_s is None:
            expected_s = [float(row["s_ref_m"]) for row in rows]
        snapshot_time = float(rows[0]["time_s"])
        if previous_time is not None and snapshot_time <= previous_time:
            raise SystemExit(f"motion time is not strictly increasing at {path}")
        previous_time = snapshot_time
        selected = [row for row in rows if int(float(row["slice_id"])) == args.slice_id]
        if len(selected) != 1:
            raise SystemExit(
                f"{path}: expected exactly one row for slice_id={args.slice_id}, got {len(selected)}"
            )
        for row in selected:
            records.append(
                (
                    row["time_s"],
                    row["slice_id"],
                    row["s_ref_m"],
                    row["x_m"],
                    row["y_m"],
                    row["z_m"],
                    row["vx_mps"],
                    row["vy_mps"],
                    row["vz_mps"],
                    row["ax_mps2"],
                    row["ay_mps2"],
                    row["az_mps2"],
                    row["coupling_iteration"],
                )
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # OpenFOAM's native tabulated6DoFMotion reads a List<Tuple2<scalar,
    # Vector2D<vector>>>: time, total translation, total rotation.  The
    # protocol CSV retains velocity/acceleration for audits, but the native
    # table intentionally contains only the six rigid-body coordinates.
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(f"{len(records)}\n(\n")
        for record in records:
            time_s, _, _, x_m, y_m, z_m, *_ = record
            stream.write(
                f"({float(time_s):.17g} (({float(x_m):.17g} "
                f"{float(y_m):.17g} {float(z_m):.17g}) (0 0 0)))\n"
            )
        stream.write(")\n")
        stream.flush()
    temporary.replace(args.output)
    print(f"converted {len(files)} validated snapshots / {len(records)} rows for slice {args.slice_id} to {args.output}")


if __name__ == "__main__":
    main()
