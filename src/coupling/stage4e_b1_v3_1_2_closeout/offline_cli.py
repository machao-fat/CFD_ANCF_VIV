from __future__ import annotations

import argparse
from pathlib import Path

from .offline import revalidate_existing_probe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    result = revalidate_existing_probe(Path(args.project_root), Path(args.output_dir))
    print(result["status"])
    print(result["source_payload_sha256"])
    print(result["old_failed_checks"])
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

