"""Validation and comparison primitives for the production dual-run."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path
from typing import Any, Mapping, Sequence


VECTOR_FIELDS = (
    "q", "qdot", "qddot", "internal_force", "external_force",
    "generalized_force", "predictor", "corrector",
)

# These are qualification acceptance bounds, not solver convergence settings.
# They are deliberately far tighter than the state magnitudes in this case.
FIELD_ABS_TOLERANCES = {
    "q": 1.0e-9,
    "qdot": 1.0e-7,
    "qddot": 1.0e-4,
    "internal_force": 1.0e-3,
    "external_force": 1.0e-9,
    "generalized_force": 1.0e-9,
    "predictor": 1.0e-9,
    "corrector": 1.0e-9,
    "residual": 1.0e-5,
}


class QualificationError(ValueError):
    """The golden record or C++ response violates the qualification contract."""


def _finite_vector(value: object, field: str, size: int = 102) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != size:
        raise QualificationError(f"{field} must have exactly {size} entries")
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise QualificationError(f"{field} is not numeric") from exc
    if any(not math.isfinite(item) for item in result):
        raise QualificationError(f"{field} contains NaN/Inf")
    return result


def vector_payload_hash(record: Mapping[str, Any]) -> tuple[str, int]:
    values = tuple(item for name in VECTOR_FIELDS for item in _finite_vector(record.get(name), name))
    payload = struct.pack("<" + "d" * len(values), *values)
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _integer(record: Mapping[str, Any], name: str, expected: int) -> int:
    value = record.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not float(value).is_integer():
        raise QualificationError(f"{name} is not an integer")
    actual = int(value)
    if actual != expected:
        raise QualificationError(f"{name} mismatch: {actual} != {expected}")
    return actual


def validate_golden(path: Path, *, run_id: str, case_id: str, count: int = 40) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != count:
        raise QualificationError(f"golden record count mismatch: {len(rows)} != {count}")
    for index, row in enumerate(rows, start=1):
        if row.get("run_id") != run_id or row.get("case_id") != case_id:
            raise QualificationError(f"run/case identity mismatch at index {index}")
        _integer(row, "global_step", 559 + index)
        _integer(row, "case_local_bridge_step", index)
        _integer(row, "integer_tick", 2_207_500_000 + index * 1_250_000)
        _integer(row, "sequence", index)
        _integer(row, "request_id", 206_000 + index)
        _integer(row, "transaction_id", 206_000_000 + index)
        _integer(row, "return_code", 0)
        _integer(row, "iterations", int(row.get("iterations", -1)))
        if int(row["iterations"]) <= 0:
            raise QualificationError(f"iterations must be positive at index {index}")
        if not math.isclose(float(row.get("time_s", math.nan)), 2.2075 + index * 0.00125, rel_tol=0.0, abs_tol=1e-12):
            raise QualificationError(f"time mismatch at index {index}")
        if row.get("finite_value_audit") is not True:
            raise QualificationError(f"finite audit failed at index {index}")
        if int(row.get("gauss_order", -1)) != 3 or int(row.get("max_newton", -1)) != 40:
            raise QualificationError(f"production numerical contract mismatch at index {index}")
        if int(row.get("mass_gauss_order", -1)) != 5:
            raise QualificationError(f"mass quadrature contract mismatch at index {index}")
        residual = float(row.get("residual", math.nan))
        if not math.isfinite(residual):
            raise QualificationError(f"residual is non-finite at index {index}")
        expected_hash, expected_size = vector_payload_hash(row)
        if row.get("payload_hash") != expected_hash or int(row.get("payload_size_bytes", -1)) != expected_size:
            raise QualificationError(f"payload hash/size mismatch at index {index}")
        checkpoint = row.get("checkpoint")
        if not isinstance(checkpoint, Mapping) or int(checkpoint.get("step", -1)) != 559 + index:
            raise QualificationError(f"checkpoint identity mismatch at index {index}")
    return rows


def compare_step(golden: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    identities = ("run_id", "case_id", "global_step", "case_local_bridge_step", "integer_tick",
                  "sequence", "request_id", "transaction_id", "iterations", "return_code")
    for field in identities:
        if golden.get(field) != candidate.get(field):
            raise QualificationError(f"C++ identity mismatch: {field}")
    if not math.isclose(float(golden["time_s"]), float(candidate["time_s"]), rel_tol=0.0, abs_tol=1e-12):
        raise QualificationError("C++ identity mismatch: time_s")
    if candidate.get("finite_value_audit") is not True:
        raise QualificationError("C++ finite audit failed")

    errors: dict[str, float] = {}
    for field in VECTOR_FIELDS + ("residual",):
        expected = golden[field]
        actual = candidate[field]
        if field == "residual":
            values = (abs(float(expected) - float(actual)),)
        else:
            reference = _finite_vector(expected, field)
            observed = _finite_vector(actual, field)
            values = tuple(abs(left - right) for left, right in zip(reference, observed))
        maximum = max(values, default=0.0)
        errors[field] = maximum
        if maximum > FIELD_ABS_TOLERANCES[field]:
            raise QualificationError(f"C++ numerical mismatch: {field}={maximum:.17g}")
    return {"status": "pass", "max_abs_error": errors}
