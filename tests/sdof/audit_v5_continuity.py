"""Audit time-series continuity across checkpoint-spliced SDOF segments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_long_sdof import merge_rows


def boundary(rows: list[dict[str, float]], time_s: float) -> dict[str, object]:
    # Compare the last state before the checkpoint with the first state
    # after it.  Do not compare a duplicated checkpoint row with itself.
    before = max((row for row in rows if row["time_s"] < time_s - 1e-12), key=lambda row: row["time_s"], default=None)
    after = min((row for row in rows if row["time_s"] > time_s + 1e-12), key=lambda row: row["time_s"], default=None)
    if before is None or after is None:
        return {"boundary_s": time_s, "available": False}
    fields = ("y_m", "vy_mps", "ay_mps2", "force_y_N", "Cl", "Cd", "fluid_work_J", "damping_dissipation_J", "mechanical_energy_J")
    return {
        "boundary_s": time_s,
        "available": True,
        "step_before": before["step"], "step_after": after["step"],
        "time_before_s": before["time_s"], "time_after_s": after["time_s"],
        "time_gap_s": after["time_s"] - before["time_s"],
        "jumps": {field: after[field] - before[field] for field in fields},
        "finite": all(value == value and abs(value) != float("inf") for field in fields for value in (before[field], after[field])),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, nargs="+", required=True)
    parser.add_argument("--boundary", type=float, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = merge_rows(args.audit)
    dt_values = [rows[i]["time_s"] - rows[i - 1]["time_s"] for i in range(1, len(rows))]
    payload = {
        "status": "pass" if max(dt_values) <= 1.5 * min(dt_values) and all(row["finite"] for row in (boundary(rows, t) for t in args.boundary) if row["available"]) else "fail",
        "time_start_s": rows[0]["time_s"], "time_end_s": rows[-1]["time_s"],
        "rows": len(rows), "dt_min_s": min(dt_values), "dt_max_s": max(dt_values),
        "boundaries": [boundary(rows, time_s) for time_s in args.boundary],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, allow_nan=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "time_end_s": payload["time_end_s"], "rows": payload["rows"]}, indent=2))


if __name__ == "__main__":
    main()
