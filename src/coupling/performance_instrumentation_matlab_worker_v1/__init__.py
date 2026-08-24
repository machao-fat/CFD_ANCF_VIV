"""Offline-only performance instrumentation and persistent MATLAB-worker protocol."""

from .protocol import ProtocolError, WorkerRequest, WorkerResponse, canonical_sha256
from .worker import OfflineMatlabWorker, WorkerProcessAudit
from .telemetry import StepTrace, TraceRecorder, summarize_traces
from .guards import OwnedProcessRegistry, ProtocolError as GuardProtocolError, no_real_process_start, validate_runtime_scope

__all__ = [
    "ProtocolError", "WorkerRequest", "WorkerResponse", "canonical_sha256",
    "OfflineMatlabWorker", "WorkerProcessAudit", "StepTrace", "TraceRecorder",
    "summarize_traces", "OwnedProcessRegistry", "GuardProtocolError", "no_real_process_start", "validate_runtime_scope",
]
