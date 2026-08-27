from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, asdict
from typing import Any, Mapping


class ProtocolError(ValueError):
    """Message violates the common file/preCICE audit contract."""


def canonical_tick(time_s: float) -> int:
    if isinstance(time_s, bool) or not isinstance(time_s, (int, float)) or not math.isfinite(float(time_s)):
        raise ProtocolError("time_s must be finite numeric")
    if time_s < 0:
        raise ProtocolError("time_s must be non-negative")
    return int(math.floor(float(time_s) * 1.0e9 + 0.5))


def _finite_tree(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _finite_tree(v, f"{name}.{k}") for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_tree(v, f"{name}[]") for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ProtocolError(f"{name} contains NaN/Inf")
    return value


@dataclass(frozen=True)
class ExchangeMessage:
    schema_version: int
    run_id: str
    case_id: str
    slice_id: str
    global_step: int
    case_local_bridge_step: int
    time_s: float
    integer_tick: int
    request_id: str
    transaction_id: str
    sequence: int
    producer: str
    consumer: str
    kind: str
    payload: Mapping[str, Any]
    ack: str | None = None
    payload_hash: str | None = None

    def _body(self) -> dict[str, Any]:
        body = asdict(self)
        body.pop("payload_hash", None)
        return _finite_tree(body, "message")

    def seal(self) -> "ExchangeMessage":
        body = self._body()
        digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        return ExchangeMessage(**body, payload_hash=digest)

    def canonical_json(self) -> str:
        if not self.payload_hash:
            raise ProtocolError("message is not sealed")
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def validate(self, *, expected: "ExchangeMessage | None" = None) -> None:
        if self.schema_version != 1:
            raise ProtocolError("unsupported schema_version")
        for name in ("run_id", "case_id", "slice_id", "request_id", "transaction_id", "producer", "consumer", "kind"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or any(ord(c) < 0x20 for c in value):
                raise ProtocolError(f"invalid {name}")
        if self.global_step < 0 or self.case_local_bridge_step < 0 or self.sequence < 1:
            raise ProtocolError("invalid step or sequence")
        if self.integer_tick != canonical_tick(self.time_s):
            raise ProtocolError("time_s/integer_tick mismatch")
        if not self.payload_hash:
            raise ProtocolError("missing payload_hash")
        actual = self.seal().payload_hash
        if self.payload_hash != actual:
            raise ProtocolError("payload_hash mismatch")
        if expected is not None:
            for name in ("run_id", "case_id", "slice_id", "global_step", "case_local_bridge_step", "time_s", "integer_tick", "request_id", "transaction_id"):
                if getattr(self, name) != getattr(expected, name):
                    raise ProtocolError(f"identity mismatch: {name}")


def make_message(**kwargs: Any) -> ExchangeMessage:
    return ExchangeMessage(**kwargs).seal()
