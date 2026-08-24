from __future__ import annotations

import argparse
from pathlib import Path

from .smoke import run_worker_smoke


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--matlab-exe", required=True)
    args = parser.parse_args()
    result = run_worker_smoke(project_root=Path(args.project_root), output_dir=Path(args.output_dir), matlab_exe=Path(args.matlab_exe))
    print(result["status"])
    if result.get("error"):
        print(result["error"])
    print(result.get("owned_residual_count"))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

