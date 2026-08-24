from __future__ import annotations

import argparse
import re
from pathlib import Path


def patch_control(case: Path, *, end_time: float) -> None:
    path = case / "system" / "controlDict"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(\s*startFrom\s+).+;", r"\g<1>latestTime;", text)
    text = re.sub(r"(?m)^(\s*endTime\s+).+;", rf"\g<1>{end_time:.12g};", text)
    path.write_text(text, encoding="utf-8")


def patch_dynamic_mesh(case: Path, *, consumed_directory: str | None) -> None:
    path = case / "constant" / "dynamicMeshDict"
    text = path.read_text(encoding="utf-8")
    if consumed_directory is not None:
        text = re.sub(r'(?m)^\s*consumedDirectory\s+[^;]+;', f'    consumedDirectory "{consumed_directory}";', text)
        if "consumedDirectory" not in text:
            text += f'\n    consumedDirectory "{consumed_directory}";\n'
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--end-time", type=float, required=True)
    parser.add_argument("--consumed-directory", type=str)
    args = parser.parse_args()
    patch_control(args.case, end_time=args.end_time)
    if args.consumed_directory is not None:
        patch_dynamic_mesh(args.case, consumed_directory=args.consumed_directory)
    print(f"configured restart segment: {args.case} latestTime -> {args.end_time:g}s")


if __name__ == "__main__":
    main()
