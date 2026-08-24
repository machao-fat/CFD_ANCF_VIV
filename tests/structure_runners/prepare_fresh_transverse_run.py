from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--end-time", type=float)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing run case: {args.output}")
    shutil.copytree(args.source, args.output)
    coupling = args.output / "coupling"
    if coupling.exists():
        for item in coupling.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    coupling.mkdir(parents=True, exist_ok=True)
    post = args.output / "postProcessing"
    if post.exists():
        shutil.rmtree(post)
    if args.end_time is not None:
        control = args.output / "system" / "controlDict"
        text = control.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^(\s*endTime\s+).+;", rf"\g<1>{args.end_time:.12g};", text)
        control.write_text(text, encoding="utf-8")
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    audit = {
        "status": "fresh_transverse_run_case",
        "source": str(args.source.resolve()),
        "output": str(args.output.resolve()),
        "coupling_empty_at_creation": not any(coupling.iterdir()),
        "postProcessing_absent_at_creation": not post.exists(),
        "old_motion_or_load_reused": False,
        "end_time_s": args.end_time,
    }
    args.audit.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
