#!/usr/bin/env python3
"""Fail-closed audit for Fluent Stage 2 prescribed-motion smoke reports."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REPORT_NAMES = ("drag-force-rfile.out", "lift-force-rfile.out", "moment-z-rfile.out")
FAIL_MARKERS = (
    "negative cell volume",
    "update-dynamic-mesh failed",
    "udf library \"libudf\" not available",
)

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


def motion_rows(path: Path) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            values = [float(value) for value in line.split(",")]
        except ValueError:
            continue
        if len(values) >= 5:
            rows.append(values)
    return rows


def newest(root: Path, filename: str) -> Path | None:
    matches = sorted(root.rglob(filename), key=lambda item: item.stat().st_mtime_ns)
    return matches[-1] if matches else None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--fluent-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--expected-end-time", type=float, default=1.0)
    p.add_argument("--dt", type=float, default=0.0025)
    args = p.parse_args()
    found = {name: newest(args.fluent_root, name) for name in REPORT_NAMES}
    rows = {name: report_rows(path) if path else [] for name, path in found.items()}
    expected_steps = round(args.expected_end_time / args.dt)
    time_ok = all(
        group and len(group[-1]) >= 3
        and abs(group[-1][2] - args.expected_end_time) <= args.dt * 0.51
        for group in rows.values()
    )
    count_ok = all(len(group) >= expected_steps + 1 for group in rows.values())
    finite = all(all(value == value and abs(value) != float("inf") for value in row) for group in rows.values() for row in group)
    # Current exact-step UDF audit name; keep the historical name as a
    # fallback for older diagnostic runs.
    motion_path = newest(args.fluent_root, "stage2_fluent_motion_step_exact_audit.csv")
    if motion_path is None:
        motion_path = newest(args.fluent_root, "stage2_fluent_motion_audit.csv")
    motion = motion_rows(motion_path) if motion_path else []
    motion_ok = len(motion) >= expected_steps and all(
        all(value == value and abs(value) != float("inf") for value in row) for row in motion
    )
    transcript = newest(args.fluent_root, "*.trn")
    transcript_text = transcript.read_text(encoding="utf-8", errors="replace").lower() if transcript else ""
    fail_markers = [marker for marker in FAIL_MARKERS if marker in transcript_text]
    udf_registered = "stage2_cylinder_motion" in transcript_text
    status = "PASS" if time_ok and count_ok and finite and motion_ok and transcript and not fail_markers and udf_registered else "FAIL_CLOSED"
    report = {
        "gate_id": "STAGE2_FLUENT_V2_SMOKE_AUDIT",
        "status": status,
        "expected_end_time_s": args.expected_end_time,
        "expected_steps": expected_steps,
        "report_files": {name: str(path) if path else None for name, path in found.items()},
        "row_counts": {name: len(group) for name, group in rows.items()},
        "last_report_times_s": {
            name: group[-1][2] if group and len(group[-1]) >= 3 else None
            for name, group in rows.items()
        },
        "motion_audit_file": str(motion_path) if motion_path else None,
        "motion_audit_row_count": len(motion),
        "motion_ok": motion_ok,
        "transcript": str(transcript) if transcript else None,
        "transcript_fail_markers": fail_markers,
        "udf_registered": udf_registered,
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
