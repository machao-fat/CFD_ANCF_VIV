from __future__ import annotations

import hashlib
import math
from numbers import Real
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
REQUEST_PRODUCER = "python_scheduler"
REQUEST_CONSUMER = "cpp_ancf_worker"
MAX_NDOF = 2048
MAX_UINT64 = (1 << 64) - 1
# schema, sequence, global_step, bridge_step, tick, time, dt, n, request token,
# transaction token, run_id, case_id, producer, consumer
REQUEST = struct.Struct("<IIIiiQddiQQ64s64s32s32s32s")
# same identity fields are echoed by the worker, plus response status/hash.
RESPONSE = struct.Struct("<IIIiiQdii32sQQI64s64s32s32s")


class FrameError(ValueError):
    """Persistent IPC frame is malformed or violates identity rules."""


def canonical_integer_tick(time_s: float) -> int:
    """Return the non-negative C++ ``llround(time_s * 1e9)`` result.

    Python's built-in ``round`` uses ties-to-even, while C++ ``llround``
    rounds halfway cases away from zero.  The wire contract is shared by both
    implementations, so the conversion must be explicit and centralized.
    """
    _finite(time_s, "time_s")
    raw = float(time_s) * 1.0e9
    if raw < 0.0 or raw > float(MAX_UINT64):
        raise FrameError("time_s is outside integer_tick range")
    tick = int(math.floor(raw + 0.5))
    if tick < 0 or tick > MAX_UINT64:
        raise FrameError("integer_tick is outside wire range")
    return tick


def canonical_tick_delta(dt_s: float) -> int:
    """Return one wire tick and reject sub-nanosecond step ambiguity."""
    _finite(dt_s, "dt_s")
    if dt_s <= 0.0:
        raise FrameError("dt_s must be positive")
    raw = float(dt_s) * 1.0e9
    delta = int(math.floor(raw + 0.5))
    if abs(raw - float(delta)) > 1.0e-9 or delta <= 0 or delta > MAX_UINT64:
        raise FrameError("dt_s does not map to an unambiguous integer tick")
    return delta


def _fixed(value: str, size: int, name: str) -> bytes:
    if not isinstance(value, str) or not value or any(ord(char) < 0x20 for char in value):
        raise FrameError(f"{name} is missing or contains a control character")
    raw = value.encode("utf-8")
    if b"\0" in raw or len(raw) >= size:
        raise FrameError(f"{name} is missing or too long")
    return raw + b"\0" * (size - len(raw))


def _finite(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise FrameError(f"{name} is not numeric")
    try:
        finite = math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise FrameError(f"{name} is not numeric") from exc
    if not finite:
        raise FrameError(f"{name} is NaN/Inf")


def _bounded_int(value: int, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise FrameError(f"{name} is outside its wire range")
    return value


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
        if self.producer != REQUEST_PRODUCER or self.consumer != REQUEST_CONSUMER:
            raise FrameError("request producer/consumer endpoint mismatch")
        n = len(self.q)
        if n == 0 or n > MAX_NDOF or len(self.qdot) != n or len(self.force) != n:
            raise FrameError("state vector lengths do not match")
        _bounded_int(self.sequence, "sequence", 1, 0xFFFFFFFF)
        _bounded_int(self.global_step, "global_step", 1, 0x7FFFFFFF)
        _bounded_int(self.case_local_bridge_step, "case_local_bridge_step", 1, 0x7FFFFFFF)
        _bounded_int(self.integer_tick, "integer_tick", 0, 0xFFFFFFFFFFFFFFFF)
        _bounded_int(self.request_id, "request_id", 1, 0xFFFFFFFFFFFFFFFF)
        _bounded_int(self.transaction_id, "transaction_id", 1, 0xFFFFFFFFFFFFFFFF)
        _finite(self.time_s, "time_s"); _finite(self.dt_s, "dt_s")
        if self.dt_s <= 0.0:
            raise FrameError("dt_s must be positive")
        canonical_tick_delta(self.dt_s)
        expected_tick = canonical_integer_tick(self.time_s)
        if (self.time_s < self.dt_s or self.time_s > 1.0e9 or expected_tick < 0 or
                expected_tick > 0xFFFFFFFFFFFFFFFF or self.integer_tick != expected_tick):
            raise FrameError("time_s and integer_tick are inconsistent")
        for value, name, limit in ((self.run_id, "run_id", ID_RUN), (self.case_id, "case_id", ID_CASE),
                                    (self.producer, "producer", ID_ENDPOINT), (self.consumer, "consumer", ID_ENDPOINT)):
            _fixed(value, limit, name)
        values = [*self.q, *self.qdot, *self.force]
        if any(isinstance(item, bool) or not isinstance(item, Real) for item in values):
            raise FrameError("request state contains a non-numeric value")
        try:
            numeric_values = [float(item) for item in values]
        except (TypeError, ValueError, OverflowError) as exc:
            raise FrameError("request state contains a non-numeric value") from exc
        if any(not math.isfinite(item) for item in numeric_values):
            raise FrameError("request state contains NaN/Inf")
        state_bytes = struct.pack("<" + "d" * len(numeric_values), *numeric_values)
        request_hash = hashlib.sha256(state_bytes).digest()
        return REQUEST.pack(SCHEMA_VERSION, PROTOCOL_VERSION, self.sequence, self.global_step, self.case_local_bridge_step,
                            self.integer_tick, self.time_s, self.dt_s, n, self.request_id, self.transaction_id,
                            _fixed(self.run_id, ID_RUN, "run_id"), _fixed(self.case_id, ID_CASE, "case_id"),
                            _fixed(self.producer, ID_ENDPOINT, "producer"), _fixed(self.consumer, ID_ENDPOINT, "consumer"), request_hash) + state_bytes


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
    # Bound the decoded vector dimension before computing the payload size or
    # unpacking values from an untrusted response frame.
    if (schema != SCHEMA_VERSION or protocol != PROTOCOL_VERSION or
            n <= 0 or n > MAX_NDOF):
        raise FrameError("response schema or vector length invalid")
    expected = RESPONSE.size + 8 * n * 3
    if len(raw) != expected:
        raise FrameError("response vector payload length mismatch")
    values = struct.unpack_from("<" + "d" * (3 * n), raw, RESPONSE.size)
    if not math.isfinite(time_s) or any(not math.isfinite(float(item)) for item in values):
        raise FrameError("response state contains NaN/Inf")
    def clean(value: bytes, name: str) -> str:
        if b"\0" not in value:
            raise FrameError(f"response {name} is not NUL-terminated")
        raw_value, trailing = value.split(b"\0", 1)
        if not raw_value or any(trailing):
            raise FrameError(f"response {name} has invalid fixed-width encoding")
        try:
            decoded = raw_value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FrameError(f"response {name} is not UTF-8") from exc
        if any(ord(char) < 0x20 for char in decoded):
            raise FrameError(f"response {name} contains a control character")
        return decoded
    return StepResponse(protocol, sequence, step, bridge, tick, time_s, code, digest, tx, request_id, ack,
                        clean(run, "run_id"), clean(case, "case_id"), clean(producer, "producer"), clean(consumer, "consumer"),
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
