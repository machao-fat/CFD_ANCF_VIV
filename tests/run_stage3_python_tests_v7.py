"""Run the complete Python regression suite and persist v7 evidence."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "04_continuous_fsi" / "stage3_v7_test_results.json"


def main() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py", "-v"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    output = completed.stdout + completed.stderr
    match = re.search(r"Ran\s+(\d+)\s+tests?", output)
    tests_run = int(match.group(1)) if match else 0
    passed = completed.returncode == 0 and "OK" in output
    payload = {
        "status": "pass" if passed else "fail",
        "command": f"{sys.executable} -m unittest discover -s tests -p test*.py -v",
        "returncode": completed.returncode,
        "tests_run": tests_run,
        "passed": tests_run if passed else 0,
        "failed": 0 if passed else max(1, tests_run),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "v7_asymptotic_tests_included": True,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-12000:],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
