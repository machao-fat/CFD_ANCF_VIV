"""Pure evidence validation for the frozen Stage 4F-C restart gate.

This module has no filesystem, process, MATLAB, or OpenFOAM dependencies.
Callers supply already-collected immutable evidence dictionaries.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .contract import (
    CFD_FIELDS,
    EXTENSION_STEPS,
    FIRST_LEG_STEPS,
    RESTART_IDENTITY_STEPS,
    RESTART_LEG_STEPS,
    STRUCTURE_RELATIVE_TOLERANCE,
    TOTAL_AUTHORIZED_STEPS,
    is_sha256,
    validate_contract,
)


class RestartExtendedAuditError(RuntimeError):
    """Restart evidence is incomplete, discontinuous, or non-identical."""


def _finite_tree(value: object, *, context: str) -> list[float]:
    if isinstance(value, Mapping):
        raise RestartExtendedAuditError(f"{context} must be an array of numeric values")
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise RestartExtendedAuditError(f"{context} must be an array of numeric values")
    output: list[float] = []
    for item in value:
        if isinstance(item, (str, bytes)) or not isinstance(item, Sequence):
            try:
                numeric = float(item)
            except (TypeError, ValueError) as exc:
                raise RestartExtendedAuditError(f"{context} contains a non-numeric value") from exc
            if not math.isfinite(numeric):
                raise RestartExtendedAuditError(f"{context} contains NaN/Inf")
            output.append(numeric)
        else:
            output.extend(_finite_tree(item, context=context))
    if not output:
        raise RestartExtendedAuditError(f"{context} must not be empty")
    return output


def _record(value: object, *, expected_step: int, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or value.get("physical_step") != expected_step:
        raise RestartExtendedAuditError(f"{label} physical-step identity is invalid")
    for key in ("predictor", "cfd_fields", "observed_forces_N", "checkpoint"):
        if key not in value:
            raise RestartExtendedAuditError(f"{label} is missing {key}")
    return value


def _checkpoint(record: Mapping[str, Any], *, label: str) -> tuple[str, str]:
    value = record["checkpoint"]
    if not isinstance(value, Mapping):
        raise RestartExtendedAuditError(f"{label} checkpoint is invalid")
    parent, current = value.get("parent_checkpoint_sha256"), value.get("checkpoint_sha256")
    if not is_sha256(parent) or not is_sha256(current):
        raise RestartExtendedAuditError(f"{label} checkpoint hashes are invalid")
    return parent, current


def _verify_lineage(records: Sequence[Mapping[str, Any]], *, original_parent: str, label: str) -> list[str]:
    previous = original_parent
    checkpoints: list[str] = []
    for offset, record in enumerate(records):
        parent, current = _checkpoint(record, label=f"{label}[{offset}]")
        if parent != previous:
            raise RestartExtendedAuditError(f"{label}[{offset}] checkpoint lineage is discontinuous")
        previous = current
        checkpoints.append(current)
    return checkpoints


def _compare_structure(reference: Mapping[str, Any], candidate: Mapping[str, Any], *, step: int) -> dict[str, float]:
    reference_predictor, candidate_predictor = reference["predictor"], candidate["predictor"]
    if not isinstance(reference_predictor, Mapping) or not isinstance(candidate_predictor, Mapping):
        raise RestartExtendedAuditError(f"step {step} predictor is invalid")
    result: dict[str, float] = {}
    for component in ("q", "qdot", "qddot"):
        left = _finite_tree(reference_predictor.get(component), context=f"step {step} reference {component}")
        right = _finite_tree(candidate_predictor.get(component), context=f"step {step} restart {component}")
        if len(left) != len(right):
            raise RestartExtendedAuditError(f"step {step} {component} length differs")
        difference = max(abs(a - b) for a, b in zip(left, right))
        scale = max(1.0, max(abs(value) for value in left))
        relative = difference / scale
        if relative > STRUCTURE_RELATIVE_TOLERANCE:
            raise RestartExtendedAuditError(f"step {step} {component} relative difference exceeds tolerance")
        result[component] = relative
    return result


def _strict_values(value: object, *, context: str) -> tuple[float, ...]:
    return tuple(_finite_tree(value, context=context))


def _force_matrix(value: object, *, context: str) -> tuple[tuple[float, float, float], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        raise RestartExtendedAuditError(f"{context} must be a 3 x 3 force matrix")
    result: list[tuple[float, float, float]] = []
    for row in value:
        if isinstance(row, (str, bytes)) or not isinstance(row, Sequence) or len(row) != 3:
            raise RestartExtendedAuditError(f"{context} must be a 3 x 3 force matrix")
        values = _strict_values(row, context=context)
        result.append((values[0], values[1], values[2]))
    return tuple(result)


def _compare_cfd(reference: Mapping[str, Any], candidate: Mapping[str, Any], *, step: int) -> dict[str, str]:
    left_fields, right_fields = reference["cfd_fields"], candidate["cfd_fields"]
    if not isinstance(left_fields, Mapping) or not isinstance(right_fields, Mapping):
        raise RestartExtendedAuditError(f"step {step} CFD fields are invalid")
    methods: dict[str, str] = {}
    for field in CFD_FIELDS:
        left, right = left_fields.get(field), right_fields.get(field)
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            raise RestartExtendedAuditError(f"step {step} CFD field {field} is missing")
        left_hash, right_hash = left.get("sha256"), right.get("sha256")
        if is_sha256(left_hash) and is_sha256(right_hash) and left_hash == right_hash:
            methods[field] = "sha256"
            continue
        if "parsed_values" not in left or "parsed_values" not in right:
            raise RestartExtendedAuditError(f"step {step} CFD field {field} has no identical hash or parsed values")
        if _strict_values(left["parsed_values"], context=f"step {step} reference {field}") != _strict_values(
            right["parsed_values"], context=f"step {step} restart {field}"
        ):
            raise RestartExtendedAuditError(f"step {step} CFD field {field} parsed values differ")
        methods[field] = "parsed_values"
    return methods


def _compare_observed_forces(reference: Mapping[str, Any], candidate: Mapping[str, Any], *, step: int) -> None:
    left = _force_matrix(reference["observed_forces_N"], context=f"step {step} reference forces")
    right = _force_matrix(candidate["observed_forces_N"], context=f"step {step} restart forces")
    if left != right:
        raise RestartExtendedAuditError(f"step {step} observed CFD forces differ")


def _verify_shutdown(value: object, *, expected_checkpoint: str) -> None:
    if not isinstance(value, Mapping):
        raise RestartExtendedAuditError("restart shutdown audit is missing")
    if value.get("phase") != "after_first_leg_before_restart":
        raise RestartExtendedAuditError("restart shutdown phase is invalid")
    if value.get("source_checkpoint_sha256") != expected_checkpoint:
        raise RestartExtendedAuditError("restart shutdown did not use the first-leg checkpoint")
    for key in ("owned_processes_started", "owned_processes_closed", "owned_processes_residual", "nonzero_return_codes"):
        if not isinstance(value.get(key), int) or value[key] < 0:
            raise RestartExtendedAuditError(f"restart shutdown audit {key} is invalid")
    if value["owned_processes_started"] < 1 or value["owned_processes_closed"] != value["owned_processes_started"]:
        raise RestartExtendedAuditError("owned processes were not fully closed before restart")
    if value["owned_processes_residual"] != 0 or value["nonzero_return_codes"] != 0:
        raise RestartExtendedAuditError("restart shutdown has residual processes or nonzero returns")


def audit_restart_identity(
    contract: Mapping[str, Any],
    *,
    continuous_steps: Sequence[Mapping[str, Any]],
    first_leg_steps: Sequence[Mapping[str, Any]],
    restart_leg_steps: Sequence[Mapping[str, Any]],
    shutdown_audit: Mapping[str, Any],
) -> dict[str, Any]:
    """Audit the only prerequisite that may authorize the seven-step extension."""
    validate_contract(contract)
    if len(continuous_steps) != RESTART_IDENTITY_STEPS:
        raise RestartExtendedAuditError("continuous reference must contain exactly three physical steps")
    if len(first_leg_steps) != FIRST_LEG_STEPS or len(restart_leg_steps) != RESTART_LEG_STEPS:
        raise RestartExtendedAuditError("restart protocol must be one first-leg step followed by two restart steps")
    original_parent = str(contract["original_parent_checkpoint_sha256"])
    continuous = [_record(row, expected_step=index, label="continuous") for index, row in enumerate(continuous_steps)]
    first_leg = [_record(first_leg_steps[0], expected_step=0, label="first_leg")]
    restart = [_record(row, expected_step=index + 1, label="restart_leg") for index, row in enumerate(restart_leg_steps)]
    _verify_lineage(continuous, original_parent=original_parent, label="continuous")
    first_checkpoints = _verify_lineage(first_leg, original_parent=original_parent, label="first_leg")
    restart_checkpoints = _verify_lineage(restart, original_parent=first_checkpoints[-1], label="restart_leg")
    _verify_shutdown(shutdown_audit, expected_checkpoint=first_checkpoints[-1])

    audit_steps: list[dict[str, Any]] = []
    split_records = first_leg + restart
    for step, (reference, candidate) in enumerate(zip(continuous, split_records)):
        audit_steps.append({
            "physical_step": step,
            "structure_relative_difference": _compare_structure(reference, candidate, step=step),
            "cfd_comparison": _compare_cfd(reference, candidate, step=step),
            "observed_forces_identical": True,
            "continuous_checkpoint_parent_sha256": _checkpoint(reference, label=f"continuous[{step}]")[0],
            "restart_checkpoint_parent_sha256": _checkpoint(candidate, label=f"restart[{step}]")[0],
        })
        _compare_observed_forces(reference, candidate, step=step)
    return {
        "schema": "stage4f-c-restart-extended-audit-v1-1.0.0",
        "status": "passed",
        "contract_sha256": contract["contract_sha256"],
        "restart_identity_steps": RESTART_IDENTITY_STEPS,
        "restart_checkpoint_sha256": first_checkpoints[-1],
        "restart_final_checkpoint_sha256": restart_checkpoints[-1],
        "steps": audit_steps,
    }


def authorize_extended_transient(contract: Mapping[str, Any], restart_audit: Mapping[str, Any]) -> dict[str, Any]:
    """Return a bounded plan only after a passing, matching restart identity audit."""
    validate_contract(contract)
    if restart_audit.get("status") != "passed" or restart_audit.get("contract_sha256") != contract.get("contract_sha256"):
        raise RestartExtendedAuditError("extended transient is not authorized before a matching restart identity pass")
    return {
        "status": "authorized",
        "execution_mode": "authorization_only_no_execution",
        "restart_from_checkpoint_sha256": restart_audit["restart_final_checkpoint_sha256"],
        "additional_physical_steps": EXTENSION_STEPS,
        "total_physical_steps": TOTAL_AUTHORIZED_STEPS,
        "end_time_s": contract["authorized_end_time_s"],
        "relaxation_alpha": contract["relaxation_alpha"],
        "max_iterations_per_physical_step": contract["max_iterations_per_physical_step"],
        "final_max_abs_Cd": contract["final_max_abs_Cd"],
        "hard_gates": list(contract["hard_gates"]),
    }
