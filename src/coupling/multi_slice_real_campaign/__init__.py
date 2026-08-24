"""Stage 4C-B real three-slice campaign helpers.

The package is a downstream wrapper around the frozen 0.2.1 mapping,
multi-slice driver, checkpoint manager and the existing OpenFOAM motion
library.  It owns run identity, fresh-case generation, bounded process
launching, the sidecar physics identity and report assembly; it does not
define a second protocol or force/mapping implementation.
"""

from .campaign import (
    BatchMatlabANCFRunner,
    OpenFOAMSliceProcess,
    build_physics_manifest,
    build_runtime_config,
    load_frozen_manifest,
    run_real_condition,
    stage_restart_case,
)

__all__ = [
    "BatchMatlabANCFRunner",
    "OpenFOAMSliceProcess",
    "build_physics_manifest",
    "build_runtime_config",
    "load_frozen_manifest",
    "run_real_condition",
    "stage_restart_case",
]
