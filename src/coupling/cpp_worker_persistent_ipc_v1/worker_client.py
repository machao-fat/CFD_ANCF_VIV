from __future__ import annotations

import hashlib
import queue
import struct
import threading
from typing import BinaryIO

from .protocol import (HEADER, FrameError, StepRequest, StepResponse, decode_response,
                       canonical_tick_delta, encode_control, encode_request, validate_response,
                       INITIALIZE_ACK, MESSAGE_INITIALIZE, MESSAGE_INITIALIZE_ACK,
                       MESSAGE_SHUTDOWN, PROTOCOL_VERSION, SCHEMA_VERSION, WORKER_ROLE)


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
        self._reader_threads: set[threading.Thread] = set()

    def _close_streams(self) -> None:
        errors: list[BaseException] = []
        for stream in (self.reader, self.writer):
            try:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
            except (OSError, AttributeError) as exc:
                errors.append(exc)
        current = threading.current_thread()
        for thread in tuple(self._reader_threads):
            if thread is not current:
                thread.join(timeout=0.25)
            if not thread.is_alive():
                self._reader_threads.discard(thread)
        if errors:
            raise FrameError("worker stream cleanup failed") from errors[0]

    def _fail_closed(self) -> None:
        self.closed = True
        self.initialized = False
        try:
            self._close_streams()
        except FrameError:
            pass

    def _read_frame_bounded(self, expected_type: int) -> bytes:
        result: queue.Queue[tuple[bytes | None, BaseException | None]] = queue.Queue(maxsize=1)

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

        def read_frame() -> None:
            try:
                header = read_exact(HEADER.size)
                if len(header) != HEADER.size:
                    raise FrameError("worker disconnected before response header")
                magic, length, message_type = HEADER.unpack(header)
                if (magic != b"CFDANCF1" or length > 64 * 1024 * 1024 or
                        message_type != expected_type):
                    raise FrameError("worker response frame is invalid")
                body = read_exact(length)
                if len(body) != length:
                    raise FrameError("worker disconnected during response")
                result.put((header + body, None))
            except BaseException as exc:
                result.put((None, exc))

        thread = threading.Thread(target=read_frame, name="cpp-worker-response-reader", daemon=True)
        self._reader_threads.add(thread)
        thread.start()
        try:
            frame, error = result.get(timeout=self.timeout_s)
        except queue.Empty as exc:
            self._fail_closed()
            raise FrameError(f"worker response exceeded {self.timeout_s:g}s") from exc
        finally:
            if not thread.is_alive():
                self._reader_threads.discard(thread)
        if error is not None:
            raise error
        if frame is None:
            raise FrameError("worker response frame is missing")
        return frame

    def _wait_for_eof(self) -> None:
        result: queue.Queue[BaseException | None] = queue.Queue(maxsize=1)

        def wait() -> None:
            try:
                marker = self.reader.read(1)
                if marker:
                    raise FrameError("worker emitted data after shutdown")
                result.put(None)
            except BaseException as exc:
                result.put(exc)

        thread = threading.Thread(target=wait, name="cpp-worker-shutdown-reader", daemon=True)
        self._reader_threads.add(thread)
        thread.start()
        try:
            error = result.get(timeout=self.timeout_s)
        except queue.Empty as exc:
            self._fail_closed()
            raise FrameError(f"worker shutdown exceeded {self.timeout_s:g}s") from exc
        finally:
            if not thread.is_alive():
                self._reader_threads.discard(thread)
        if error is not None:
            raise error

    @staticmethod
    def _validate_initialize_ack(frame: bytes) -> None:
        body = frame[HEADER.size:]
        if len(body) != INITIALIZE_ACK.size:
            raise FrameError("worker initialization acknowledgement length is invalid")
        schema, protocol, message_type, role = INITIALIZE_ACK.unpack(body)
        if b"\0" not in role:
            raise FrameError("worker role acknowledgement is not terminated")
        raw_role, padding = role.split(b"\0", 1)
        if not raw_role or any(padding):
            raise FrameError("worker role acknowledgement padding is invalid")
        try:
            role_value = raw_role.decode("ascii")
        except UnicodeDecodeError as exc:
            raise FrameError("worker role acknowledgement is not ASCII") from exc
        if (schema != SCHEMA_VERSION or protocol != PROTOCOL_VERSION or
                message_type != MESSAGE_INITIALIZE_ACK or role_value != WORKER_ROLE):
            raise FrameError("worker initialization acknowledgement is invalid")

    def request(self, value: StepRequest) -> StepResponse:
        if self.closed or not self.initialized or value.sequence != self.last_sequence + 1:
            raise FrameError("worker client is closed or sequence is not monotonic")
        if value.request_id in self.seen_request_ids or value.transaction_id in self.seen_transaction_ids:
            raise FrameError("request_id or transaction_id was already used")
        if self.last_global_step is not None:
            tick_delta = canonical_tick_delta(self.last_dt_s)
            if tick_delta <= 0:
                self._fail_closed()
                raise FrameError("worker client dt does not advance an integer tick")
            expected_tick = self.last_tick + tick_delta
            if (value.global_step != self.last_global_step + 1 or
                    value.case_local_bridge_step != self.last_bridge_step + 1 or
                    value.integer_tick != expected_tick or
                    abs(value.time_s - (self.last_time_s + self.last_dt_s)) > 1.0e-12 or
                    abs(value.dt_s - self.last_dt_s) > 1.0e-15):
                self._fail_closed()
                raise FrameError("worker client step/time lineage is not continuous")
        try:
            frame = encode_request(value)
            self.writer.write(frame); self.writer.flush()
            response_frame = self._read_frame_bounded(2)
            response = decode_response(response_frame)
            validate_response(value, response)
        except Exception:
            self._fail_closed()
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
            self._validate_initialize_ack(self._read_frame_bounded(MESSAGE_INITIALIZE_ACK))
        except Exception:
            self._fail_closed()
            raise
        self.initialized = True

    def shutdown(self) -> None:
        if not self.closed:
            if not self.initialized:
                self._fail_closed()
                raise FrameError("worker shutdown requires initialization")
            try:
                self.writer.write(encode_control(MESSAGE_SHUTDOWN)); self.writer.flush()
                # A clean worker exits after the shutdown control frame and
                # closes its output stream. EOF is the only transport-level
                # shutdown acknowledgement in this protocol.
                self._wait_for_eof()
            except Exception:
                self._fail_closed()
                raise
            self.close()

    def close(self) -> None:
        if self.closed and not self.initialized and not self._reader_threads:
            return
        self.closed = True
        self.initialized = False
        self._close_streams()

    @property
    def owned_residual(self) -> int:
        """Return only residuals owned by this transport client.

        The client deliberately does not own the OS process, so its process
        return code must be audited by the process supervisor.  Reader
        threads, however, are client-owned and must never be silently lost.
        """
        return sum(1 for thread in self._reader_threads if thread.is_alive())

    @property
    def return_code(self) -> None:
        """Process return code is unavailable because this class owns streams only."""
        return None


def response_state_sha256(response: StepResponse) -> bytes:
    payload = struct.pack("<" + "d" * (len(response.q) * 3), *(response.q + response.qdot + response.qddot))
    return hashlib.sha256(payload).digest()
