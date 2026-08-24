"""Atomically add one completed benchmark result to the audit matrix."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    result_path = Path(args.result).resolve()
    matrix_path = Path(args.input).resolve()
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("status") != "completed" or not result.get("real_measurement"):
        raise SystemExit("only a completed real benchmark may enter the matrix")
    label = str(result.get("configuration_label", ""))
    if not label:
        raise SystemExit("benchmark result has no configuration_label")
    matrix = json.loads(matrix_path.read_text(encoding="utf-8")) if matrix_path.is_file() else {
        "metadata": {"real_measurement": True, "source": "user-session benchmark runner"}}
    metadata = matrix.setdefault("metadata", {})
    for key in ("source_global_step", "source_time_s", "source_tick", "global_dt_s", "source_checkpoint_sha256"):
        if key in result:
            if key in metadata and metadata[key] != result[key]:
                raise SystemExit(f"source metadata conflict for {key}")
            metadata[key] = result[key]
    previous = matrix.get(label)
    if previous is None:
        matrix[label] = [result]
    elif isinstance(previous, list):
        matrix[label] = previous + [result]
    else:
        matrix[label] = [previous, result]
    matrix_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = matrix_path.with_name(matrix_path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(matrix, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, matrix_path)
    print(json.dumps({"label": label, "input": str(matrix_path), "samples": len(matrix[label])}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
