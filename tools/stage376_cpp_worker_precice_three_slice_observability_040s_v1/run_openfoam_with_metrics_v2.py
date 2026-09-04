"""OpenFOAM quality wrapper using the strict pending-Courant parser."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.convergence_observability_v2 import OpenFOAMQualityError, OpenFOAMQualityParser  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--failure-tail", required=True)
    parser.add_argument("solver", nargs=argparse.REMAINDER, default=["pimpleFoam"])
    args = parser.parse_args()
    command = list(args.solver or ["pimpleFoam"])
    if command and command[0] == "--":
        command = command[1:]
    quality = OpenFOAMQualityParser()
    tail: deque[str] = deque(maxlen=200)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
    assert process.stdout is not None
    for line in process.stdout:
        quality.feed(line)
        tail.append(line.rstrip("\r\n"))
    return_code = process.wait()
    try:
        records = quality.finalize()
    except OpenFOAMQualityError as exc:
        records = []
        if return_code == 0:
            return_code = 2
        tail.append(f"quality_parser: {type(exc).__name__}: {exc}")
    output = {"schema_version": 2, "solver": command, "return_code": return_code, "records": records, "record_count": len(records), "parser": "convergence_observability_v2.pending_courant"}
    out = Path(args.metrics)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if return_code != 0:
        failure = Path(args.failure_tail)
        failure.parent.mkdir(parents=True, exist_ok=True)
        failure.write_text("\n".join(tail) + "\n", encoding="utf-8")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
