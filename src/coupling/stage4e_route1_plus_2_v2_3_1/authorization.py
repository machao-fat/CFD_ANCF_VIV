"""Authorization rules for the one-time scenario-S sensitivity run.

This module is intentionally independent from the v2.3 implementation.  A
low-amplitude or transition-not-activated N result does not authorize tuning,
but it does authorize the pre-declared S sensitivity case once when the source
audit passes.
"""

from __future__ import annotations

from math import isclose


S_INPUT = {
    "U_mps": 0.43414375179615955,
    "D_m": 0.02841,
    "nu_m2ps": 1.0e-6,
    "rho_kgpm3": 1000.0,
    "Re": 12334.023988528894,
    "Tu_percent": 4.472135954999579,
    "I_fraction": 0.044721359549995794,
    "k_m2ps2": 0.000565442391670936,
    "omega_1ps": 305.627421187018,
    "ReThetat": 132.86363717120778,
    "gammaInt": 1.0,
}


def authorize_scenario_s(
    n_status: str,
    source_audit_passed: bool,
    *,
    scenario_count: int = 0,
    fine_requested: bool = False,
) -> dict:
    """Return a deterministic authorization record for the single S run."""

    reasons = []
    n_allows = n_status in {"rejected_low_amplitude", "transition_not_activated"}
    if not n_allows:
        reasons.append("N status is not an allowed S-entry status")
    if not source_audit_passed:
        reasons.append("kOmegaSSTLM source audit did not pass")
    if scenario_count >= 1:
        reasons.append("scenario S has already been run")
    if fine_requested:
        reasons.append("fine is prohibited in v2.3.1")
    return {
        "scenario": "S",
        "authorized": not reasons,
        "run_once_only": True,
        "n_status": n_status,
        "source_audit_passed": bool(source_audit_passed),
        "scenario_count_before": int(scenario_count),
        "fine_requested": bool(fine_requested),
        "reason": "authorized_once_after_N_low_amplitude_or_transition_not_activated"
        if not reasons
        else "; ".join(reasons),
    }


def validate_s_input_contract(values: dict, tolerance: float = 1.0e-12) -> dict:
    """Check the frozen S input values without accepting fitted alternatives."""

    mismatches = {}
    for key, expected in S_INPUT.items():
        actual = values.get(key)
        if actual is None or not isclose(float(actual), expected, rel_tol=tolerance, abs_tol=tolerance):
            mismatches[key] = {"expected": expected, "actual": actual}
    return {"passed": not mismatches, "mismatches": mismatches, "values": dict(values)}
