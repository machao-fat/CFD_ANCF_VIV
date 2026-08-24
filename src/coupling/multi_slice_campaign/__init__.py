"""Stage 4C-A mock campaign helpers.

This package is deliberately downstream of the frozen 0.2.1 mapping,
driver, and checkpoint modules.  It owns only candidate geometry, synthetic
loads, campaign orchestration, and audit/report assembly.
"""

from .campaign import (
    CampaignDefinition,
    FaultInjectCheckpointManager,
    SyntheticLoadModel,
    build_candidate_definition,
    build_scale_definition,
    load_candidate_pair,
    map_spatial_loads,
    run_failure_injection_matrix,
    run_mock_campaign,
    run_restart_comparison,
    serialize_candidate_pair,
    validate_slice_coverage,
)

__all__ = [
    "CampaignDefinition",
    "FaultInjectCheckpointManager",
    "SyntheticLoadModel",
    "build_candidate_definition",
    "build_scale_definition",
    "load_candidate_pair",
    "map_spatial_loads",
    "run_failure_injection_matrix",
    "run_mock_campaign",
    "run_restart_comparison",
    "serialize_candidate_pair",
    "validate_slice_coverage",
]
