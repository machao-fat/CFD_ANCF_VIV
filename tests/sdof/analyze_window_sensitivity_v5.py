"""Window-origin sensitivity audit for the existing Ur=5.2 record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_campaign_point_v5 import audit
from analyze_long_sdof import merge_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, nargs="+", required=True)
    parser.add_argument("--log", type=Path, nargs="+", required=True)
    parser.add_argument("--ur", type=float, default=5.2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = merge_rows(args.audit)
    windows = [(58.0, 84.0, 84.0, 110.0), (59.0, 85.0, 85.0, 111.0), (60.0, 86.0, 86.0, 112.0)]
    combinations = []
    for start1, end1, start2, end2 in windows:
        item = audit(rows, args.log, args.ur, start1, end1, start2, end2)
        item["window_pair"] = {"window_1": [start1, end1], "window_2": [start2, end2]}
        combinations.append(item)
    passed = [bool(item["final_steady_window_pass"]) for item in combinations]
    payload = {
        "status": "robust_window_pass" if sum(passed) >= 2 else "boundary_window_pass_only" if any(passed) else "window_sensitivity_fail",
        "ur": args.ur,
        "time_end_s": rows[-1]["time_s"],
        "window_combinations": combinations,
        "passed_combinations": sum(passed),
        "required_passed_combinations": 2,
        "interpretation": "At least two of three translated pairs must pass; one final-window pass alone is boundary evidence only.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "passed_combinations": payload["passed_combinations"]}, indent=2))


if __name__ == "__main__":
    main()
