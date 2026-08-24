from __future__ import annotations

import json
from pathlib import Path

from ..multi_slice_mapping.mapping import atomic_write_json
from .engine import factory
from .execute import execute_d2


def run(preflight_path: Path, output: Path) -> dict:
    checked = json.loads(preflight_path.read_text(encoding="utf-8"))
    if checked.get("status") != "passed" or checked.get("branch") != "D2":
        raise RuntimeError("D2 preflight does not authorize this run")
    engine, shutdown = factory(checked["plan"])
    value = execute_d2(engine, shutdown)
    atomic_write_json(output, value)
    return value


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.preflight, args.output)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result.get("execution_error") is None else 2)

