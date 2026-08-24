#!/usr/bin/env python3
"""Seed the stage-three-compatible materialized motion view for smoke cases."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from pathlib import Path


FIELDS = (
    "schema_version", "step", "coupling_iteration", "time_s", "slice_id", "s_ref_m",
    "x_m", "y_m", "z_m", "vx_mps", "vy_mps", "vz_mps", "ax_mps2", "ay_mps2", "az_mps2",
)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        temporary_path.write_text(text, encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, action="append", required=True)
    parser.add_argument("--slice-id", type=int, action="append", required=True)
    parser.add_argument("--s-ref-m", type=float, action="append", required=True)
    args = parser.parse_args()
    if not (len(args.case) == len(args.slice_id) == len(args.s_ref_m)):
        raise SystemExit("case, slice-id and s-ref-m counts must match")
    for case, slice_id, s_ref in zip(args.case, args.slice_id, args.s_ref_m):
        coupling = case / "coupling"
        output = coupling / "motion.csv"
        row = {
            "schema_version": "0.1.0", "step": 0, "coupling_iteration": 0,
            "time_s": 0.0, "slice_id": slice_id, "s_ref_m": s_ref,
            "x_m": 0.0, "y_m": 0.0, "z_m": 0.0,
            "vx_mps": 0.0, "vy_mps": 0.0, "vz_mps": 0.0,
            "ax_mps2": 0.0, "ay_mps2": 0.0, "az_mps2": 0.0,
        }
        stream = __import__("io").StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
        atomic_write(output, stream.getvalue())
        marker = {"kind": "motion_ready", "payload": "motion.csv", "step": 0, "time_s": 0.0}
        atomic_write(coupling / "motion_ready", json.dumps(marker, sort_keys=True) + "\n")
    print(json.dumps({"status": "seeded", "cases": [str(path) for path in args.case]}, sort_keys=True))


if __name__ == "__main__":
    main()
