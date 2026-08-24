"""Run the complete unittest-discoverable Stage-3 Python regression suite."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results" / "04_continuous_fsi" / "stage3_v5_python_test_results.json"


def main() -> int:
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py", "-v"]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    combined = completed.stdout + completed.stderr
    marker = "Ran "
    ran = None
    if marker in combined:
        tail = combined.split(marker, 1)[1]
        try:
            ran = int(tail.split(" tests", 1)[0])
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
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "tests_run": ran, "output": str(OUTPUT)}, ensure_ascii=False))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
