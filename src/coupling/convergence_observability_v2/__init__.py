"""Versioned OpenFOAM quality parsing for offline convergence audits."""

from .openfoam_log import OpenFOAMQualityError, OpenFOAMQualityParser

__all__ = ["OpenFOAMQualityError", "OpenFOAMQualityParser"]
