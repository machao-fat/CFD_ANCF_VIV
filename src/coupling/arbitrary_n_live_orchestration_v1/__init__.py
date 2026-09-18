"""Generic, offline-verifiable arbitrary-N coupling orchestration.

This package is deliberately additive.  It does not alter the existing
single-slice/three-slice entry points or the ANCF kernel/wire contract.
"""

from .manifest import (
    ManifestError,
    OrchestrationSlice,
    SliceManifest,
    build_slice_manifest,
)
from .topology import (
    LaunchDescriptor,
    PreciceTopologyError,
    generate_openfoam_launch_plan,
    generate_precice_xml,
    inspect_precice_xml,
)
from .coordinator import (
    CheckpointError,
    CouplingCheckpoint,
    ForceSample,
    FakePreciceFleet,
    GenericStructuralCoordinator,
    InMemoryANCFBackend,
    OrchestrationError,
    WorkerRequest,
    assemble_generalized_force,
)

__all__ = [
    "CheckpointError",
    "CouplingCheckpoint",
    "FakePreciceFleet",
    "ForceSample",
    "GenericStructuralCoordinator",
    "InMemoryANCFBackend",
    "LaunchDescriptor",
    "ManifestError",
    "OrchestrationError",
    "OrchestrationSlice",
    "PreciceTopologyError",
    "SliceManifest",
    "WorkerRequest",
    "assemble_generalized_force",
    "build_slice_manifest",
    "generate_openfoam_launch_plan",
    "generate_precice_xml",
    "inspect_precice_xml",
]
