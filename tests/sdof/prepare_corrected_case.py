from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rewrite_field(source: Path, target: Path, *, moving_wall: bool) -> None:
    text = source.read_text(encoding="utf-8")
    text = re.sub(r'(?m)^(\s*location\s+)"?30"?\s*;', r'\g<1>"0";', text)
    if moving_wall:
        pattern = r'(?ms)(^\s*cylinder\s*\{)(.*?)(^\s*\})'
        match = re.search(pattern, text)
        if not match:
            raise ValueError(f"cylinder patch not found in {source}")
        body = re.sub(r'(?m)^\s*type\s+[^;]+;', "        type            movingWallVelocity;", match.group(2), count=1)
        if "value" in body:
            body = re.sub(r'(?m)^\s*value\s+[^;]+;', "        value           uniform (0 0 0);", body, count=1)
        else:
            body += "\n        value           uniform (0 0 0);\n"
        text = text[: match.start(2)] + body + text[match.end(2):]
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-case", type=Path, required=True)
    parser.add_argument("--template-case", type=Path, required=True)
    parser.add_argument("--output-case", type=Path, required=True)
    parser.add_argument("--end-time", type=float, required=True)
    parser.add_argument("--dt", type=float, default=0.0025)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    source_time = args.source_case / "30"
    if not (source_time / "U").is_file() or not (source_time / "p").is_file():
        raise SystemExit(f"source 30 s U/p are missing: {source_time}")
    if args.output_case.exists():
        raise SystemExit(f"refusing to overwrite existing case: {args.output_case}")
    shutil.copytree(args.template_case, args.output_case)
    (args.output_case / "coupling").mkdir(parents=True, exist_ok=True)
    rewrite_field(source_time / "U", args.output_case / "0" / "U", moving_wall=True)
    rewrite_field(source_time / "p", args.output_case / "0" / "p", moving_wall=False)
    control = args.output_case / "system" / "controlDict"
    control_text = control.read_text(encoding="utf-8")
    control_text = re.sub(r"(?m)^(\s*startFrom\s+).+;", r"\1startTime;", control_text)
    control_text = re.sub(r"(?m)^(\s*startTime\s+).+;", r"\g<1>0;", control_text)
    control_text = re.sub(r"(?m)^(\s*endTime\s+).+;", rf"\g<1>{args.end_time:.12g};", control_text)
    control_text = re.sub(r"(?m)^(\s*deltaT\s+).+;", rf"\g<1>{args.dt:.12g};", control_text)
    with control.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(control_text)
    dynamic_mesh = args.output_case / "constant" / "dynamicMeshDict"
    dynamic_text = dynamic_mesh.read_text(encoding="utf-8")
    dynamic_text = re.sub(r"(?m)^(\s*couplingDeltaT\s+).+;", rf"\g<1>{args.dt:.12g};", dynamic_text)
    dynamic_mesh.write_text(dynamic_text, encoding="utf-8")
    source_hashes = {name: sha256(source_time / name) for name in ("U", "p")}
    target_hashes = {name: sha256(args.output_case / "0" / name) for name in ("U", "p")}
    audit = {
        "status": "prepared_from_source_30s",
        "source_case": str(args.source_case.resolve()),
        "source_time": "30",
        "template_case": str(args.template_case.resolve()),
        "output_case": str(args.output_case.resolve()),
        "source_U_sha256": source_hashes["U"],
        "source_p_sha256": source_hashes["p"],
        "target_U_sha256": target_hashes["U"],
        "target_p_sha256": target_hashes["p"],
        "target_field_location": "0",
        "target_cylinder_boundary": "movingWallVelocity",
        "old_sdof_case_or_checkpoint_reused": False,
        "end_time_s": args.end_time,
        "dt_s": args.dt,
    }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
