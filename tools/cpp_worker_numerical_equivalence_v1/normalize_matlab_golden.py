"""Normalize MATLAB golden JSONL payload hashes for the C++ validator.

MATLAB's exporter records the hash of its JSON round-trip byte payload.  The
offline C++ validator uses a canonical little-endian IEEE-754 representation,
so this tool preserves the original hash and emits the validator's canonical
hash without changing any numerical values or identities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
from pathlib import Path
from typing import Any


VECTOR_FIELDS = (
    "q",
    "qdot",
    "qddot",
    "internal_force",
    "external_force",
    "generalized_force",
    "predictor",
    "corrector",
)


def _canonical_payload(row: dict[str, Any]) -> bytes:
    values: list[float] = []
    for field in VECTOR_FIELDS:
        vector = row.get(field)
        if not isinstance(vector, list) or len(vector) != 102:
            raise ValueError(f"{field} must contain 102 values")
        converted = [float(value) for value in vector]
        if any(not math.isfinite(value) for value in converted):
            raise ValueError(f"{field} contains NaN/Inf")
        values.extend(converted)
    return struct.pack("<" + "d" * len(values), *values)


def normalize(raw_path: Path, output_path: Path) -> int:
    if not raw_path.is_file():
        raise FileNotFoundError(raw_path)
    if output_path.exists():
        raise FileExistsError(output_path)

    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 40:
        raise ValueError(f"expected 40 records, got {len(rows)}")

    normalized: list[str] = []
    for index, row in enumerate(rows, start=1):
        payload = _canonical_payload(row)
        original_hash = str(row.get("payload_hash", ""))
        if not original_hash:
            raise ValueError(f"missing original payload hash at index {index}")
        converted = dict(row)
        converted["matlab_payload_hash_original"] = original_hash
        converted["payload_hash"] = hashlib.sha256(payload).hexdigest()
        converted["payload_hash_normalization"] = "canonical_little_endian_float64"
        converted["payload_size_bytes"] = len(payload)
        normalized.append(json.dumps(converted, ensure_ascii=True, sort_keys=True, separators=(",", ":")))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    temporary.write_text("\n".join(normalized) + "\n", encoding="utf-8")
    os.replace(temporary, output_path)
    return len(normalized)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    count = normalize(args.raw.resolve(), args.output.resolve())
    print(json.dumps({"status": "pass", "count": count, "output": str(args.output.resolve())}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
