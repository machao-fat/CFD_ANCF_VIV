"""Run the full Python regression suite and persist a v8-labelled result."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/04_continuous_fsi/stage3_v8_test_results.json"


def main() -> None:
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py", "-v"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    stdout = completed.stdout
    stderr = completed.stderr
    import re
    match = re.search(r"Ran (\d+) tests?", stdout + "\n" + stderr)
    tests_run = int(match.group(1)) if match else 0
    passed = tests_run if completed.returncode == 0 else 0
    report = {
        "schema_version": "stage3_v8_python_regression",
        "status": "pass" if completed.returncode == 0 else "fail",
        "command": " ".join(command),
        "returncode": completed.returncode,
        "tests_run": tests_run,
        "total": tests_run,
        "passed": passed,
        "failed": tests_run - passed,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "v8_asymptotic_and_dt_tests_included": "test_asymptotic_v8" in stdout + stderr and "test_long_window_dt_v8" in stdout + stderr,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-12000:],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "tests_run": tests_run, "passed": passed, "failed": report["failed"]}, indent=2))
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
