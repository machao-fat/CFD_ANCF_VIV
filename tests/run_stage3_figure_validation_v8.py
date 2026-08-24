"""Persist strict Nature-figure source validation for the v8 figure script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "04_continuous_fsi" / "stage3_v8_figure_validation.json"
VALIDATOR = Path(r"C:\Users\Administrator\.codex\skills\nature-figure\scripts\validate_figure.py")


def main() -> None:
    completed = subprocess.run(
        [sys.executable, str(VALIDATOR), str(ROOT / "tests" / "plot_stage3_v8.py"), "--json", "--strict"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"raw_stdout": completed.stdout, "raw_stderr": completed.stderr}
    payload["validator_returncode"] = completed.returncode
    payload["strict_ready"] = bool(payload.get("summary", {}).get("ready", False))
    payload["output_formats"] = ["PNG", "SVG", "PDF"]
    payload["tiff_omitted_by_v8_request"] = True
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    raise SystemExit(0 if payload["strict_ready"] else 1)


if __name__ == "__main__":
    main()
