from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


def patch_control(case: Path, end_time: float) -> None:
    path = case / "system" / "controlDict"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(\s*startFrom\s+).+;", r"\g<1>latestTime;", text)
    text = re.sub(r"(?m)^(\s*endTime\s+).+;", rf"\g<1>{end_time:.12g};", text)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-case", type=Path, required=True)
    parser.add_argument("--source-result", type=Path, required=True)
    parser.add_argument("--target-case", type=Path, required=True)
    parser.add_argument("--target-result", type=Path, required=True)
    parser.add_argument("--end-time", type=float, default=70.0)
    args = parser.parse_args()
    for target in (args.target_case, args.target_result):
        if target.exists():
            raise SystemExit(f"refusing to overwrite existing continuation target: {target}")
    shutil.copytree(args.source_case, args.target_case)
    shutil.copytree(args.source_result, args.target_result)
    coupling = args.target_case / "coupling"
    if coupling.exists():
        shutil.rmtree(coupling)
    coupling.mkdir(parents=True)
    patch_control(args.target_case, args.end_time)
    payload = {
        "status": "fresh_long_continuation_prepared",
        "source_case": str(args.source_case.resolve()),
        "source_result": str(args.source_result.resolve()),
        "target_case": str(args.target_case.resolve()),
        "target_result": str(args.target_result.resolve()),
        "restart_time_s": 10.0,
        "end_time_s": args.end_time,
        "restart_checkpoint": str((args.target_result / "sdof_checkpoint.json").resolve()),
        "old_10s_result_overwritten": False,
        "old_checkpoint_reused_as_restart_input": True,
    }
    audit = args.target_result / "long_preparation.json"
    audit.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
