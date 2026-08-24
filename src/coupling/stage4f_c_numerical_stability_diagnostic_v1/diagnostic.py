"""不改变求解器的早期显式弱耦合稳定性诊断指标。"""
from __future__ import annotations
import math
from typing import Any, Iterable, Mapping

class StabilityDiagnosticError(ValueError): pass

def _finite(value: Any, name: str) -> float:
    try: result = float(value)
    except (TypeError, ValueError) as exc: raise StabilityDiagnosticError(f"{name} non-numeric") from exc
    if not math.isfinite(result): raise StabilityDiagnosticError(f"{name} non-finite")
    return result

def diagnose(rows: Iterable[Mapping[str, Any]], *, cd_limit: float = 10.0, velocity_limit: float = 0.01) -> dict[str, Any]:
    data = list(rows)
    if not data: raise StabilityDiagnosticError("empty diagnostic sequence")
    envelope = []; alternating = []; cd_failures = []; velocity_failures = []
    previous_sign = None
    for index, row in enumerate(data):
        cd = abs(_finite(row.get("max_abs_Cd"), "max_abs_Cd"))
        velocity = abs(_finite(row.get("max_velocity_consistency_error"), "max_velocity_consistency_error"))
        cfl = _finite(row.get("max_cfl"), "max_cfl")
        envelope.append(cd)
        if cd > cd_limit: cd_failures.append(index)
        if velocity > velocity_limit: velocity_failures.append(index)
        sign = math.copysign(1.0, float(row.get("signed_force", 0.0)))
        if previous_sign is not None and sign != previous_sign: alternating.append(index)
        previous_sign = sign
        if cfl >= 0.8: raise StabilityDiagnosticError(f"CFL hard gate exceeded at index {index}")
    growth = [envelope[i] / max(envelope[i-1], 1.0e-300) for i in range(1, len(envelope))]
    return {"sample_count": len(data), "cd_envelope": envelope, "successive_cd_growth": growth,
            "alternating_force_indices": alternating, "cd_failures": cd_failures,
            "velocity_failures": velocity_failures,
            "alternating_growth_detected": bool(alternating and any(g > 1.0 for g in growth)),
            "first_hard_failure_index": min(cd_failures + velocity_failures) if cd_failures or velocity_failures else None,
            "classification": "early_explicit_weak_coupling_amplification" if (cd_failures or velocity_failures) else "no_failure_in_supplied_window"}
