from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--end-time", type=float, default=0.5)
    args = parser.parse_args()
    if args.target.exists():
        raise SystemExit(f"refusing to overwrite: {args.target}")
    shutil.copytree(args.source, args.target)
    for relative in (Path("coupling"), Path("postProcessing")):
        path = args.target / relative
        if path.exists():
            shutil.rmtree(path)
    (args.target / "coupling").mkdir(parents=True)
    control = args.target / "system" / "controlDict"
    text = control.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(\s*startFrom\s+).+;", r"\g<1>startTime;", text)
    text = re.sub(r"(?m)^(\s*startTime\s+).+;", r"\g<1>0;", text)
    text = re.sub(r"(?m)^(\s*endTime\s+).+;", rf"\g<1>{args.end_time:.12g};", text)
    control.write_text(text, encoding="utf-8")
    payload = {
        "status": "fresh_single_restart_case",
        "source": str(args.source.resolve()),
        "target": str(args.target.resolve()),
        "first_segment_end_s": args.end_time,
        "old_results_reused": False,
    }
    audit = args.target.with_name(args.target.name + "_audit.json")
    audit.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
