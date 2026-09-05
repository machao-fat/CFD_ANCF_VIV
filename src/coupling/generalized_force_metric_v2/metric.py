"""Mixed-unit generalized-force equality metric for ANCF Hermite DOFs.

For q=[r, r_s] at each node, r has unit m and r_s=dr/ds is
dimensionless.  Its virtual-work conjugates consequently have units N and
N m respectively.  This module deliberately never forms a mixed-unit norm
as a pass/fail criterion.
"""
from __future__ import annotations

import math
import sys
from typing import Any, Sequence

MACHINE_EPSILON = sys.float_info.epsilon
SAFETY_ULPS = 128
RTOL = SAFETY_ULPS * MACHINE_EPSILON
POSITION_ATOL_N = RTOL * 1.0


def freeze_contract(element_length_m: float) -> dict[str, Any]:
    if not math.isfinite(element_length_m) or element_length_m <= 0.0:
        raise ValueError("element_length_m must be finite and positive")
    return {
        "schema_version": "generalized-force-metric-v2.0.0",
        "formula": "abs(Q_cpp_j-Q_formal_j) <= atol_group + rtol * sum_i(abs(Q_formal_i_j))",
        "contribution_scale": "sum over structural slices of abs(formal H_i^T F_i contribution for DOF j)",
        "mixed_unit_policy": "evaluate positional and slope DOFs independently; no mixed-unit vector norm is a hard gate",
        "floating_point_basis": {"machine_epsilon": MACHINE_EPSILON, "safety_ulps": SAFETY_ULPS,
                                   "rtol": RTOL},
        "position": {"q_unit": "m", "Q_unit": "N", "atol": POSITION_ATOL_N},
        "slope": {"q_unit": "1 (m/m)", "Q_unit": "N*m",
                  "atol": POSITION_ATOL_N * element_length_m,
                  "element_length_m": element_length_m},
        "zero_contribution_policy": "when contribution_scale is zero, apply the dimensionally correct absolute floor; exact zero is separately required by the zero-force regression",
        "legacy_metric": "legacy_absolute_inf_error is diagnostic only",
    }


DEFAULT_CONTRACT = freeze_contract(3.125)


def _dof(index: int, contract: dict[str, Any]) -> dict[str, Any]:
    component = index % 6
    if component < 3:
        kind = "position"
        label = ("x", "y", "z")[component]
    else:
        kind = "slope"
        label = ("x", "y", "z")[component - 3]
    item = contract[kind]
    return {"dof_index": index, "dof_type": f"{kind}_{label}", "q_unit": item["q_unit"],
            "Q_unit": item["Q_unit"], "atol": float(item["atol"]), "rtol": float(contract["floating_point_basis"]["rtol"])}


def evaluate(q_formal: Sequence[float], q_cpp: Sequence[float],
             formal_slice_contributions: Sequence[Sequence[float]] | dict[int, Sequence[float]],
             *, contract: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the V2 criterion without altering either mapping result."""
    formal = [float(x) for x in q_formal]
    cpp = [float(x) for x in q_cpp]
    rows = list(formal_slice_contributions.values()) if isinstance(formal_slice_contributions, dict) else list(formal_slice_contributions)
    contributions = [[float(x) for x in row] for row in rows]
    if not formal or len(formal) != len(cpp) or any(len(row) != len(formal) for row in contributions):
        raise ValueError("generalized-force vector length mismatch")
    if not all(math.isfinite(x) for x in formal + cpp + [v for row in contributions for v in row]):
        raise ValueError("generalized-force metric inputs must be finite")
    per_dof: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(zip(formal, cpp)):
        item = _dof(index, contract)
        scale = sum(abs(row[index]) for row in contributions)
        delta = abs(right - left)
        threshold = item["atol"] + item["rtol"] * scale
        normalized = delta / (scale if scale > 0.0 else item["atol"] / item["rtol"])
        utilization = delta / threshold
        per_dof.append({**item, "Q_formal": left, "Q_cpp": right, "absolute_error": delta,
                        "contribution_scale": scale, "threshold": threshold,
                        "normalized_error": normalized, "threshold_utilization": utilization,
                        "pass": delta <= threshold})
    legacy = max(item["absolute_error"] for item in per_dof)
    return {"GENERALIZED_FORCE_MAPPING_V2": "PASS" if all(item["pass"] for item in per_dof) else "FAIL",
            "GENERALIZED_FORCE_LEGACY_ABS_DIAGNOSTIC": legacy,
            "metric_contract_schema": contract["schema_version"],
            "per_dof": per_dof,
            "max_threshold_utilization": max(item["threshold_utilization"] for item in per_dof),
            "max_normalized_error": max(item["normalized_error"] for item in per_dof),
            "max_absolute_error": legacy}
