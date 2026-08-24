"""Strict, round-trip-safe bridge time serialization checks."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping


def serialize_consumed(*, step: int, time_s: float) -> str:
    """Mirror C++ max_digits10 JSON output for an IEEE-754 double."""
    if step < 0 or not math.isfinite(time_s):
        raise ValueError("invalid consumed identity")
    return '{"kind":"motion_consumed","step":%d,"time_s":%s}\n' % (
        step,
        format(float(time_s), ".17g"),
    )


def validate_round_trip(payload: str, *, expected_step: int, expected_time_s: float) -> Mapping[str, Any]:
    value = json.loads(payload)
    if int(value.get("step", -1)) != expected_step:
        raise ValueError("bridge step mismatch")
    actual = float(value.get("time_s", math.nan))
    if not math.isfinite(actual):
        raise ValueError("bridge time is non-finite")
    if actual != float(expected_time_s):
        raise ValueError("bridge time is not an exact binary64 round trip")
    return value


def audit_source(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    required = (
        "#include <iomanip>",
        "#include <limits>",
        "std::setprecision(std::numeric_limits<scalar>::max_digits10)",
    )
    missing = [token for token in required if token not in text]
    return {"path": str(path.resolve()), "required_tokens": list(required), "missing": missing, "passed": not missing}

