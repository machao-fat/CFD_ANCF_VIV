"""Qualification evidence may be reused only when every identity is pinned."""

from __future__ import annotations

from typing import Any, Mapping


REQUIRED_IDENTITIES = (
    "worker_sha256",
    "worker_size_bytes",
    "worker_mtime_ns",
    "library_sha256",
    "model_contract_sha256",
    "gauss_order",
    "max_newton",
    "global_dt_s",
    "formal_protocol",
)


def assess_reuse(
    qualification: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare a completed dual-run qualification with a candidate segment.

    A previous Gate assertion alone is deliberately insufficient: the original
    MATLAB/C++ dual-run must be identified and every executable/configuration
    identity has to be present and equal.
    """
    errors: list[str] = []
    if qualification.get("dual_run_status") != "pass":
        errors.append("qualification does not contain a passing strict dual-run")
    if qualification.get("numerical_core_status") != "validated":
        errors.append("qualification numerical-core status is not validated")

    comparisons: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_IDENTITIES:
        left = qualification.get(name)
        right = candidate.get(name)
        available = left is not None and right is not None
        equal = available and left == right
        comparisons[name] = {"qualification": left, "candidate": right,
                             "available": available, "equal": equal}
        if not available:
            errors.append(f"missing identity: {name}")
        elif not equal:
            errors.append(f"identity mismatch: {name}")

    eligible = not errors
    return {
        "status": "pass" if eligible else "not_evaluable",
        "C++_ANCF_NUMERICAL_CORE_STATUS": (
            "qualified_by_reuse" if eligible else "not_completed"
        ),
        "reuse_eligible": eligible,
        "comparisons": comparisons,
        "errors": errors,
    }
