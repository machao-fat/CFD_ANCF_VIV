from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping


class ProtocolError(ValueError):
    """An exchange envelope is malformed or not valid for the current transaction."""


def canonical_tick(time_s: float) -> int:
    if isinstance(time_s, bool) or not isinstance(time_s, (int, float)):
        raise ProtocolError("time_s must be numeric")
    value = float(time_s)
    if not math.isfinite(value) or value < 0:
        raise ProtocolError("time_s must be finite and non-negative")
    return int(math.floor(value * 1.0e9 + 0.5))


def _finite(value: Any, path: str = "payload") -> Any:
    if isinstance(value, Mapping):
        return {str(k): _finite(v, f"{path}.{k}") for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v, f"{path}[]") for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ProtocolError(f"{path} contains NaN/Inf")
    return value


@dataclass(frozen=True)
class Envelope:
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
    ack: str
    payload_hash: str | None = None

    def body(self) -> dict[str, Any]:
        body = asdict(self)
        body.pop("payload_hash", None)
        return _finite(body, "message")

    def seal(self) -> "Envelope":
        raw = json.dumps(self.body(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return Envelope(**self.body(), payload_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest())

    def canonical_json(self) -> str:
        if not self.payload_hash:
            raise ProtocolError("unsealed envelope")
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def validate(self, expected: Mapping[str, Any] | None = None) -> None:
        if self.schema_version != 1:
            raise ProtocolError("unsupported schema_version")
        for name in ("run_id", "case_id", "slice_id", "request_id", "transaction_id", "producer", "consumer", "kind", "ack"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or any(ord(ch) < 0x20 for ch in value):
                raise ProtocolError(f"invalid {name}")
        if self.global_step < 0 or self.case_local_bridge_step < 0 or self.sequence < 1:
            raise ProtocolError("negative step or sequence")
        if self.integer_tick != canonical_tick(self.time_s):
            raise ProtocolError("time_s/integer_tick mismatch")
        if not self.payload_hash:
            raise ProtocolError("missing payload_hash")
        if self.payload_hash != self.seal().payload_hash:
            raise ProtocolError("payload_hash mismatch")
        if expected:
            for name, value in expected.items():
                if getattr(self, name, object()) != value:
                    raise ProtocolError(f"identity mismatch: {name}")


def make_envelope(**kwargs: Any) -> Envelope:
    return Envelope(**kwargs).seal()
