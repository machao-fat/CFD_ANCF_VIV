from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any, Iterable, Mapping


VECTOR_FIELDS = (
    "q", "qdot", "qddot", "internal_force", "external_force",
    "generalized_force", "predictor", "corrector",
)


class GoldenValidationError(ValueError):
    pass


def _vector(record: Mapping[str, Any], field: str, length: int = 102) -> tuple[float, ...]:
    raw = record.get(field)
    if not isinstance(raw, list) or len(raw) != length:
        raise GoldenValidationError(f"{field} dimension mismatch")
    values = tuple(float(value) for value in raw)
    if any(not math.isfinite(value) for value in values):
        raise GoldenValidationError(f"{field} contains NaN/Inf")
    return values


def validate_record(record: Mapping[str, Any], index: int, *, run_id: str, case_id: str) -> dict[str, Any]:
    expected_step = 559 + index
    expected_time = 2.2075 + index * 0.00125
    if record.get("run_id") != run_id or record.get("case_id") != case_id:
        raise GoldenValidationError(f"identity mismatch at index {index}")
    if int(record.get("global_step", -1)) != expected_step or int(record.get("case_local_bridge_step", -1)) != index:
        raise GoldenValidationError(f"step/bridge mismatch at index {index}")
    if not math.isclose(float(record.get("time_s", float("nan"))), expected_time, rel_tol=0.0, abs_tol=1e-12):
        raise GoldenValidationError(f"time mismatch at index {index}")
    if int(record.get("integer_tick", -1)) != round(expected_time * 1e9):
        raise GoldenValidationError(f"tick mismatch at index {index}")
    if int(record.get("sequence", -1)) != index or int(record.get("request_id", -1)) != 510000 + index:
        raise GoldenValidationError(f"request sequence mismatch at index {index}")
    if int(record.get("transaction_id", -1)) != 520000 + index or int(record.get("return_code", -1)) != 0:
        raise GoldenValidationError(f"transaction/return mismatch at index {index}")
    if record.get("finite_value_audit") is not True:
        raise GoldenValidationError(f"finite audit failed at index {index}")
    vectors = tuple(_vector(record, field) for field in VECTOR_FIELDS)
    payload = struct.pack("<" + "d" * (len(VECTOR_FIELDS) * 102), *(value for vector in vectors for value in vector))
    expected_hash = hashlib.sha256(payload).hexdigest()
    if str(record.get("payload_hash", "")).lower() != expected_hash:
        raise GoldenValidationError(f"payload hash mismatch at index {index}")
    if int(record.get("payload_size_bytes", -1)) != len(payload):
        raise GoldenValidationError(f"payload size mismatch at index {index}")
    checkpoint = record.get("checkpoint")
    if not isinstance(checkpoint, Mapping) or int(checkpoint.get("step", -1)) != expected_step:
        raise GoldenValidationError(f"checkpoint identity mismatch at index {index}")
    return {"index": index, "global_step": expected_step, "payload_size_bytes": len(payload), "payload_hash": expected_hash}


def validate_jsonl(path: str | Path, *, run_id: str, case_id: str, expected_count: int = 40) -> dict[str, Any]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != expected_count:
        raise GoldenValidationError(f"expected {expected_count} records, got {len(rows)}")
    validated = [validate_record(row, index, run_id=run_id, case_id=case_id) for index, row in enumerate(rows, start=1)]
    return {"status": "pass", "count": len(validated), "records": validated}
