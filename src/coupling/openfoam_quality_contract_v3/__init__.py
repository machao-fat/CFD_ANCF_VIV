"""Separate OpenFOAM observability completeness from numerical quality."""

from .audit import audit_records, validate_numerical_quality_contract

__all__ = ["audit_records", "validate_numerical_quality_contract"]
