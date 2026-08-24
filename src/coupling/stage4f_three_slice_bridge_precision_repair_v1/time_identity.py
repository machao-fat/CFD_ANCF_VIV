"""Bridge 时间身份合同：整数 tick + 规范十进制字符串。"""
from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

TICK_SECONDS = Decimal("0.000000001")
CONTRACT = "stage4f-c-bridge-time-identity-v1"

class TimeIdentityError(ValueError):
    pass

def _finite_decimal(value: Any) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TimeIdentityError("time is not a valid decimal") from exc
    if not d.is_finite() or d < 0:
        raise TimeIdentityError("time must be finite and non-negative")
    return d

def time_to_tick(time_s: Any) -> int:
    d = _finite_decimal(time_s)
    q = d / TICK_SECONDS
    if q != q.to_integral_value():
        raise TimeIdentityError("time is not representable at 1 ns tick")
    return int(q)

def tick_to_time(tick: int) -> str:
    if isinstance(tick, bool) or int(tick) < 0 or int(tick) != tick:
        raise TimeIdentityError("tick must be a non-negative integer")
    d = Decimal(int(tick)) * TICK_SECONDS
    return format(d, "f")

def identity(*, global_step: int, time_s: Any, case_id: str, slice_id: int, run_id: str) -> dict[str, Any]:
    if isinstance(global_step, bool) or int(global_step) < 0 or int(global_step) != global_step:
        raise TimeIdentityError("global_step mismatch")
    if not case_id or not run_id or isinstance(slice_id, bool) or int(slice_id) < 0:
        raise TimeIdentityError("case/slice/run identity is invalid")
    tick = time_to_tick(time_s)
    return {"contract": CONTRACT, "global_step": int(global_step), "time_tick": tick,
            "time_s": tick_to_time(tick), "case_id": str(case_id), "slice_id": int(slice_id), "run_id": str(run_id)}

def dumps(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"

def parse_and_validate(payload: str, *, expected_step: int, expected_time_s: Any, case_id: str, slice_id: int, run_id: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TimeIdentityError("marker JSON invalid") from exc
    if not isinstance(value, Mapping):
        raise TimeIdentityError("marker is not an object")
    expected = identity(global_step=expected_step, time_s=expected_time_s, case_id=case_id, slice_id=slice_id, run_id=run_id)
    for key in expected:
        if value.get(key) != expected[key]:
            raise TimeIdentityError(f"{key} mismatch")
    if time_to_tick(value["time_s"]) != int(value["time_tick"]):
        raise TimeIdentityError("time tick mismatch")
    return dict(value)

def legacy_marker_status(payload: str, **kwargs: Any) -> str:
    try:
        parse_and_validate(payload, **kwargs)
    except TimeIdentityError as exc:
        return str(exc)
    return "accepted"
