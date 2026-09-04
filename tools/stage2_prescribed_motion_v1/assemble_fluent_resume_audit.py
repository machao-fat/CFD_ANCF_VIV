#!/usr/bin/env python3
"""Assemble a strict t=0..T Fluent audit view from checkpoint and restart outputs."""
from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path


FORCES = ("drag-force-rfile.out", "lift-force-rfile.out", "moment-z-rfile.out")
MOTION = "stage2_fluent_motion_audit.csv"


def numeric_rows(path: Path, sep: str) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = [float(x) for x in line.split(sep)]
        except ValueError:
            continue
        if row:
            rows.append(row)
    return rows


def check_times(rows: list[list[float]], time_index: int, dt: float, label: str) -> None:
    if not rows:
        raise ValueError(f"{label}: no numeric rows")
    if not all(math.isfinite(x) for row in rows for x in row):
        raise ValueError(f"{label}: non-finite value")
    for prev, cur in zip(rows, rows[1:]):
        if abs((cur[time_index] - prev[time_index]) - dt) > dt * 0.02:
            raise ValueError(f"{label}: time gap/overlap at {prev[time_index]} -> {cur[time_index]}")


def write_force(path: Path, rows: list[list[float]]) -> None:
    path.write_text("\n".join(" ".join(f"{x:.16g}" for x in row) for row in rows) + "\n", encoding="utf-8")


def write_motion(path: Path, rows: list[list[float]]) -> None:
    path.write_text("time_s,y_m,vy_m_s\n" + "\n".join(
        ",".join(f"{x:.16g}" for x in row) for row in rows
    ) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--dt", type=float, default=0.0025)
    args = p.parse_args()
    run = args.run_dir
    out = run / "audit_inputs_t0_to_20s"
    if out.exists():
        raise SystemExit(f"refusing to overwrite existing audit directory: {out}")
    out.mkdir()
    manifest: dict[str, object] = {"dt_s": args.dt, "files": {}}
    for name in FORCES:
        first = numeric_rows(run / f"checkpoint_1s_{name}", " ")
        rest = numeric_rows(run / name, " ")
        rows = first + rest
        check_times(rows, 2, args.dt, name)
        write_force(out / name, rows)
        manifest["files"][name] = {"checkpoint_rows": len(first), "restart_rows": len(rest), "merged_rows": len(rows), "start_s": rows[0][2], "end_s": rows[-1][2]}
    first_m = numeric_rows(run / f"checkpoint_1s_{MOTION}", ",")
    rest_m = numeric_rows(run / MOTION, ",")
    motion = first_m + rest_m
    check_times(motion, 0, args.dt, MOTION)
    write_motion(out / MOTION, motion)
    manifest["files"][MOTION] = {"checkpoint_rows": len(first_m), "restart_rows": len(rest_m), "merged_rows": len(motion), "start_s": motion[0][0], "end_s": motion[-1][0]}
    transcript = max(run.glob("*.trn"), key=lambda f: f.stat().st_mtime_ns)
    shutil.copy2(transcript, out / transcript.name)
    manifest["transcript"] = transcript.name
    (out / "assembly_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
