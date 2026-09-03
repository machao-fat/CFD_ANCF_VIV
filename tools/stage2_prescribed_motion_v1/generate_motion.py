#!/usr/bin/env python3
"""Generate a deterministic prescribed cylinder motion table for Stage 2."""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--end-time", type=float, default=1.0)
    p.add_argument("--dt", type=float, default=0.0025)
    p.add_argument("--amplitude", type=float, default=0.10)
    p.add_argument("--frequency", type=float, default=0.16)
    args = p.parse_args()
    if args.end_time <= 0 or args.dt <= 0 or args.amplitude < 0 or args.frequency <= 0:
        raise SystemExit("invalid motion parameters")
    n = int(round(args.end_time / args.dt))
    if abs(n * args.dt - args.end_time) > 1e-12:
        raise SystemExit("end-time must be an integer multiple of dt")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["schema_version", "step", "time_s", "x_m", "y_m", "vx_m_s", "vy_m_s"])
        for step in range(n + 1):
            t = step * args.dt
            omega = 2.0 * math.pi * args.frequency
            w.writerow([
                "stage2.motion.v1", step, f"{t:.12g}", "0",
                f"{args.amplitude * math.sin(omega * t):.12g}", "0",
                f"{args.amplitude * omega * math.cos(omega * t):.12g}",
            ])


if __name__ == "__main__":
    main()
