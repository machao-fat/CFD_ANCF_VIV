"""Versioned OpenFOAM numerical-quality parsing and fail-closed evaluation."""

from .audit import AuditError, audit_log, evaluate_quality, parse_fv_solution

__all__ = ["AuditError", "audit_log", "evaluate_quality", "parse_fv_solution"]
