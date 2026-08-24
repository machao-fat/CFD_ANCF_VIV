"""Stage-4B multi-slice orchestration on the formal 0.2.1 protocol."""

from .ancf_adapter import ANCFAdapterError, ProductionANCFAdapter
from .contract import (
    CONSUMED_FIELDS,
    IDENTITY_R_GL,
    LOAD_FIELDS,
    MOTION_FIELDS,
    READY_FIELDS,
    SCHEMA_VERSION,
    ContractError,
    LoadRecord,
    MotionRecord,
    RuntimeConfig,
    SliceDefinition,
    SliceExchangePaths,
    SliceManifest,
    SliceSpec,
)
from .scheduler import (
    MultiSliceConfig,
    MultiSliceScheduler,
    SchedulerError,
    SchedulerState,
    SliceProcess,
    StepResult,
    StructureAdapter,
)

__all__ = [
    "SCHEMA_VERSION", "IDENTITY_R_GL", "MOTION_FIELDS", "LOAD_FIELDS", "READY_FIELDS", "CONSUMED_FIELDS",
    "ContractError", "SliceDefinition", "SliceManifest", "RuntimeConfig", "MotionRecord", "LoadRecord",
    "SliceSpec", "SliceExchangePaths", "MultiSliceConfig", "MultiSliceScheduler", "SchedulerError",
    "SchedulerState", "SliceProcess", "StructureAdapter", "StepResult", "ProductionANCFAdapter",
    "ANCFAdapterError",
]

