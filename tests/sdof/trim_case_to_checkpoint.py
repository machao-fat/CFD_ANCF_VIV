from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--time", type=float, required=True)
    parser.add_argument("--remove-incomplete", action="store_true")
    args = parser.parse_args()
    case = args.case.resolve()
    removed = []
    for path in case.iterdir():
        if not path.is_dir():
            continue
        try:
            value = float(path.name)
        except ValueError:
            continue
        if value > args.time + 1.0e-12:
            if not args.remove_incomplete and (not (path / "U").is_file() or not (path / "p").is_file()):
                continue
            shutil.rmtree(path)
            removed.append(path.name)
    print({"case": str(case), "checkpoint_time_s": args.time, "removed_time_directories": removed})


if __name__ == "__main__":
    main()
