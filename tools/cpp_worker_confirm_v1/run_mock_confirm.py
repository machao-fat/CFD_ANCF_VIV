from __future__ import annotations

import argparse
from pathlib import Path

from coupling.cpp_worker_confirm_v1.coordinator import run_mock_confirm


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--executable", type=Path)
    args = parser.parse_args()
    gate = run_mock_confirm(runtime=args.runtime, executable=args.executable, results_dir=args.results)
    print(gate["gate"])
    return 0 if gate["gate"].endswith("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
