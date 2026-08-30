from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence


class BootstrapProtocolError(ValueError):
    """A restart bootstrap message or state violates the contract."""


def canonical_tick(time_s: float) -> int:
    value = float(time_s)
    if not math.isfinite(value) or value < 0.0:
        raise BootstrapProtocolError("time_s must be finite and non-negative")
    return int(math.floor(value * 1.0e9 + 0.5))


def _vector(values: Sequence[float], name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result or any(not math.isfinite(value) for value in result):
        raise BootstrapProtocolError(f"{name} is empty or non-finite")
    return result


def q_hash(values: Sequence[float]) -> str:
    vector = _vector(values, "q")
    return hashlib.sha256(struct.pack("<" + "d" * len(vector), *vector)).hexdigest()


@dataclass(frozen=True)
class RestartBootstrapState:
    source_global_step: int
    field_time_s: float
    state_time_s: float
    lag_steps: int
    dt_s: float
    q: tuple[float, ...]
    qdot: tuple[float, ...]
    qddot: tuple[float, ...]
    q_sha256: str
    source_final_q_sha256: str | None = None
    direct_final_q_rejected: bool = True

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "RestartBootstrapState":
        item = cls(
            source_global_step=int(raw["source_global_step"]),
            field_time_s=float(raw["field_time_s"]),
            state_time_s=float(raw["state_time_s"]),
            lag_steps=int(raw["lag_steps"]),
            dt_s=float(raw["dt_s"]),
            q=_vector(raw["q"], "q"),
            qdot=_vector(raw["qdot"], "qdot"),
            qddot=_vector(raw["qddot"], "qddot"),
            q_sha256=str(raw["q_sha256"]),
            source_final_q_sha256=(str(raw["source_final_q_sha256"]) if raw.get("source_final_q_sha256") else None),
            direct_final_q_rejected=bool(raw.get("direct_final_q_rejected", False)),
        )
        item.validate()
        return item

    def validate(self) -> None:
        if self.source_global_step < 1 or self.lag_steps < 1 or self.dt_s <= 0.0:
            raise BootstrapProtocolError("invalid source step, lag_steps, or dt_s")
        if not all(math.isfinite(value) for value in (self.field_time_s, self.state_time_s, self.dt_s)):
            raise BootstrapProtocolError("restart times are non-finite")
        expected = self.field_time_s - self.lag_steps * self.dt_s
        if abs(self.state_time_s - expected) > 1.0e-12:
            raise BootstrapProtocolError("state_time does not match field_time and lag_steps")
        if not self.direct_final_q_rejected:
            raise BootstrapProtocolError("direct final_q use must be rejected")
        if len(self.q) != len(self.qdot) or len(self.q) != len(self.qddot):
            raise BootstrapProtocolError("restart state dimensions differ")
        if self.q_sha256 != q_hash(self.q):
            raise BootstrapProtocolError("q_sha256 mismatch")
        if self.source_final_q_sha256 is not None and (len(self.source_final_q_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.source_final_q_sha256.lower())):
            raise BootstrapProtocolError("source_final_q_sha256 is not a SHA-256 digest")


@dataclass(frozen=True)
class BootstrapEnvelope:
    schema_version: int
    run_id: str
    case_id: str
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
    ack: str
    bootstrap_window: int
    q_sha256: str
    payload_hash: str | None = None

    def body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "global_step": self.global_step,
            "case_local_bridge_step": self.case_local_bridge_step,
            "time_s": self.time_s,
            "integer_tick": self.integer_tick,
            "request_id": self.request_id,
            "transaction_id": self.transaction_id,
            "sequence": self.sequence,
            "producer": self.producer,
            "consumer": self.consumer,
            "kind": self.kind,
            "ack": self.ack,
            "bootstrap_window": self.bootstrap_window,
            "q_sha256": self.q_sha256,
        }

    def seal(self) -> "BootstrapEnvelope":
        raw = json.dumps(self.body(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return replace(self, payload_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest())

    def validate(self, *, state: RestartBootstrapState, run_id: str, case_id: str) -> None:
        state.validate()
        if self.payload_hash is None:
            raise BootstrapProtocolError("missing payload_hash")
        if self.payload_hash != self.seal().payload_hash:
            raise BootstrapProtocolError("payload_hash mismatch")
        if self.schema_version != 1 or self.run_id != run_id or self.case_id != case_id:
            raise BootstrapProtocolError("run/case/schema identity mismatch")
        if self.global_step != state.source_global_step or self.case_local_bridge_step != 0:
            raise BootstrapProtocolError("bootstrap step mismatch")
        if abs(self.time_s - state.field_time_s) > 1.0e-12 or self.integer_tick != canonical_tick(self.time_s):
            raise BootstrapProtocolError("bootstrap time/tick mismatch")
        if self.bootstrap_window not in (0, 1) or self.sequence != self.bootstrap_window + 1:
            raise BootstrapProtocolError("bootstrap window sequence mismatch")
        if self.q_sha256 != state.q_sha256:
            raise BootstrapProtocolError("bootstrap q hash mismatch")
        if self.request_id != f"bootstrap-{self.bootstrap_window}" or self.transaction_id != f"bootstrap-tx-{self.bootstrap_window}":
            raise BootstrapProtocolError("bootstrap request/transaction mismatch")
        for name in ("request_id", "transaction_id", "producer", "consumer", "kind", "ack"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or any(ord(ch) < 0x20 for ch in value):
                raise BootstrapProtocolError(f"invalid {name}")


def _make(*, run_id: str, case_id: str, window: int, kind: str, ack: str, producer: str, consumer: str, state: RestartBootstrapState) -> BootstrapEnvelope:
    message = BootstrapEnvelope(
        schema_version=1,
        run_id=run_id,
        case_id=case_id,
        global_step=state.source_global_step,
        case_local_bridge_step=0,
        time_s=state.field_time_s,
        integer_tick=canonical_tick(state.field_time_s),
        request_id=f"bootstrap-{window}",
        transaction_id=f"bootstrap-tx-{window}",
        sequence=window + 1,
        producer=producer,
        consumer=consumer,
        kind=kind,
        ack=ack,
        bootstrap_window=window,
        q_sha256=state.q_sha256,
    )
    return message.seal()


def make_bootstrap_seed(*, run_id: str, case_id: str, window: int, state: RestartBootstrapState) -> BootstrapEnvelope:
    return _make(run_id=run_id, case_id=case_id, window=window, kind="bootstrap_seed", ack="required", producer="structure", consumer="fluid", state=state)


def make_bootstrap_ack(seed: BootstrapEnvelope, *, state: RestartBootstrapState) -> BootstrapEnvelope:
    return _make(run_id=seed.run_id, case_id=seed.case_id, window=seed.bootstrap_window, kind="bootstrap_ack", ack="consumed", producer="fluid", consumer="structure", state=state)


def reject_direct_final_q(final_q: Sequence[float], state: RestartBootstrapState) -> None:
    if state.source_final_q_sha256 and q_hash(final_q) == state.source_final_q_sha256:
        raise BootstrapProtocolError("direct final_q restart is forbidden; use lagged bootstrap state")


@dataclass
class BootstrapSession:
    state: RestartBootstrapState
    run_id: str
    case_id: str
    next_window: int = 0
    bootstrap_acked: bool = False
    accepted_windows: list[int] | None = None

    def __post_init__(self) -> None:
        self.state.validate()
        self.accepted_windows = [] if self.accepted_windows is None else self.accepted_windows

    def accept_ack(self, message: BootstrapEnvelope) -> None:
        message.validate(state=self.state, run_id=self.run_id, case_id=self.case_id)
        if message.kind != "bootstrap_ack" or message.ack != "consumed":
            raise BootstrapProtocolError("expected consumed bootstrap_ack")
        if message.producer != "fluid" or message.consumer != "structure":
            raise BootstrapProtocolError("bootstrap ack producer/consumer mismatch")
        if message.bootstrap_window != self.next_window:
            raise BootstrapProtocolError("stale, duplicate, or out-of-order bootstrap ack")
        assert self.accepted_windows is not None
        self.accepted_windows.append(message.bootstrap_window)
        self.next_window += 1
        if self.next_window == 2:
            self.bootstrap_acked = True

    def require_ready_for_normal_continuation(self) -> None:
        if not self.bootstrap_acked:
            raise BootstrapProtocolError("normal continuation requires two bootstrap acknowledgements")
