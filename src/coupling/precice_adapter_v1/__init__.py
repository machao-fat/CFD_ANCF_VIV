"""Isolated preCICE/file transport contract for single-slice validation."""

from .protocol import ExchangeMessage, ProtocolError, canonical_tick, make_message
from .barrier import GlobalBarrier, BarrierError
from .transports import FileTransport, PreciceTransport, TransportUnavailable
from .guards import NoCfdViolation, validate_probe_only_contract, assert_no_processes_started

__all__ = [
    "ExchangeMessage", "ProtocolError", "canonical_tick", "make_message", "GlobalBarrier",
    "BarrierError", "FileTransport", "PreciceTransport", "TransportUnavailable",
    "NoCfdViolation", "validate_probe_only_contract", "assert_no_processes_started",
]
