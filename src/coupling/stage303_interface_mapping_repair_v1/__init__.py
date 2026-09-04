"""Canonical interface projection for the Stage 303 mapping repair."""

from .canonical_projection import (
    DEFAULT_ELEMENTS,
    DEFAULT_LENGTH_M,
    DEFAULT_SLICE_POSITIONS_M,
    MappingAudit,
    canonical_h_row,
    diagnose_mapping,
    project_interface,
)

__all__ = [
    "DEFAULT_ELEMENTS",
    "DEFAULT_LENGTH_M",
    "DEFAULT_SLICE_POSITIONS_M",
    "MappingAudit",
    "canonical_h_row",
    "diagnose_mapping",
    "project_interface",
]
