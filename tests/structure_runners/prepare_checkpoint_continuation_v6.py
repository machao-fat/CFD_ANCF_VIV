"""Prepare a non-overwriting EB/ANCF continuation from a MATLAB checkpoint."""

from __future__ import annotations

import argparse
import csv
import re
import shutil
from pathlib import Path


def trim_forces(path: Path, end_time: float) -> None:
    if not path.is_file():
        return
    kept: list[str] = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if not line.strip() or line.lstrip().startswith("#"):
                kept.append(line)
                continue
            try:
                time_s = float(line.split()[0])
            except (ValueError, IndexError):
                kept.append(line)
                continue
            if time_s <= end_time + 1.0e-12:
                kept.append(line)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(kept), encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-case", type=Path, required=True)
    parser.add_argument("--source-result", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--target-case", type=Path, required=True)
    parser.add_argument("--target-result", type=Path, required=True)
    parser.add_argument("--checkpoint-time", type=float, required=True)
    parser.add_argument("--end-time", type=float, required=True)
    args = parser.parse_args()
    if args.target_case.exists() or args.target_result.exists():
        raise SystemExit("refusing to overwrite existing v6 continuation target")
    if not args.checkpoint.is_file():
        raise FileNotFoundError(args.checkpoint)
    shutil.copytree(args.source_case, args.target_case)
    shutil.copytree(args.source_result, args.target_result)
    for path in (args.target_case / "coupling", args.target_result / "matlab_runner"):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    # The CFD solver must restart at exactly the structure checkpoint, not at
    # a later copied time directory.
    for child in args.target_case.iterdir():
        if not child.is_dir():
            continue
        try:
            value = float(child.name)
        except ValueError:
            continue
        if value > args.checkpoint_time + 1.0e-12:
            shutil.rmtree(child)
    control = args.target_case / "system" / "controlDict"
    text = control.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(\s*startFrom\s+).+;", r"\g<1>latestTime;", text)
    text = re.sub(r"(?m)^(\s*endTime\s+).+;", rf"\g<1>{args.end_time:.12g};", text)
    control.write_text(text, encoding="utf-8")
    forces = args.target_case / "postProcessing" / "cylinderForces" / "0" / "forces.dat"
    trim_forces(forces, args.checkpoint_time)
    shutil.copy2(args.checkpoint, args.target_result / "midpoint_runner_checkpoint.mat")
    marker = {
        "status": "prepared_from_common_checkpoint_v6",
        "source_case": str(args.source_case.resolve()),
        "source_result": str(args.source_result.resolve()),
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_time_s": args.checkpoint_time,
        "checkpoint_time_directories_removed": True,
        "forces_trimmed_to_checkpoint": True,
        "target_case": str(args.target_case.resolve()),
        "target_result": str(args.target_result.resolve()),
        "end_time_s": args.end_time,
        "old_targets_overwritten": False,
    }
    (args.target_result / "checkpoint_continuation_preparation_v6.json").write_text(__import__("json").dumps(marker, indent=2) + "\n", encoding="utf-8")
    print(__import__("json").dumps(marker, indent=2))


if __name__ == "__main__":
    main()
