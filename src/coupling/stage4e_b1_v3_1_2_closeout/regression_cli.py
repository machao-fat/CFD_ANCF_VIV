from __future__ import annotations

import argparse
from pathlib import Path

from .regression import run_non_matlab_regression, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run_non_matlab_regression(Path(args.project_root))
    write_json(args.output, result)
    print(result["status"], result["tests_run"], result["tests_collected_root"], result["excluded_real_matlab_test_count"])
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

