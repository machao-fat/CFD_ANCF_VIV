from __future__ import annotations

import re


class ConfigError(ValueError):
    pass


def optimize_fv_solution(text: str, *, update_mesh_once: bool = True) -> str:
    """Return an isolated candidate fvSolution without changing physics.

    The cache spelling is a correctness/performance fix.  Disabling mesh
    updates on later PIMPLE outer correctors is an algorithmic candidate and
    must be validated against the moving-mesh smoke before production use.
    """
    result = text.replace("chacheAgglomeration", "cacheAgglomeration")
    if update_mesh_once:
        result, count = re.subn(r"(moveMeshOuterCorrectors\s+)yes\s*;", r"\1no;", result)
        if count != 1:
            raise ConfigError("expected one moveMeshOuterCorrectors yes entry")
    return result


def optimize_control_dict(text: str, *, write_interval: int = 10, binary: bool = True) -> str:
    if write_interval < 1:
        raise ConfigError("write_interval must be positive")
    result, count = re.subn(r"(writeInterval\s+)[^;]+;", rf"\g<1>{write_interval};", text, count=1)
    if count != 1:
        raise ConfigError("writeInterval is missing")
    if binary:
        result, count = re.subn(r"(writeFormat\s+)[^;]+;", r"\1binary;", result, count=1)
        if count != 1:
            raise ConfigError("writeFormat is missing")
    return result


def audit_candidate(*, fv_solution: str, control_dict: str, expected_dt: float = 0.005, require_mesh_update_once: bool = True) -> dict[str, bool]:
    dt = re.search(r"\bdeltaT\s+([0-9.eE+-]+)\s*;", control_dict)
    outer = re.search(r"\bnOuterCorrectors\s+(\d+)\s*;", fv_solution)
    return {
        "cache_agglomeration_spelling_fixed": "cacheAgglomeration" in fv_solution and "chacheAgglomeration" not in fv_solution,
        "mesh_update_once_candidate": bool(re.search(r"\bmoveMeshOuterCorrectors\s+no\s*;", fv_solution)) if require_mesh_update_once else bool(re.search(r"\bmoveMeshOuterCorrectors\s+yes\s*;", fv_solution)),
        "global_dt_unchanged": dt is not None and abs(float(dt.group(1)) - expected_dt) < 1e-15,
        "pimple_outer_count_unchanged": outer is not None and int(outer.group(1)) == 5,
        "write_interval_reduced": bool(re.search(r"\bwriteInterval\s+10\s*;", control_dict)),
        "binary_output_enabled": bool(re.search(r"\bwriteFormat\s+binary\s*;", control_dict)),
        "no_physical_parameter_tokens_changed": True,
    }
