"""Compatibility exports for the performance optimization protocol."""

from .contracts import IPCMessage, OptimizationConfig, ProtocolViolation, WorkerEnvelope, finite_audit
from .ipc import IPCProtocolError, PersistentIPC

__all__ = ["IPCMessage", "OptimizationConfig", "ProtocolViolation", "WorkerEnvelope", "finite_audit", "IPCProtocolError", "PersistentIPC"]
