"""Fail-closed Newton-response evidence for the protected C++ worker wire."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Mapping, Sequence


class NewtonEvidenceError(ValueError):
    pass


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise NewtonEvidenceError(f"{name} is missing or non-finite")
    return float(value)


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise NewtonEvidenceError(f"{name} is invalid")
    return value


def _state(value: Mapping[str, Sequence[object]]) -> tuple[dict[str, list[float]], str]:
    fields: dict[str, list[float]] = {}
    width: int | None = None
    for name in ("q", "qdot", "qddot"):
        row = value.get(name)
        if isinstance(row, (str, bytes)) or not isinstance(row, Sequence) or not row:
            raise NewtonEvidenceError(f"{name} is missing")
        converted = [_finite(item, f"{name}[]") for item in row]
        if width is None:
            width = len(converted)
        elif len(converted) != width:
            raise NewtonEvidenceError("ANCF state dimensions are inconsistent")
        fields[name] = converted
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return fields, hashlib.sha256(payload).hexdigest()


def make_record(*, run_id: str, case_id: str, global_step: int, time_s: float, integer_tick: int,
                phase: str, transport_sequence: int, correction_sequence: int | None,
                diagnostics: Mapping[str, object], state: Mapping[str, Sequence[object]],
                max_newton_iterations: int) -> dict[str, object]:
    """Create one independently auditable wire-response record.

    The current v1 wire has iterations and final residual, but no initial
    residual.  It also has no explicit converged bit: a zero return is a
    sound derived convergence fact because the kernel throws on nonconvergence.
    """
    if phase not in {"prediction", "correction"}:
        raise NewtonEvidenceError("phase is invalid")
    if not isinstance(run_id, str) or not run_id or not isinstance(case_id, str) or not case_id:
        raise NewtonEvidenceError("run/case identity is missing")
    step = _integer(global_step, "global_step", minimum=1)
    time_value = _finite(time_s, "time_s")
    if time_value <= 0.0:
        raise NewtonEvidenceError("time_s is not positive")
    tick = _integer(integer_tick, "integer_tick", minimum=1)
    if abs(time_value * 1.0e9 - tick) > 0.5:
        raise NewtonEvidenceError("time/tick identity is inconsistent")
    sequence = _integer(transport_sequence, "transport_sequence", minimum=1)
    expected_sequence = 2 * step - 1 if phase == "prediction" else 2 * step
    if sequence != expected_sequence:
        raise NewtonEvidenceError("phase/transport sequence is inconsistent")
    if phase == "correction":
        if correction_sequence != sequence:
            raise NewtonEvidenceError("correction sequence is inconsistent")
    elif correction_sequence is not None:
        raise NewtonEvidenceError("prediction must not carry correction sequence")
    iterations = _integer(diagnostics.get("newton_iterations"), "newton_iterations", minimum=1)
    if iterations > _integer(max_newton_iterations, "max_newton_iterations", minimum=1):
        raise NewtonEvidenceError("newton iterations exceed frozen maximum")
    residual = _finite(diagnostics.get("newton_final_residual"), "newton_final_residual")
    if residual < 0.0:
        raise NewtonEvidenceError("newton final residual is negative")
    if diagnostics.get("newton_converged") is not True:
        raise NewtonEvidenceError("kernel convergence evidence is missing")
    if diagnostics.get("finite_value_audit") is not True:
        raise NewtonEvidenceError("finite-state evidence is missing")
    if diagnostics.get("worker_return_code") != 0:
        raise NewtonEvidenceError("worker return code is nonzero")
    state_value, state_sha256 = _state(state)
    return {
        "schema_version": "ancf-newton-evidence-v1",
        "run_id": run_id,
        "case_id": case_id,
        "global_step": step,
        "time_s": time_value,
        "integer_tick": tick,
        "phase": phase,
        "transport_sequence": sequence,
        "correction_sequence": correction_sequence,
        "newton_iterations": iterations,
        "max_newton_iterations": _integer(max_newton_iterations, "max_newton_iterations", minimum=1),
        "newton_final_residual": residual,
        "newton_converged": True,
        "newton_converged_semantics": "derived_from_zero_return_code; kernel throws when Newton does not converge",
        "finite_state": True,
        "worker_return_code": 0,
        "state": state_value,
        "state_sha256": state_sha256,
    }


def validate_records(records: Sequence[Mapping[str, object]], *, expected_steps: int) -> dict[str, object]:
    expected = _integer(expected_steps, "expected_steps", minimum=1)
    if len(records) != 2 * expected:
        raise NewtonEvidenceError("Newton record count does not equal prediction/correction count")
    identities: set[tuple[int, str]] = set()
    run_case: tuple[str, str] | None = None
    for item in records:
        state = item.get("state")
        if not isinstance(state, Mapping):
            raise NewtonEvidenceError("state link is missing")
        rebuilt = make_record(run_id=item.get("run_id"), case_id=item.get("case_id"),
            global_step=item.get("global_step"), time_s=item.get("time_s"), integer_tick=item.get("integer_tick"),
            phase=item.get("phase"), transport_sequence=item.get("transport_sequence"),
            correction_sequence=item.get("correction_sequence"), diagnostics={
                "newton_iterations": item.get("newton_iterations"), "newton_final_residual": item.get("newton_final_residual"),
                "newton_converged": item.get("newton_converged"), "finite_value_audit": item.get("finite_state"),
                "worker_return_code": item.get("worker_return_code"),
            }, state=state, max_newton_iterations=item.get("max_newton_iterations"))
        if rebuilt["state_sha256"] != item.get("state_sha256"):
            raise NewtonEvidenceError("state identity hash mismatch")
        identity = (int(rebuilt["global_step"]), str(rebuilt["phase"]))
        if identity in identities:
            raise NewtonEvidenceError("duplicate Newton identity")
        identities.add(identity)
        current = (str(rebuilt["run_id"]), str(rebuilt["case_id"]))
        if run_case is None:
            run_case = current
        elif run_case != current:
            raise NewtonEvidenceError("run/case identity is discontinuous")
    expected_identities = {(step, phase) for step in range(1, expected + 1) for phase in ("prediction", "correction")}
    if identities != expected_identities:
        raise NewtonEvidenceError("Newton IDs/ticks are not continuous")
    return {"status": "pass", "record_count": len(records), "prediction_count": expected, "correction_count": expected,
            "run_id": run_case[0] if run_case else None, "case_id": run_case[1] if run_case else None}
