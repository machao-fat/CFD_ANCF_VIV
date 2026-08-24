from __future__ import annotations

import hashlib
import struct
from typing import BinaryIO

from .protocol import (HEADER, FrameError, StepRequest, StepResponse, decode_response,
                       encode_control, encode_request, validate_response,
                       MESSAGE_INITIALIZE, MESSAGE_SHUTDOWN)


class PersistentCppWorkerClient:
    """One persistent framed connection; no retry or reconnect is permitted."""

    def __init__(self, reader: BinaryIO, writer: BinaryIO) -> None:
        self.reader = reader
        self.writer = writer
        self.last_sequence = 0
        self.closed = False

    def request(self, value: StepRequest) -> StepResponse:
        if self.closed or value.sequence != self.last_sequence + 1:
            raise FrameError("worker client is closed or sequence is not monotonic")
        frame = encode_request(value)
        self.writer.write(frame); self.writer.flush()
        header = self.reader.read(HEADER.size)
        if len(header) != HEADER.size:
            raise FrameError("worker disconnected before response header")
        magic, length, count = HEADER.unpack(header)
        if length > 64 * 1024 * 1024 or count != 1:
            raise FrameError("response length/count is invalid")
        body = self.reader.read(length)
        if len(body) != length:
            raise FrameError("worker disconnected during response")
        response = decode_response(header + body)
        validate_response(value, response)
        self.last_sequence = value.sequence
        return response

    def initialize(self) -> None:
        if self.closed:
            raise FrameError("worker client is closed")
        self.writer.write(encode_control(MESSAGE_INITIALIZE)); self.writer.flush()

    def shutdown(self) -> None:
        if not self.closed:
            self.writer.write(encode_control(MESSAGE_SHUTDOWN)); self.writer.flush()
            self.closed = True

    def close(self) -> None:
        self.closed = True


def response_state_sha256(response: StepResponse) -> bytes:
    payload = struct.pack("<" + "d" * (len(response.q) * 3), *(response.q + response.qdot + response.qddot))
    return hashlib.sha256(payload).digest()
