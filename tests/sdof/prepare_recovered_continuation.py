from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-case", type=Path, required=True)
    parser.add_argument("--source-result", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--target-case", type=Path, required=True)
    parser.add_argument("--target-result", type=Path, required=True)
    parser.add_argument("--end-time", type=float, required=True)
    args = parser.parse_args()
    if args.target_case.exists() or args.target_result.exists():
        raise SystemExit("refusing to overwrite recovered continuation target")
    shutil.copytree(args.source_case, args.target_case)
    shutil.copytree(args.source_result, args.target_result)
    coupling = args.target_case / "coupling"
    if coupling.exists():
        shutil.rmtree(coupling)
    coupling.mkdir(parents=True)
    control = args.target_case / "system" / "controlDict"
    text = control.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(\s*startFrom\s+).+;", r"\g<1>latestTime;", text)
    text = re.sub(r"(?m)^(\s*endTime\s+).+;", rf"\g<1>{args.end_time:.12g};", text)
    text = re.sub(r"(?m)^\s*log\s+yes;", "        log             no;", text)
    control.write_text(text, encoding="utf-8")
    shutil.copy2(args.checkpoint, args.target_result / "sdof_checkpoint.json")
    payload = {
        "status": "prepared_from_recovered_checkpoint",
        "source_case": str(args.source_case.resolve()),
        "source_result": str(args.source_result.resolve()),
        "checkpoint": str(args.checkpoint.resolve()),
        "target_case": str(args.target_case.resolve()),
        "target_result": str(args.target_result.resolve()),
        "end_time_s": args.end_time,
        "old_targets_overwritten": False,
    }
    (args.target_result / "recovered_preparation.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
