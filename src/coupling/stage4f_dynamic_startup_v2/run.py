from __future__ import annotations

import argparse
from pathlib import Path

from .campaign import PROJECT_ROOT, run_dynamic_startup_preflight


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--protocol", type=Path, default=PROJECT_ROOT / "results" / "11_stage4f_lowre_benchmark_design_v2_1" / "three_slice_protocol_0_2_1.json")
    args = parser.parse_args()
    print(run_dynamic_startup_preflight(args.root, args.protocol, steps=args.steps)["status"])


if __name__ == "__main__":
    main()

