from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass


MAGIC = b"CFDANCF1"
SCHEMA_VERSION = 1
PROTOCOL_VERSION = 1
ACK_OK = 1
HEADER = struct.Struct("<8sII")
MESSAGE_STEP_REQUEST = 1
MESSAGE_STEP_RESPONSE = 2
MESSAGE_SHUTDOWN = 3
MESSAGE_INITIALIZE = 4
ID_RUN = 64
ID_CASE = 64
ID_ENDPOINT = 32
# schema, sequence, global_step, bridge_step, tick, time, dt, n, request token,
# transaction token, run_id, case_id, producer, consumer
REQUEST = struct.Struct("<IIIiiQddiQQ64s64s32s32s32s")
# same identity fields are echoed by the worker, plus response status/hash.
RESPONSE = struct.Struct("<IIIiiQdii32sQQI64s64s32s32s")


class FrameError(ValueError):
    """Persistent IPC frame is malformed or violates identity rules."""


def _finite(value: float, name: str) -> None:
    if not math.isfinite(float(value)):
        raise FrameError(f"{name} is NaN/Inf")


@dataclass(frozen=True)
class StepRequest:
    sequence: int
    global_step: int
    case_local_bridge_step: int
    integer_tick: int
    time_s: float
    dt_s: float
    request_id: int
    transaction_id: int
    run_id: str
    case_id: str
    q: tuple[float, ...]
    qdot: tuple[float, ...]
    force: tuple[float, ...]
    producer: str = "python_scheduler"
    consumer: str = "cpp_ancf_worker"

    def payload(self) -> bytes:
        n = len(self.q)
        if n == 0 or len(self.qdot) != n or len(self.force) != n:
            raise FrameError("state vector lengths do not match")
        if (self.sequence <= 0 or self.global_step <= 0 or
                self.case_local_bridge_step <= 0 or self.integer_tick < 0 or
                self.request_id == 0 or self.transaction_id == 0):
            raise FrameError("request identity is invalid")
        _finite(self.time_s, "time_s"); _finite(self.dt_s, "dt_s")
        if self.dt_s <= 0.0:
            raise FrameError("dt_s must be positive")
        expected_tick = int(round(self.time_s * 1.0e9))
        if self.time_s < self.dt_s or self.integer_tick != expected_tick:
            raise FrameError("time_s and integer_tick are inconsistent")
        for value, name, limit in ((self.run_id, "run_id", ID_RUN), (self.case_id, "case_id", ID_CASE),
                                    (self.producer, "producer", ID_ENDPOINT), (self.consumer, "consumer", ID_ENDPOINT)):
            if not value or len(value.encode("utf-8")) >= limit:
                raise FrameError(f"{name} is missing or too long")
        values = [*self.q, *self.qdot, *self.force]
        if any(not math.isfinite(float(item)) for item in values):
            raise FrameError("request state contains NaN/Inf")
        fixed = lambda value, size: value.encode("utf-8") + b"\0" * (size - len(value.encode("utf-8")))
        state_bytes = struct.pack("<" + "d" * len(values), *values)
        request_hash = hashlib.sha256(state_bytes).digest()
        return REQUEST.pack(SCHEMA_VERSION, PROTOCOL_VERSION, self.sequence, self.global_step, self.case_local_bridge_step,
                            self.integer_tick, self.time_s, self.dt_s, n, self.request_id, self.transaction_id,
                            fixed(self.run_id, ID_RUN), fixed(self.case_id, ID_CASE),
                            fixed(self.producer, ID_ENDPOINT), fixed(self.consumer, ID_ENDPOINT), request_hash) + state_bytes


def encode_request(request: StepRequest) -> bytes:
    payload = request.payload()
    return HEADER.pack(MAGIC, len(payload), MESSAGE_STEP_REQUEST) + payload


def encode_control(message_type: int) -> bytes:
    if message_type not in {MESSAGE_INITIALIZE, MESSAGE_SHUTDOWN}:
        raise FrameError("unsupported control message")
    return HEADER.pack(MAGIC, 0, message_type)


@dataclass(frozen=True)
class StepResponse:
    protocol_version: int
    sequence: int
    global_step: int
    case_local_bridge_step: int
    integer_tick: int
    time_s: float
    return_code: int
    payload_hash: bytes
    transaction_id: int
    request_id: int
    ack: int
    run_id: str
    case_id: str
    producer: str
    consumer: str
    q: tuple[float, ...]
    qdot: tuple[float, ...]
    qddot: tuple[float, ...]


def decode_response(frame: bytes) -> StepResponse:
    if len(frame) < HEADER.size:
        raise FrameError("response frame is truncated")
    magic, length, count = HEADER.unpack_from(frame)
    if magic != MAGIC or count != MESSAGE_STEP_RESPONSE or length != len(frame) - HEADER.size:
        raise FrameError("response frame header mismatch")
    raw = frame[HEADER.size:]
    if len(raw) < RESPONSE.size:
        raise FrameError("response payload is truncated")
    schema, protocol, sequence, step, bridge, tick, time_s, n, code, digest, tx, request_id, ack, run, case, producer, consumer = RESPONSE.unpack_from(raw)
    if schema != SCHEMA_VERSION or protocol != PROTOCOL_VERSION or n <= 0:
        raise FrameError("response schema or vector length invalid")
    expected = RESPONSE.size + 8 * n * 3
    if len(raw) != expected:
        raise FrameError("response vector payload length mismatch")
    values = struct.unpack_from("<" + "d" * (3 * n), raw, RESPONSE.size)
    if any(not math.isfinite(float(item)) for item in values):
        raise FrameError("response state contains NaN/Inf")
    clean = lambda value: value.split(b"\0", 1)[0].decode("utf-8")
    return StepResponse(protocol, sequence, step, bridge, tick, time_s, code, digest, tx, request_id, ack,
                        clean(run), clean(case), clean(producer), clean(consumer),
                        tuple(values[:n]), tuple(values[n:2*n]), tuple(values[2*n:]))


def validate_response(request: StepRequest, response: StepResponse, *, expected_sha256: bytes | None = None) -> None:
    if response.protocol_version != PROTOCOL_VERSION or response.sequence != request.sequence or response.transaction_id != request.transaction_id:
        raise FrameError("response sequence/transaction mismatch")
    if response.request_id != request.request_id or response.ack != ACK_OK:
        raise FrameError("response request acknowledgement mismatch")
    if response.run_id != request.run_id or response.case_id != request.case_id:
        raise FrameError("response run/case identity mismatch")
    if response.producer != request.consumer or response.consumer != request.producer:
        raise FrameError("response producer/consumer identity mismatch")
    if response.global_step != request.global_step or response.case_local_bridge_step != request.case_local_bridge_step:
        raise FrameError("response step identity mismatch")
    if response.integer_tick != request.integer_tick or not math.isclose(response.time_s, request.time_s, rel_tol=0.0, abs_tol=1e-12):
        raise FrameError("response time/tick mismatch")
    if response.return_code != 0:
        raise FrameError(f"C++ worker returned {response.return_code}")
    if len(response.q) != len(request.q) or len(response.qdot) != len(request.qdot) or len(response.qddot) != len(request.q):
        raise FrameError("response state dimensions do not match request")
    actual_sha256 = hashlib.sha256(struct.pack("<" + "d" * (len(response.q) * 3),
                                               *(response.q + response.qdot + response.qddot))).digest()
    if response.payload_hash != actual_sha256:
        raise FrameError("response payload hash mismatch")
    if expected_sha256 is not None and response.payload_hash != expected_sha256:
        raise FrameError("response payload hash mismatch")
