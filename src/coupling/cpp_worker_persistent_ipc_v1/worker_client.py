from __future__ import annotations

import hashlib
import queue
import struct
import threading
from typing import BinaryIO

from .protocol import (HEADER, FrameError, StepRequest, StepResponse, decode_response,
                       canonical_tick_delta, encode_control, encode_request, validate_response,
                       MESSAGE_INITIALIZE, MESSAGE_SHUTDOWN)


class PersistentCppWorkerClient:
    """One persistent framed connection; no retry or reconnect is permitted."""

    MAX_SEEN_IDENTITIES = 100_000

    def __init__(self, reader: BinaryIO, writer: BinaryIO, *, timeout_s: float = 30.0) -> None:
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise FrameError("worker timeout must be positive")
        self.reader = reader
        self.writer = writer
        self.timeout_s = float(timeout_s)
        self.last_sequence = 0
        self.last_global_step: int | None = None
        self.last_bridge_step: int | None = None
        self.last_tick: int | None = None
        self.last_time_s: float | None = None
        self.last_dt_s: float | None = None
        self.closed = False
        self.initialized = False
        self.seen_request_ids: set[int] = set()
        self.seen_transaction_ids: set[int] = set()

    def request(self, value: StepRequest) -> StepResponse:
        if self.closed or not self.initialized or value.sequence != self.last_sequence + 1:
            raise FrameError("worker client is closed or sequence is not monotonic")
        if value.request_id in self.seen_request_ids or value.transaction_id in self.seen_transaction_ids:
            raise FrameError("request_id or transaction_id was already used")
        if self.last_global_step is not None:
            tick_delta = canonical_tick_delta(self.last_dt_s)
            if tick_delta <= 0:
                self.closed = True
                raise FrameError("worker client dt does not advance an integer tick")
            expected_tick = self.last_tick + tick_delta
            if (value.global_step != self.last_global_step + 1 or
                    value.case_local_bridge_step != self.last_bridge_step + 1 or
                    value.integer_tick != expected_tick or
                    abs(value.time_s - (self.last_time_s + self.last_dt_s)) > 1.0e-12 or
                    abs(value.dt_s - self.last_dt_s) > 1.0e-15):
                self.closed = True
                raise FrameError("worker client step/time lineage is not continuous")
        try:
            frame = encode_request(value)
            self.writer.write(frame); self.writer.flush()
            result: queue.Queue[tuple[bytes | None, BaseException | None]] = queue.Queue(maxsize=1)

            def read_frame() -> None:
                try:
                    def read_exact(size: int) -> bytes:
                        chunks: list[bytes] = []
                        remaining = size
                        while remaining:
                            chunk = self.reader.read(remaining)
                            if not chunk:
                                break
                            chunks.append(chunk)
                            remaining -= len(chunk)
                        return b"".join(chunks)

                    header = read_exact(HEADER.size)
                    if len(header) != HEADER.size:
                        raise FrameError("worker disconnected before response header")
                    magic, length, count = HEADER.unpack(header)
                    if magic != b"CFDANCF1" or length > 64 * 1024 * 1024 or count != 2:
                        raise FrameError("response magic/length/count is invalid")
                    body = read_exact(length)
                    if len(body) != length:
                        raise FrameError("worker disconnected during response")
                    result.put((header + body, None))
                except BaseException as exc:
                    result.put((None, exc))

            threading.Thread(target=read_frame, name="cpp-worker-response-reader", daemon=True).start()
            try:
                frame, error = result.get(timeout=self.timeout_s)
            except queue.Empty as exc:
                raise FrameError(f"worker response exceeded {self.timeout_s:g}s") from exc
            if error is not None:
                raise error
            if frame is None:
                raise FrameError("worker response frame is missing")
            response = decode_response(frame)
            validate_response(value, response)
        except Exception:
            self.closed = True
            raise
        if (len(self.seen_request_ids) >= self.MAX_SEEN_IDENTITIES or
                len(self.seen_transaction_ids) >= self.MAX_SEEN_IDENTITIES):
            self.closed = True
            raise FrameError("worker identity replay window exhausted")
        self.last_sequence = value.sequence
        self.last_global_step = value.global_step
        self.last_bridge_step = value.case_local_bridge_step
        self.last_tick = value.integer_tick
        self.last_time_s = value.time_s
        self.last_dt_s = value.dt_s
        self.seen_request_ids.add(value.request_id)
        self.seen_transaction_ids.add(value.transaction_id)
        return response

    def initialize(self) -> None:
        if self.closed or self.initialized:
            raise FrameError("worker client is closed")
        try:
            self.writer.write(encode_control(MESSAGE_INITIALIZE)); self.writer.flush()
        except Exception:
            self.closed = True
            raise
        self.initialized = True

    def shutdown(self) -> None:
        if not self.closed:
            try:
                self.writer.write(encode_control(MESSAGE_SHUTDOWN)); self.writer.flush()
            except Exception:
                self.closed = True
                raise
            self.closed = True

    def close(self) -> None:
        self.closed = True


def response_state_sha256(response: StepResponse) -> bytes:
    payload = struct.pack("<" + "d" * (len(response.q) * 3), *(response.q + response.qdot + response.qddot))
    return hashlib.sha256(payload).digest()
