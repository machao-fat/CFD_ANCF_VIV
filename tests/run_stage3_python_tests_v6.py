"""Run the complete Stage-3 Python regression suite and preserve v6 evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results" / "04_continuous_fsi" / "stage3_v6_test_results.json"


def main() -> int:
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py", "-v"]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    combined = completed.stdout + completed.stderr
    ran = None
    marker = "Ran "
    if marker in combined:
        try:
            ran = int(combined.split(marker, 1)[1].split(" tests", 1)[0])
        except (ValueError, IndexError):
            ran = None
    payload = {
        "status": "pass" if completed.returncode == 0 else "fail",
        "command": " ".join(command),
        "returncode": completed.returncode,
        "tests_run": ran,
        "total": ran or 0,
        "passed": ran if completed.returncode == 0 and ran is not None else 0,
        "failed": 0 if completed.returncode == 0 else max(ran or 0, 1),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "response_cycle_v6_tests_included": "test_response_cycle_and_classification_v6" in combined,
        "stdout_tail": completed.stdout[-6000:],
        "stderr_tail": completed.stderr[-6000:],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "tests_run": ran, "v6_tests_included": payload["response_cycle_v6_tests_included"], "output": str(OUTPUT)}, ensure_ascii=False))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
