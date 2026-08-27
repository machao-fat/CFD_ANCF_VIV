"""Isolated preCICE/file transport contract for single-slice validation."""

from .protocol import ExchangeMessage, ProtocolError, canonical_tick, make_message
from .barrier import GlobalBarrier, BarrierError
from .transports import FileTransport, PreciceTransport, TransportUnavailable
from .guards import NoCfdViolation, validate_probe_only_contract, assert_no_processes_started
from .participant import ParticipantError, ParticipantSession, ParticipantState
from .precice_backend import PreciceBackendError, PrecicePythonBackend

__all__ = [
    "ExchangeMessage", "ProtocolError", "canonical_tick", "make_message", "GlobalBarrier",
    "BarrierError", "FileTransport", "PreciceTransport", "TransportUnavailable",
    "NoCfdViolation", "validate_probe_only_contract", "assert_no_processes_started",
    "ParticipantError", "ParticipantSession", "ParticipantState",
    "PreciceBackendError", "PrecicePythonBackend",
]
