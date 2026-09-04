#!/usr/bin/env python3
"""Fail-closed audit for Fluent Stage 2 prescribed-motion smoke reports."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def report_rows(path: Path) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            values = [float(value) for value in line.split()]
        except ValueError:
            continue
        if values:
            rows.append(values)
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--fluent-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--expected-end-time", type=float, default=1.0)
    p.add_argument("--dt", type=float, default=0.0025)
    args = p.parse_args()
    found = {}
    for name in ("drag_force-rfile.out", "lift_force-rfile.out", "moment_z-rfile.out"):
        matches = sorted(args.fluent_root.rglob(name), key=lambda item: item.stat().st_mtime_ns)
        found[name] = matches[-1] if matches else None
    rows = {name: report_rows(path) if path else [] for name, path in found.items()}
    expected_steps = round(args.expected_end_time / args.dt)
    drag = rows["drag_force-rfile.out"]
    lift = rows["lift_force-rfile.out"]
    time_ok = bool(drag and abs(drag[-1][2] - args.expected_end_time) <= args.dt * 0.51)
    count_ok = len(drag) >= expected_steps + 1 and len(lift) >= expected_steps + 1
    finite = all(all(value == value and abs(value) != float("inf") for value in row) for group in rows.values() for row in group)
    status = "PASS" if time_ok and count_ok and finite else "FAIL_CLOSED"
    report = {
        "gate_id": "STAGE2_FLUENT_V2_SMOKE_AUDIT",
        "status": status,
        "expected_end_time_s": args.expected_end_time,
        "expected_steps": expected_steps,
        "report_files": {name: str(path) if path else None for name, path in found.items()},
        "row_counts": {name: len(group) for name, group in rows.items()},
        "last_drag_time_s": drag[-1][2] if drag and len(drag[-1]) >= 3 else None,
        "time_ok": time_ok,
        "count_ok": count_ok,
        "finite": finite,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
