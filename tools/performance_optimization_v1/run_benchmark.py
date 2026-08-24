from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.coupling.performance_optimization_v1.benchmark import run_offline_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline-only performance optimization benchmark")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--steps", type=int, default=None)
    args = parser.parse_args()
    report = run_offline_benchmark(args.root, steps=args.steps)
    print(json.dumps({"status": report["gate"]["status"], "report": str(args.root / "results" / "90_performance_optimization_v1" / "performance_optimization_v1_report.json"),
                      "external_process_starts": report["gate"]["external_process_starts"], "owned_residual": report["gate"]["owned_residual"]}, ensure_ascii=False))
    return 0 if report["gate"]["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
