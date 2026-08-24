from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from coupling.performance_optimization_v1.ipc import IPCProtocolError, PersistentIPC
from coupling.performance_optimization_v1.contracts import IPCMessage


class MappedIPCError(IPCProtocolError):
    """IPC identity or source-to-bridge mapping failure."""


@dataclass(frozen=True)
class MappedIPCConfig:
    run_id: str
    case_id: str
    slice_id: int
    source_global_step: int
    source_time_s: float
    source_tick: int
    dt_s: float


class MappedPersistentIPC:
    """Persistent IPC with explicit global-to-case-local mapping checks."""

    def __init__(self, config: MappedIPCConfig, *, timeout_s: float = 1.0) -> None:
        if config.dt_s <= 0 or config.source_global_step < 0 or config.source_tick < 0:
            raise MappedIPCError("invalid IPC source mapping")
        self.config = config
        self.channel = PersistentIPC(run_id=config.run_id, case_id=config.case_id, slice_id=config.slice_id, timeout_s=timeout_s)

    def _validate_mapping(self, message: IPCMessage) -> None:
        expected_bridge = message.global_step - self.config.source_global_step
        if expected_bridge <= 0 or message.case_local_bridge_step != expected_bridge:
            raise MappedIPCError("global/case-local bridge step mismatch")
        expected_time = self.config.source_time_s + expected_bridge * self.config.dt_s
        if not math.isclose(message.time_s, expected_time, abs_tol=1e-12):
            raise MappedIPCError("global/case-local time mismatch")
        expected_tick = self.config.source_tick + int(round(expected_bridge * self.config.dt_s * 1_000_000_000))
        if message.integer_tick != expected_tick:
            raise MappedIPCError("global/case-local tick mismatch")

    def send(self, message: IPCMessage, *, timeout_s: float | None = None) -> None:
        self._validate_mapping(message); self.channel.send(message, timeout_s=timeout_s)

    def receive(self, *, timeout_s: float | None = None) -> IPCMessage:
        message = self.channel.receive(timeout_s=timeout_s); self._validate_mapping(message); return message

    def ack(self, message: IPCMessage, *, producer: str, consumer: str, sequence: int) -> IPCMessage:
        self._validate_mapping(message); return self.channel.ack(message, producer=producer, consumer=consumer, sequence=sequence)

    def disconnect(self) -> None: self.channel.disconnect()
    def close(self) -> None: self.channel.close()
    def stats(self) -> Any: return self.channel.stats()
