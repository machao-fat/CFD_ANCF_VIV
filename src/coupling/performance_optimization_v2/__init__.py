"""Stage95 performance optimization contracts and attribution utilities.

This package is deliberately process-neutral.  It can record a real
user-session benchmark, but it never starts MATLAB, OpenFOAM, WSL, or CFD.
"""

from .contracts import BenchmarkContract, Factor, FACTORS
from .attribution import AttributeResult, attribute_measurements
from .coordinator import PersistentSliceCoordinator, OpenFOAMProcessEngine, StepIdentity, CoordinatorError
from .ipc import MappedIPCConfig, MappedPersistentIPC
from .audit import BatchAuditWriter

__all__ = ["BenchmarkContract", "Factor", "FACTORS", "AttributeResult", "attribute_measurements",
           "PersistentSliceCoordinator", "OpenFOAMProcessEngine", "StepIdentity", "CoordinatorError", "MappedIPCConfig",
           "MappedPersistentIPC", "BatchAuditWriter"]
