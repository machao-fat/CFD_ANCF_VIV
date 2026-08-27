from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from .protocol import ExchangeMessage, ProtocolError


class ParticipantError(ProtocolError):
    pass


class ParticipantState(str, Enum):
    CREATED = "CREATED"
    INITIALIZED = "INITIALIZED"
    FINALIZED = "FINALIZED"
    FAILED = "FAILED"


class ParticipantBackend(Protocol):
    def initialize(self) -> None: ...
    def write_displacement(self, payload: dict[str, Any]) -> None: ...
    def advance(self, dt_s: float) -> None: ...
    def read_force(self) -> dict[str, Any]: ...
    def finalize(self) -> None: ...


@dataclass
class ParticipantSession:
    """Strict lifecycle wrapper shared by a future preCICE backend and mocks."""

    backend: ParticipantBackend
    run_id: str
    case_id: str
    slice_id: str
    dt_s: float
    state: ParticipantState = ParticipantState.CREATED
    global_step: int = 0
    local_bridge_step: int = 0
    _write_step: int | None = None
    _advanced_step: int | None = None

    def initialize(self) -> None:
        if self.state is not ParticipantState.CREATED:
            raise ParticipantError("participant initialize called in invalid state")
        if self.dt_s <= 0:
            raise ParticipantError("coupling dt must be positive")
        self.backend.initialize()
        self.state = ParticipantState.INITIALIZED

    def write_displacement(self, message: ExchangeMessage) -> None:
        self._check_message(message, "displacement")
        if self.state is not ParticipantState.INITIALIZED:
            raise ParticipantError("write requires INITIALIZED participant")
        if self._write_step is not None:
            raise ParticipantError("duplicate displacement write")
        self.backend.write_displacement(dict(message.payload))
        self._write_step = self.global_step

    def advance(self) -> None:
        if self.state is not ParticipantState.INITIALIZED:
            raise ParticipantError("advance requires INITIALIZED participant")
        if self._write_step != self.global_step:
            raise ParticipantError("advance requires displacement for current step")
        self.backend.advance(self.dt_s)
        self._advanced_step = self.global_step

    def read_force(self, message: ExchangeMessage) -> dict[str, Any]:
        self._check_message(message, "force")
        if self.state is not ParticipantState.INITIALIZED:
            raise ParticipantError("read requires INITIALIZED participant")
        if self._advanced_step != self.global_step:
            raise ParticipantError("read requires advance for current step")
        payload = self.backend.read_force()
        self.global_step += 1
        self.local_bridge_step += 1
        self._write_step = None
        self._advanced_step = None
        return payload

    def finalize(self) -> None:
        if self.state is ParticipantState.FINALIZED:
            raise ParticipantError("duplicate finalize")
        if self.state is ParticipantState.INITIALIZED and (self._write_step is not None or self._advanced_step is not None):
            raise ParticipantError("cannot finalize with an incomplete exchange")
        self.backend.finalize()
        self.state = ParticipantState.FINALIZED

    def _check_message(self, message: ExchangeMessage, kind: str) -> None:
        try:
            message.validate()
        except ProtocolError as exc:
            self.state = ParticipantState.FAILED
            raise ParticipantError(str(exc)) from exc
        expected_tick = int(round(message.time_s * 1e9))
        if (message.run_id, message.case_id, message.slice_id) != (self.run_id, self.case_id, self.slice_id):
            self.state = ParticipantState.FAILED
            raise ParticipantError("participant identity mismatch")
        if message.global_step != self.global_step or message.case_local_bridge_step != self.local_bridge_step:
            self.state = ParticipantState.FAILED
            raise ParticipantError("participant step mismatch")
        if message.integer_tick != expected_tick or message.kind != kind:
            self.state = ParticipantState.FAILED
            raise ParticipantError("participant time/kind mismatch")
