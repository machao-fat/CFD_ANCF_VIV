from __future__ import annotations

import queue
import threading
import time
import math
from dataclasses import dataclass
from typing import Any

from .contracts import IPCMessage, ProtocolViolation, SCHEMA_VERSION, finite_audit, payload_hash


class IPCProtocolError(ProtocolViolation):
    """Persistent IPC rejects a message and enters fail-closed state."""


@dataclass(frozen=True)
class IPCStats:
    sent: int
    received: int
    rejected: int
    connected: bool
    closed_cleanly: bool
    failure_reason: str | None


class PersistentIPC:
    """A bounded in-process persistent channel used by offline tests.

    The same validation rules are intended for a future socket/pipe backend.
    Once a protocol error, timeout, or disconnect occurs the channel is
    poisoned; callers must not retry within the same runtime.
    """

    def __init__(self, *, run_id: str, case_id: str, slice_id: int,
                 timeout_s: float = 1.0, maxsize: int = 128) -> None:
        self.run_id, self.case_id, self.slice_id = run_id, case_id, int(slice_id)
        self.timeout_s = float(timeout_s)
        self._queue: queue.Queue[IPCMessage] = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._last_sequence: dict[str, int] = {}
        self._last_step: dict[str, int] = {}
        self._last_bridge_step: dict[str, int] = {}
        self._last_tick: dict[str, int] = {}
        self._last_time: dict[str, float] = {}
        self._last_ack: dict[str, bool] = {}
        self._last_received_sequence: dict[str, int] = {}
        self._last_received_step: dict[str, int] = {}
        self._last_received_bridge_step: dict[str, int] = {}
        self._last_received_tick: dict[str, int] = {}
        self._last_received_time: dict[str, float] = {}
        self._last_received_ack: dict[str, bool] = {}
        self._seen_request_ids: set[str] = set()
        self._seen_transaction_ids: set[str] = set()
        self._seen_ack_ids: set[tuple[str, str]] = set()
        self._request_payload_hashes: dict[tuple[str, str], str] = {}
        self._sent = self._received = self._rejected = 0
        self.connected = True
        self.poisoned = False
        self.failure_reason: str | None = None

    def _fail(self, message: str) -> None:
        with self._lock:
            self._rejected += 1
            self.poisoned = True
            self.failure_reason = message
        raise IPCProtocolError(message)

    def _validate(self, message: IPCMessage) -> None:
        if self.poisoned:
            raise IPCProtocolError(self.failure_reason or "IPC channel is fail-closed")
        if not self.connected:
            self._fail("disconnect")
        if message.schema_version != SCHEMA_VERSION:
            self._fail("schema_version mismatch")
        try:
            finite_audit(message.payload, "ipc.payload")
        except ProtocolViolation as exc:
            self._fail(str(exc))
        if payload_hash(message.payload) != message.payload_hash:
            self._fail("payload hash mismatch")
        identity = (message.request_id, message.transaction_id)
        if message.ack:
            expected_hash = self._request_payload_hashes.get(identity)
            if expected_hash is None or message.payload != {"ack_for": expected_hash}:
                self._fail("received ack payload does not match request")
        if (message.run_id, message.case_id, message.slice_id) != (self.run_id, self.case_id, self.slice_id):
            self._fail("run/case/slice identity mismatch")
        if not math.isfinite(message.time_s):
            self._fail("non-finite time_s")
        if message.global_step < 0 or message.case_local_bridge_step < 0 or message.integer_tick < 0:
            self._fail("negative step or tick")
        if not message.producer or not message.consumer or not message.request_id or not message.transaction_id:
            self._fail("missing IPC identity field")
        endpoints = {"matlab", f"openfoam_{self.slice_id}"}
        if message.producer not in endpoints or message.consumer not in endpoints or message.producer == message.consumer:
            self._fail("producer/consumer identity mismatch")
        if not math.isfinite(message.time_s):
            self._fail("received non-finite time_s")
        if message.sequence <= 0:
            self._fail("invalid sequence")
        last = self._last_sequence.get(message.producer, 0)
        if message.sequence <= last:
            self._fail("duplicate or stale sequence")
        if message.sequence != last + 1:
            self._fail("out-of-order sequence")
        previous_step = self._last_step.get(message.producer)
        previous_bridge_step = self._last_bridge_step.get(message.producer)
        previous_tick = self._last_tick.get(message.producer)
        previous_time = self._last_time.get(message.producer)
        if previous_step is not None and message.global_step < previous_step:
            self._fail("stale global_step")
        if previous_step is not None and message.global_step == previous_step and self._last_ack.get(message.producer) == message.ack:
            self._fail("stale global_step")
        if previous_bridge_step is not None and message.case_local_bridge_step < previous_bridge_step:
            self._fail("stale case_local_bridge_step")
        if previous_bridge_step is not None and message.case_local_bridge_step == previous_bridge_step and self._last_ack.get(message.producer) == message.ack:
            self._fail("stale case_local_bridge_step")
        if previous_tick is not None and message.integer_tick < previous_tick:
            self._fail("stale integer_tick")
        if previous_tick is not None and message.integer_tick == previous_tick and self._last_ack.get(message.producer) == message.ack:
            self._fail("stale integer_tick")
        if previous_time is not None and message.time_s < previous_time:
            self._fail("stale time_s")
        if previous_time is not None and message.time_s == previous_time and self._last_ack.get(message.producer) == message.ack:
            self._fail("stale time_s")
        if message.request_id in self._seen_request_ids and not message.ack:
            self._fail("duplicate request_id")
        if message.transaction_id in self._seen_transaction_ids and not message.ack:
            self._fail("duplicate transaction_id")
        identity = (message.request_id, message.transaction_id)
        if message.ack:
            expected_hash = self._request_payload_hashes.get(identity)
            if expected_hash is None or message.payload != {"ack_for": expected_hash}:
                self._fail("ack payload does not match request")
        else:
            self._request_payload_hashes[identity] = message.payload_hash
        if message.ack and (message.request_id, message.transaction_id) in self._seen_ack_ids:
            self._fail("duplicate ack")

    def _validate_received(self, message: IPCMessage) -> None:
        """Validate data at the consumer boundary as well as at send time.

        The queue is intentionally an implementation detail, but validating
        on both sides makes a future socket/pipe backend fail closed if a
        peer injects, mutates, or replays a frame after it was sent.
        """
        if self.poisoned:
            raise IPCProtocolError(self.failure_reason or "IPC channel is fail-closed")
        if not self.connected:
            self._fail("disconnect")
        try:
            finite_audit(message.payload, "ipc.payload")
        except ProtocolViolation as exc:
            self._fail(str(exc))
        if message.schema_version != SCHEMA_VERSION:
            self._fail("schema_version mismatch")
        if (message.run_id, message.case_id, message.slice_id) != (self.run_id, self.case_id, self.slice_id):
            self._fail("run/case/slice identity mismatch")
        if not message.producer or not message.consumer or not message.request_id or not message.transaction_id:
            self._fail("missing IPC identity field")
        endpoints = {"matlab", f"openfoam_{self.slice_id}"}
        if message.producer not in endpoints or message.consumer not in endpoints or message.producer == message.consumer:
            self._fail("received producer/consumer identity mismatch")
        if message.sequence <= 0:
            self._fail("invalid sequence")
        expected = self._last_received_sequence.get(message.producer, 0) + 1
        if message.sequence != expected:
            self._fail("received stale, duplicate, or out-of-order sequence")
        if payload_hash(message.payload) != message.payload_hash:
            self._fail("payload hash mismatch")
        identity = (message.request_id, message.transaction_id)
        if message.ack:
            expected_hash = self._request_payload_hashes.get(identity)
            if expected_hash is None or message.payload != {"ack_for": expected_hash}:
                self._fail("received ack payload does not match request")
        previous_step = self._last_received_step.get(message.producer)
        previous_bridge_step = self._last_received_bridge_step.get(message.producer)
        previous_tick = self._last_received_tick.get(message.producer)
        previous_time = self._last_received_time.get(message.producer)
        previous_ack = self._last_received_ack.get(message.producer)
        if previous_step is not None and message.global_step < previous_step:
            self._fail("received stale global_step")
        if previous_step is not None and message.global_step == previous_step and previous_ack == message.ack:
            self._fail("received stale global_step")
        if previous_bridge_step is not None and message.case_local_bridge_step < previous_bridge_step:
            self._fail("received stale case_local_bridge_step")
        if previous_bridge_step is not None and message.case_local_bridge_step == previous_bridge_step and previous_ack == message.ack:
            self._fail("received stale case_local_bridge_step")
        if previous_tick is not None and message.integer_tick < previous_tick:
            self._fail("received stale integer_tick")
        if previous_tick is not None and message.integer_tick == previous_tick and previous_ack == message.ack:
            self._fail("received stale integer_tick")
        if previous_time is not None and message.time_s < previous_time:
            self._fail("received stale time_s")
        if previous_time is not None and message.time_s == previous_time and previous_ack == message.ack:
            self._fail("received stale time_s")

        self._last_received_sequence[message.producer] = message.sequence
        self._last_received_step[message.producer] = message.global_step
        self._last_received_bridge_step[message.producer] = message.case_local_bridge_step
        self._last_received_tick[message.producer] = message.integer_tick
        self._last_received_time[message.producer] = message.time_s
        self._last_received_ack[message.producer] = message.ack

    def send(self, message: IPCMessage, *, timeout_s: float | None = None) -> None:
        self._validate(message)
        try:
            self._queue.put(message, timeout=self.timeout_s if timeout_s is None else timeout_s)
        except queue.Full:
            self._fail("timeout while sending IPC message")
        with self._lock:
            self._last_sequence[message.producer] = message.sequence
            self._last_step[message.producer] = message.global_step
            self._last_bridge_step[message.producer] = message.case_local_bridge_step
            self._last_tick[message.producer] = message.integer_tick
            self._last_time[message.producer] = message.time_s
            self._last_ack[message.producer] = message.ack
            self._seen_request_ids.add(message.request_id)
            self._seen_transaction_ids.add(message.transaction_id)
            if message.ack:
                self._seen_ack_ids.add((message.request_id, message.transaction_id))
            self._sent += 1

    def receive(self, *, timeout_s: float | None = None) -> IPCMessage:
        if self.poisoned:
            raise IPCProtocolError(self.failure_reason or "IPC channel is fail-closed")
        if not self.connected:
            self._fail("disconnect")
        try:
            message = self._queue.get(timeout=self.timeout_s if timeout_s is None else timeout_s)
        except queue.Empty:
            self._fail("timeout waiting for IPC message")
        self._validate_received(message)
        with self._lock:
            self._received += 1
        return message

    def ack(self, message: IPCMessage, *, producer: str, consumer: str, sequence: int) -> IPCMessage:
        if message.ack:
            self._fail("cannot acknowledge an acknowledgement")
        return IPCMessage.create(
            run_id=self.run_id, case_id=self.case_id, slice_id=self.slice_id,
            global_step=message.global_step, case_local_bridge_step=message.case_local_bridge_step,
            time_s=message.time_s, integer_tick=message.integer_tick,
            request_id=message.request_id, transaction_id=message.transaction_id,
            sequence=sequence, producer=producer, consumer=consumer, ack=True,
            payload={"ack_for": message.payload_hash},
        )

    def disconnect(self) -> None:
        """Record an unexpected peer disconnect and poison this runtime."""
        self.connected = False
        self.poisoned = True
        self.failure_reason = "disconnect"

    def close(self) -> None:
        """Close a healthy channel without poisoning its protocol state."""
        self.connected = False

    def stats(self) -> IPCStats:
        return IPCStats(self._sent, self._received, self._rejected, self.connected and not self.poisoned,
                        (not self.connected and not self.poisoned), self.failure_reason)
