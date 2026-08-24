"""Offline-only performance optimization harness for CFD_ANCF_VIV.

The package models the proposed lifecycle and protocol changes without
starting MATLAB, OpenFOAM, WSL, or CFD.  It is deliberately isolated from the
formal 0.2.1 runtime and produces auditable benchmark artifacts.
"""

from .contracts import (
    OptimizationConfig,
    ProtocolViolation,
    ProcessAudit,
    WorkerEnvelope,
    IPCMessage,
    finite_audit,
)
from .ipc import PersistentIPC, IPCProtocolError, IPCStats
from .workers import MockMatlabWorker, MockOpenFOAMSlice, WorkerLifecycleError
from .scheduler import GlobalBarrierScheduler, BarrierError, SchedulerResult, StepRecord
from .benchmark import BenchmarkRunner, BenchmarkReport, LatencyProfile, STAGES, run_offline_benchmark

__all__ = [
    "OptimizationConfig", "ProtocolViolation", "ProcessAudit", "WorkerEnvelope",
    "IPCMessage", "finite_audit", "PersistentIPC", "IPCProtocolError", "IPCStats",
    "MockMatlabWorker", "MockOpenFOAMSlice", "WorkerLifecycleError",
    "GlobalBarrierScheduler", "BarrierError", "SchedulerResult", "StepRecord",
    "BenchmarkRunner", "BenchmarkReport", "LatencyProfile", "STAGES",
    "run_offline_benchmark",
]
