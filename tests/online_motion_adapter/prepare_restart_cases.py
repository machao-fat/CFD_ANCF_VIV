from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


def set_control(case: Path, *, end_time: float, latest: bool) -> None:
    path = case / "system" / "controlDict"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(\s*startFrom\s+).+;", rf"\g<1>{'latestTime' if latest else 'startTime'};", text)
    text = re.sub(r"(?m)^(\s*startTime\s+).+;", r"\g<1>0;", text)
    text = re.sub(r"(?m)^(\s*endTime\s+).+;", rf"\g<1>{end_time:.12g};", text)
    path.write_text(text, encoding="utf-8")


def fresh_copy(source: Path, target: Path, *, end_time: float) -> None:
    if target.exists():
        raise SystemExit(f"refusing to overwrite restart case: {target}")
    shutil.copytree(source, target)
    coupling = target / "coupling"
    if coupling.exists():
        shutil.rmtree(coupling)
    coupling.mkdir(parents=True, exist_ok=True)
    post = target / "postProcessing"
    if post.exists():
        shutil.rmtree(post)
    set_control(target, end_time=end_time, latest=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-native", type=Path, required=True)
    parser.add_argument("--source-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    root = args.output_root
    root.mkdir(parents=True, exist_ok=True)
    names = {
        "native_reference": root / "native_reference",
        "native_restart": root / "native_restart",
        "file_reference": root / "file_reference",
        "file_restart": root / "file_restart",
    }
    fresh_copy(args.source_native, names["native_reference"], end_time=1.0)
    fresh_copy(args.source_native, names["native_restart"], end_time=0.5)
    fresh_copy(args.source_file, names["file_reference"], end_time=1.0)
    fresh_copy(args.source_file, names["file_restart"], end_time=0.5)
    payload = {
        "status": "fresh_restart_cases",
        "source_native": str(args.source_native.resolve()),
        "source_file": str(args.source_file.resolve()),
        "cases": {key: str(value.resolve()) for key, value in names.items()},
        "first_segment_end_s": 0.5,
        "final_end_s": 1.0,
        "old_results_reused": False,
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
