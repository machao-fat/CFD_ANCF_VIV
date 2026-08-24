from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

SCHEMA_VERSION = "performance_instrumentation_matlab_worker_v1.0"
FORMAL_PROTOCOL_VERSION = "0.2.1"


class ProtocolError(RuntimeError):
    """A fail-closed worker protocol or identity violation."""


def canonical_json(value: Any) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"payload is not canonical JSON: {exc}") from exc


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _finite(value: Any, path: str = "value") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _finite(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _finite(item, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ProtocolError(f"{path} contains NaN/Inf")


@dataclass(frozen=True)
class WorkerRequest:
    schema_version: str
    formal_protocol_version: str
    operation: str
    run_id: str
    case_id: str
    global_step: int
    case_local_bridge_step: int
    time_s: float
    integer_tick: int
    request_id: str
    transaction_id: str
    payload_hash: str
    payload: Any

    @classmethod
    def create(cls, *, operation: str, run_id: str, case_id: str, global_step: int,
               case_local_bridge_step: int, time_s: float, integer_tick: int,
               request_id: str, transaction_id: str, payload: Any) -> "WorkerRequest":
        if not request_id or not transaction_id or not run_id or not case_id:
            raise ProtocolError("request identity is incomplete")
        if global_step < 0 or case_local_bridge_step < 0 or integer_tick < 0 or not math.isfinite(float(time_s)):
            raise ProtocolError("request step/time metadata is invalid")
        _finite(payload, "request.payload")
        return cls(SCHEMA_VERSION, FORMAL_PROTOCOL_VERSION, operation, run_id, case_id,
                   int(global_step), int(case_local_bridge_step), float(time_s), int(integer_tick),
                   request_id, transaction_id, canonical_sha256(payload), payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkerResponse:
    schema_version: str
    formal_protocol_version: str
    operation: str
    run_id: str
    case_id: str
    global_step: int
    case_local_bridge_step: int
    time_s: float
    integer_tick: int
    request_id: str
    transaction_id: str
    payload_hash: str
    output_sha256: str
    output_size: int
    output_mtime_ns: int
    return_code: int
    finite_value_audit: Mapping[str, Any]
    worker_pid: int
    worker_creation_time: int
    parent_pid: int
    command_line: list[str]
    payload: Any

    @classmethod
    def create(cls, request: WorkerRequest, *, payload: Any, output_sha256: str,
               output_size: int, output_mtime_ns: int, return_code: int,
               worker_pid: int, worker_creation_time: int, parent_pid: int,
               command_line: list[str]) -> "WorkerResponse":
        _finite(payload, "response.payload")
        return cls(SCHEMA_VERSION, FORMAL_PROTOCOL_VERSION, request.operation,
                   request.run_id, request.case_id, request.global_step,
                   request.case_local_bridge_step, request.time_s, request.integer_tick,
                   request.request_id, request.transaction_id, request.payload_hash,
                   output_sha256, int(output_size), int(output_mtime_ns), int(return_code),
                   {"finite": True}, int(worker_pid), int(worker_creation_time), int(parent_pid), list(command_line), payload)

    def validate(self, request: WorkerRequest, *, raw_payload_sha256: str | None = None) -> None:
        expected = (request.run_id, request.case_id, request.global_step,
                    request.case_local_bridge_step, request.time_s, request.integer_tick,
                    request.request_id, request.transaction_id, request.payload_hash)
        actual = (self.run_id, self.case_id, self.global_step, self.case_local_bridge_step,
                  self.time_s, self.integer_tick, self.request_id, self.transaction_id,
                  self.payload_hash)
        if actual != expected:
            raise ProtocolError("response identity or time metadata mismatch")
        if self.schema_version != SCHEMA_VERSION or self.formal_protocol_version != FORMAL_PROTOCOL_VERSION:
            raise ProtocolError("unsupported protocol version")
        if self.return_code != 0:
            raise ProtocolError(f"worker returned non-zero code {self.return_code}")
        if not self.output_sha256 or self.output_size <= 0 or self.output_mtime_ns <= 0 or self.worker_creation_time <= 0:
            raise ProtocolError("response output metadata is missing")
        if self.finite_value_audit.get("finite") is not True:
            raise ProtocolError("finite-value audit failed")
        expected_output_hash = raw_payload_sha256 or canonical_sha256(self.payload)
        if expected_output_hash != self.output_sha256:
            raise ProtocolError("response output hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
