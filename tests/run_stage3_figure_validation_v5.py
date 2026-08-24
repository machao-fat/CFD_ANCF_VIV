"""Run strict Nature-style source QA for every v5 Python figure generator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = Path(r"C:\Users\Administrator\.codex\skills\nature-figure\scripts\validate_figure.py")
SOURCES = [
    ROOT / "tests" / "sdof" / "plot_five_point_v5.py",
    ROOT / "tests" / "sdof" / "plot_ur5p2_extended_v5.py",
    ROOT / "tests" / "structure_runners" / "plot_long_time_online_comparison_v5.py",
]
OUTPUT = ROOT / "results" / "04_continuous_fsi" / "stage3_v5_figure_validation.json"


def main() -> int:
    records = []
    returncode = 0
    for source in SOURCES:
        command = [sys.executable, str(VALIDATOR), "--backend", "python", "--json", "--strict", str(source)]
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        returncode = max(returncode, completed.returncode)
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError:
            report = {"ready": False, "raw_output": completed.stdout, "stderr": completed.stderr}
        records.append({"source": str(source), "returncode": completed.returncode, "ready": report.get("summary", {}).get("ready", False), "report": report})
    payload = {"status": "pass" if returncode == 0 else "fail", "sources": records}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "sources": len(records), "output": str(OUTPUT)}, ensure_ascii=False))
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
