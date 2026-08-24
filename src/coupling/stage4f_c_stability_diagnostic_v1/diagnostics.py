"""Deterministic, solver-free audits for short-window feedback failures."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


class AuditFailure(ValueError):
    """Raised when a frozen transaction or identity contract is violated."""


def _finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise AuditFailure("non-finite value")
    return result


def analyze_amplification(
    states: Sequence[float],
    *,
    dt: float,
    tolerance: float = 1.0e-12,
) -> dict[str, Any]:
    """Estimate per-step amplification and classify monotonic feedback growth."""
    dt = _finite(dt)
    if dt <= 0 or len(states) < 2:
        raise AuditFailure("positive dt and two states are required")
    values = [_finite(v) for v in states]
    ratios: list[float] = []
    for previous, current in zip(values, values[1:]):
        if abs(previous) <= tolerance:
            continue
        ratios.append(current / previous)
    growth = [abs(r) for r in ratios]
    return {
        "dt_s": dt,
        "ratios": ratios,
        "max_abs_amplification": max(growth, default=None),
        "mean_abs_amplification": sum(growth) / len(growth) if growth else None,
        "monotonic_absolute_growth": all(b > a + tolerance for a, b in zip(map(abs, values), map(abs, values[1:]))),
        "unstable_diagnostic": bool(growth and max(growth) > 1.0 + tolerance),
        "classification": "amplifying_feedback" if growth and max(growth) > 1.0 + tolerance else "not_amplifying",
    }


def audit_time_layers(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require one force transaction per step and exact predictor/commit alignment."""
    if not records:
        raise AuditFailure("no time-layer records")
    failures: list[str] = []
    seen: set[int] = set()
    for row in records:
        step = int(row.get("step", -1))
        if step in seen:
            failures.append(f"duplicate_step:{step}")
        seen.add(step)
        if row.get("force_time") != row.get("committed_time"):
            failures.append(f"force_commit_time_mismatch:{step}")
        if row.get("predictor_time") != row.get("published_time"):
            failures.append(f"predictor_publish_time_mismatch:{step}")
        if row.get("force_consumed") is not True:
            failures.append(f"force_not_consumed:{step}")
        if row.get("old_force_reused") is True:
            failures.append(f"old_force_reused:{step}")
    return {"passed": not failures, "failure_reasons": failures, "record_count": len(records)}


def audit_force_transaction(
    raw_force: Sequence[float],
    *,
    dt: float,
    expected_impulse: float,
    applied_impulse: float,
    absolute_scale: float = 1.0e-9,
) -> dict[str, Any]:
    """Detect missing or repeated dt multiplication in force impulse accounting."""
    if not raw_force:
        raise AuditFailure("empty force history")
    dt = _finite(dt)
    expected = _finite(expected_impulse)
    applied = _finite(applied_impulse)
    scale = max(abs(_finite(absolute_scale)), 1.0e-30)
    reconstructed = sum(_finite(v) for v in raw_force) * dt
    error = abs(reconstructed - applied) / max(abs(expected), scale)
    return {
        "reconstructed_impulse": reconstructed,
        "applied_impulse": applied,
        "expected_impulse": expected,
        "relative_error": error,
        "passed": error <= 1.0e-10,
        "possible_dt_double_application": abs(applied - reconstructed * dt) <= scale,
        "possible_dt_omission": abs(applied - sum(float(v) for v in raw_force)) <= scale,
    }


def audit_checkpoint_initial_state(
    checkpoint: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    """Check that a diagnostic starts from the accepted committed parent state."""
    required = ("case_id", "manifest_sha256", "config_sha256", "time_s", "commit_seq", "slice_ids")
    failures = [key for key in required if key not in checkpoint]
    for key in required:
        if key in checkpoint and checkpoint.get(key) != expected.get(key):
            failures.append(f"mismatch:{key}")
    if checkpoint.get("state") != "committed":
        failures.append("checkpoint_not_committed")
    if len(set(checkpoint.get("slice_ids", []))) != len(checkpoint.get("slice_ids", [])):
        failures.append("duplicate_slice_id")
    return {"passed": not failures, "failure_reasons": failures}


def decide_next_action(*, d1_passed: bool, d2_passed: bool, evidence_ok: bool) -> str:
    """Return a conservative next-state decision without changing any threshold."""
    if not evidence_ok:
        return "failure_identity_or_runtime_blocked"
    if d1_passed and d2_passed:
        return "accepted_timestep_refinement_candidate"
    return "failure_timestep_refinement_not_sufficient"


def recommend_minimal_repair(
    *,
    amplification_detected: bool,
    time_layers_passed: bool,
    force_transaction_passed: bool,
    checkpoint_passed: bool,
) -> dict[str, Any]:
    """Choose the smallest next diagnostic without silently changing physics."""
    if not checkpoint_passed:
        return {"action": "repair_checkpoint_identity", "new_authorization_required": False}
    if not time_layers_passed:
        return {"action": "repair_time_layer_transaction", "new_authorization_required": False}
    if not force_transaction_passed:
        return {"action": "repair_force_application", "new_authorization_required": False}
    if amplification_detected:
        return {
            "action": "freeze_and_run_partitioned_fixed_point_stability_diagnostic",
            "new_authorization_required": True,
            "minimum_scope": [
                "one physical step from the accepted parent checkpoint",
                "fixed-point residual history with no OpenFOAM time advancement between coupling iterations",
                "pre-frozen constant relaxation candidates followed by Aitken only if separately authorized",
                "rollback to the same committed checkpoint for every candidate",
            ],
            "forbidden_shortcuts": [
                "dt/8 continuation",
                "raising Cd or geometry thresholds",
                "reusing a partially committed state",
                "calling a relaxed iteration a physical time step",
            ],
        }
    return {"action": "insufficient_evidence_for_change", "new_authorization_required": True}
