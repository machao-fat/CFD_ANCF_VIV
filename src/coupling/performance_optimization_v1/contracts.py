from __future__ import annotations

import hashlib
import json
import math
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "performance_optimization_v1.0"
FORMAL_PROTOCOL_VERSION = "0.2.1"
STATISTICAL_STATUS = {
    "frequency": "not_evaluable_performance_optimization_only",
    "FORMAL_STROUHAL_STATUS": "not_completed",
    "STABLE_VIV_RESPONSE_CLAIM": "not_completed",
    "LOCK_IN_CLAIM": "not_completed",
}


class ProtocolViolation(RuntimeError):
    """Any identity, ordering, numerical, or lifecycle contract violation."""


def finite_audit(value: Any, path: str = "value") -> dict[str, Any]:
    """Return a JSON-safe finite-value audit and fail on NaN/Inf."""
    if isinstance(value, Mapping):
        children = {str(k): finite_audit(v, f"{path}.{k}") for k, v in value.items()}
        return {"path": path, "finite": True, "children": children}
    if isinstance(value, (list, tuple)):
        children = {str(i): finite_audit(v, f"{path}[{i}]") for i, v in enumerate(value)}
        return {"path": path, "finite": True, "children": children}
    if isinstance(value, float) and not math.isfinite(value):
        raise ProtocolViolation(f"{path} contains NaN/Inf")
    return {"path": path, "finite": True, "value_type": type(value).__name__}


def payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class OptimizationConfig:
    """Runtime constants copied as constraints, never changed by benchmarks."""

    global_dt_s: float = 0.0025
    segment_duration_s: float = 0.05
    slice_count: int = 3
    stabilization_parameters: Mapping[str, float] = field(default_factory=lambda: {"rho_inf": 0.5})
    numerical_thresholds: Mapping[str, float] = field(default_factory=lambda: {"identity": 0.0, "finite": 0.0})
    statistical_gate: str = "formal_0.2.1_unchanged"
    formal_protocol_version: str = FORMAL_PROTOCOL_VERSION

    @property
    def steps_per_segment(self) -> int:
        ratio = self.segment_duration_s / self.global_dt_s
        if abs(ratio - round(ratio)) > 1e-12:
            raise ProtocolViolation("segment duration is not an integer number of global steps")
        return int(round(ratio))

    def validate(self) -> None:
        if self.slice_count != 3:
            raise ProtocolViolation("performance optimization is scoped to exactly three slices")
        if self.global_dt_s != 0.0025 or self.segment_duration_s != 0.05:
            raise ProtocolViolation("global dt/segment window are immutable in this stage")
        if self.formal_protocol_version != FORMAL_PROTOCOL_VERSION:
            raise ProtocolViolation("formal protocol version cannot be changed")
        finite_audit(self.stabilization_parameters, "stabilization_parameters")
        finite_audit(self.numerical_thresholds, "numerical_thresholds")


@dataclass
class ProcessAudit:
    component: str
    pid: int
    creation_time_ns: int
    parent_pid: int
    command_line: list[str]
    return_code: int | None = None
    started_at_ns: int = field(default_factory=time.time_ns)
    ended_at_ns: int | None = None
    cleanup_status: str = "open"
    process_kind: str = "offline_mock"

    def close(self, return_code: int = 0) -> None:
        self.return_code = int(return_code)
        self.ended_at_ns = time.time_ns()
        self.cleanup_status = "closed"

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class WorkerEnvelope:
    run_id: str
    case_id: str
    global_step: int
    case_local_bridge_step: int
    time_s: float
    integer_tick: int
    request_id: str
    transaction_id: str
    payload_hash: str
    size: int
    mtime_ns: int
    return_code: int
    finite_audit: Mapping[str, Any]
    worker_pid: int
    # Logical output hash.  For the offline worker this is the immutable
    # payload hash; the surrounding file still carries size and mtime_ns.
    output_hash: str = ""

    @classmethod
    def build(cls, *, run_id: str, case_id: str, global_step: int,
              case_local_bridge_step: int, time_s: float, integer_tick: int,
              request_id: str | None = None, transaction_id: str | None = None,
              payload: Any = None, size: int = 0, mtime_ns: int | None = None,
              return_code: int = 0, worker_pid: int) -> "WorkerEnvelope":
        if not math.isfinite(float(time_s)):
            raise ProtocolViolation("time_s contains NaN/Inf")
        if int(global_step) < 0 or int(case_local_bridge_step) < 0 or int(integer_tick) < 0:
            raise ProtocolViolation("negative worker step or tick")
        finite = finite_audit(payload, "payload")
        digest = payload_hash(payload)
        return cls(run_id, case_id, int(global_step), int(case_local_bridge_step),
                   float(time_s), int(integer_tick), request_id or uuid.uuid4().hex,
                   transaction_id or uuid.uuid4().hex, digest, int(size),
                   int(time.time_ns() if mtime_ns is None else mtime_ns), int(return_code),
                   finite, int(worker_pid), digest)

    def validate_against(self, *, run_id: str, case_id: str, global_step: int,
                         case_local_bridge_step: int, time_s: float, integer_tick: int) -> None:
        if not math.isfinite(self.time_s) or self.global_step < 0 or self.case_local_bridge_step < 0 or self.integer_tick < 0:
            raise ProtocolViolation("worker metadata is non-finite or negative")
        if not self.request_id or not self.transaction_id or self.worker_pid <= 0:
            raise ProtocolViolation("worker identity is incomplete")
        if self.size < 0 or self.mtime_ns <= 0:
            raise ProtocolViolation("worker output metadata is invalid")
        expected = (run_id, case_id, int(global_step), int(case_local_bridge_step), float(time_s), int(integer_tick))
        actual = (self.run_id, self.case_id, self.global_step, self.case_local_bridge_step, self.time_s, self.integer_tick)
        if actual != expected:
            raise ProtocolViolation(f"worker identity/tick mismatch: expected={expected} actual={actual}")
        if self.return_code != 0:
            raise ProtocolViolation(f"worker returned non-zero code {self.return_code}")
        if not self.finite_audit.get("finite", False):
            raise ProtocolViolation("worker finite audit failed")
        if not self.output_hash or self.output_hash != self.payload_hash:
            raise ProtocolViolation("worker output hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class IPCMessage:
    schema_version: str
    run_id: str
    case_id: str
    slice_id: int
    global_step: int
    case_local_bridge_step: int
    time_s: float
    integer_tick: int
    request_id: str
    transaction_id: str
    payload_hash: str
    sequence: int
    producer: str
    consumer: str
    ack: bool
    payload: Any = None

    @classmethod
    def create(cls, *, run_id: str, case_id: str, slice_id: int, global_step: int,
               case_local_bridge_step: int, time_s: float, integer_tick: int,
               request_id: str, transaction_id: str, sequence: int,
               producer: str, consumer: str, ack: bool, payload: Any = None) -> "IPCMessage":
        if not math.isfinite(float(time_s)):
            raise ProtocolViolation("ipc time_s contains NaN/Inf")
        if int(global_step) < 0 or int(case_local_bridge_step) < 0 or int(integer_tick) < 0:
            raise ProtocolViolation("negative IPC step or tick")
        finite_audit(payload, "ipc.payload")
        return cls(SCHEMA_VERSION, run_id, case_id, int(slice_id), int(global_step),
                   int(case_local_bridge_step), float(time_s), int(integer_tick),
                   request_id, transaction_id, payload_hash(payload), int(sequence),
                   producer, consumer, bool(ack), payload)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)
