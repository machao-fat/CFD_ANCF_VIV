"""Numerical-contract normalization for the real C++ confirm path.

The source ANCF contract uses the same integration and Newton limits as
``vertical_ttr_case``.  The historical dual-run fixture was generated with
different diagnostic values; it must never silently define a real confirm.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any


ANCF_GAUSS_ORDER = 3
ANCF_MAX_NEWTON = 40
ANCF_CONTRACT_SOURCE = "vertical_ttr_case_contract"


def normalize_model(model: Any) -> Any:
    """Return a model carrying the fixed ANCF numerical contract.

    Only the integration/iteration fields are normalized.  Geometry, material,
    physical loads, time step, damping, and all other model fields are kept
    unchanged.  A dataclass-like model is required so accidental mutation of a
    shared fixture cannot leak into other tests.
    """
    if not hasattr(model, "gauss_order") or not hasattr(model, "max_newton"):
        raise TypeError("ANCF model is missing numerical-contract fields")
    if not hasattr(model, "__dataclass_fields__"):
        raise TypeError("ANCF model must be a dataclass for isolated normalization")
    return replace(model, gauss_order=ANCF_GAUSS_ORDER, max_newton=ANCF_MAX_NEWTON)

