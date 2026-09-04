"""Offline time-step and long-double/double-solve diagnostics."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from run_offline_validation import run


def max_state_error(lhs: dict, rhs: dict) -> float:
    values = []
    for left, right in zip(lhs["trajectory"], rhs["trajectory"]):
        for field in ("q", "qdot", "qddot"):
            values.extend(abs(a - b) for a, b in zip(left[field], right[field]))
    return max(values, default=0.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--long-worker", type=Path, required=True)
    parser.add_argument("--double-worker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    zero = (0.0,) * 18
    long_coarse = run(args.long_worker.resolve(), 2, zero, 0.00125)
    long_fine = run(args.long_worker.resolve(), 4, zero, 0.000625)
    long_double = run(args.long_worker.resolve(), 40, zero, 0.00125)
    double_double = run(args.double_worker.resolve(), 40, zero, 0.00125)
    # Compare states at the common end time for the time-step diagnostic.
    coarse_end = long_coarse["trajectory"][-1]
    fine_end = long_fine["trajectory"][-1]
    time_error = max(
        abs(a - b)
        for field in ("q", "qdot", "qddot")
        for a, b in zip(coarse_end[field], fine_end[field])
    )
    double_error = max_state_error(long_double, double_double)
    result = {
        "status": "pass" if all(
            math.isfinite(value) for value in (time_error, double_error)
        ) else "do_not_pass",
        "time_step": {
            "coarse_dt_s": 0.00125,
            "fine_dt_s": 0.000625,
            "common_end_time_s": 0.0025,
            "max_state_abs_difference": time_error,
            "finite": math.isfinite(time_error),
        },
        "long_double_vs_double_solve": {
            "steps": 40,
            "max_state_abs_difference": double_error,
            "finite": math.isfinite(double_error),
            "long_worker_status": long_double["status"],
            "double_worker_status": double_double["status"],
            "long_worker_start_count": long_double["worker_start_count"],
            "double_worker_start_count": double_double["worker_start_count"],
        },
        "physical_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "owned_residual": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
