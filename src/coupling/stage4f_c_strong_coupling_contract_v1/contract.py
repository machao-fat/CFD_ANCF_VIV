from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping


SCHEMA = "stage4f-c-strong-coupling-contract-v1-1.0.0"
ALPHA = 0.5
MAX_ITERATIONS = 12
FORCE_RESIDUAL_RELATIVE_MAX = 0.001
FORCE_RESIDUAL_ABSOLUTE_MAX_N = 25.0
CONSECUTIVE_CONVERGED_ITERATIONS = 2
DT_TICK_NS = 625_000
START_TIME_TICK_NS = 1_507_500_000
MAX_ABS_CD = 10.0
MAX_CFL_EXCLUSIVE = 0.8
POSITION_DIFFERENCE_OVER_D_MAX = 0.005
VELOCITY_DIFFERENCE_OVER_U_MAX = 0.01
VIRTUAL_WORK_RELATIVE_ERROR_MAX = 1.0e-12
FORCE_CONVERSION_RELATIVE_ERROR_MAX = 1.0e-10


def _hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_contract(parent_checkpoint_sha256: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", parent_checkpoint_sha256):
        raise ValueError("parent checkpoint SHA-256 must be 64 lowercase hexadecimal characters")
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "parent_checkpoint_sha256": parent_checkpoint_sha256,
        "relaxation_alpha": ALPHA,
        "max_iterations_per_physical_step": MAX_ITERATIONS,
        "force_residual_relative_max": FORCE_RESIDUAL_RELATIVE_MAX,
        "force_residual_absolute_max_N": FORCE_RESIDUAL_ABSOLUTE_MAX_N,
        "force_residual_absolute_scale_N": 25000.0,
        "force_residual_relative_denominator": "max(25000_N,norm_inf(F_relaxed),norm_inf(F_observed))",
        "force_residual_relative_denominator": "max(25000 N, norm_inf(F_observed), norm_inf(F_relaxed))",
        "consecutive_converged_iterations": CONSECUTIVE_CONVERGED_ITERATIONS,
        "dt_tick_ns": DT_TICK_NS,
        "stage_start_time_tick_ns": START_TIME_TICK_NS,
        "max_abs_Cd": MAX_ABS_CD,
        "max_CFL_exclusive": MAX_CFL_EXCLUSIVE,
        "position_difference_over_D_max": POSITION_DIFFERENCE_OVER_D_MAX,
        "velocity_difference_over_U_max": VELOCITY_DIFFERENCE_OVER_U_MAX,
        "virtual_work_relative_error_max": VIRTUAL_WORK_RELATIVE_ERROR_MAX,
        "force_conversion_relative_error_max": FORCE_CONVERSION_RELATIVE_ERROR_MAX,
        "rollback_source": "physical_step_parent_committed_checkpoint",
        "iteration_advances_physical_time": False,
        "commit_policy": "exactly_one_after_convergence",
        "inner_exchange_contract": "0.2.1-explicit-weak-coupling_iteration_0",
        "outer_iteration_identity": "strong_coupling_sidecar_only",
        "failure_policy": "block_current_and_all_later_physical_steps",
    }
    value["contract_sha256"] = _hash(value)
    return value


def validate_contract(value: Mapping[str, Any]) -> None:
    candidate = dict(value)
    supplied_hash = candidate.pop("contract_sha256", None)
    if supplied_hash != _hash(candidate):
        raise ValueError("contract hash mismatch")
    parent = candidate.get("parent_checkpoint_sha256")
    if not isinstance(parent, str):
        raise ValueError("parent checkpoint identity missing")
    if dict(value) != build_contract(parent):
        raise ValueError("frozen strong-coupling contract changed")


def _finite_nonnegative(name: str, value: Any) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return number


def iteration_passes_hard_gates(metrics: Mapping[str, Any]) -> bool:
    residual = _finite_nonnegative("force_residual_relative", metrics["force_residual_relative"])
    residual_abs = _finite_nonnegative("force_residual_absolute_N", metrics["force_residual_absolute_N"])
    cd = _finite_nonnegative("max_abs_Cd", metrics["max_abs_Cd"])
    cfl = _finite_nonnegative("max_CFL", metrics["max_CFL"])
    position = _finite_nonnegative("position_difference_over_D", metrics["position_difference_over_D"])
    velocity = _finite_nonnegative("velocity_difference_over_U", metrics["velocity_difference_over_U"])
    virtual_work = _finite_nonnegative(
        "virtual_work_relative_error", metrics["virtual_work_relative_error"]
    )
    force_conversion = _finite_nonnegative(
        "force_conversion_relative_error", metrics["force_conversion_relative_error"]
    )
    return (
        residual <= FORCE_RESIDUAL_RELATIVE_MAX
        and residual_abs <= FORCE_RESIDUAL_ABSOLUTE_MAX_N
        and cd <= MAX_ABS_CD
        and cfl < MAX_CFL_EXCLUSIVE
        and position <= POSITION_DIFFERENCE_OVER_D_MAX
        and velocity <= VELOCITY_DIFFERENCE_OVER_U_MAX
        and virtual_work <= VIRTUAL_WORK_RELATIVE_ERROR_MAX
        and force_conversion <= FORCE_CONVERSION_RELATIVE_ERROR_MAX
        and bool(metrics.get("all_three_slices_complete"))
        and bool(metrics.get("rollback_verified"))
        and not bool(metrics.get("fatal_detected"))
        and not bool(metrics.get("negative_volume_detected"))
    )


@dataclass
class StrongCouplingLedger:
    """Offline transaction ledger enforcing production fixed-point semantics."""

    parent_checkpoint_sha256: str
    physical_step_index: int
    target_time_s: float
    iterations: list[dict[str, Any]] = field(default_factory=list)
    committed_checkpoint_sha256: str | None = None
    failed: bool = False
    physical_steps_advanced: int = 0

    def __post_init__(self) -> None:
        build_contract(self.parent_checkpoint_sha256)
        if self.physical_step_index < 0 or not math.isfinite(float(self.target_time_s)):
            raise ValueError("invalid physical-step identity")

    def record_iteration(
        self,
        *,
        iteration_index: int,
        rollback_checkpoint_sha256: str,
        physical_step_index: int,
        target_time_s: float,
        metrics: Mapping[str, Any],
    ) -> bool:
        if self.failed:
            raise RuntimeError("failed physical step cannot continue")
        if self.committed_checkpoint_sha256 is not None:
            raise RuntimeError("committed physical step cannot accept iterations")
        if iteration_index != len(self.iterations):
            raise ValueError("iteration sequence is not contiguous")
        if iteration_index >= MAX_ITERATIONS:
            self.failed = True
            raise RuntimeError("strong-coupling iteration limit exceeded")
        if rollback_checkpoint_sha256 != self.parent_checkpoint_sha256:
            self.failed = True
            raise ValueError("iteration rollback identity mismatch")
        if physical_step_index != self.physical_step_index or not math.isclose(
            float(target_time_s), float(self.target_time_s), rel_tol=0.0, abs_tol=1.0e-12
        ):
            self.failed = True
            raise ValueError("iteration advanced or changed physical-step identity")
        hard_passed = iteration_passes_hard_gates(metrics)
        prior_hard_passed = bool(self.iterations and self.iterations[-1]["hard_gates_passed"])
        passed = hard_passed and prior_hard_passed
        self.iterations.append(
            {
                "iteration_index": iteration_index,
                "rollback_checkpoint_sha256": rollback_checkpoint_sha256,
                "physical_step_index": physical_step_index,
                "target_time_s": float(target_time_s),
                "hard_gates_passed": hard_passed,
                "converged": passed,
                "metrics": dict(metrics),
            }
        )
        return passed

    def commit(self, checkpoint_sha256: str) -> None:
        if self.failed:
            raise RuntimeError("failed physical step cannot commit")
        if self.committed_checkpoint_sha256 is not None:
            raise RuntimeError("physical step already has a committed checkpoint")
        if not self.iterations or not self.iterations[-1]["converged"]:
            raise RuntimeError("physical step cannot commit before convergence")
        if not re.fullmatch(r"[0-9a-f]{64}", checkpoint_sha256):
            raise ValueError("invalid committed checkpoint SHA-256")
        self.committed_checkpoint_sha256 = checkpoint_sha256
        self.physical_steps_advanced = 1

    def fail(self, reason: str) -> None:
        if self.committed_checkpoint_sha256 is not None:
            raise RuntimeError("cannot fail an already committed physical step")
        if not reason.strip():
            raise ValueError("failure reason is required")
        self.failed = True

    @property
    def next_physical_step_authorized(self) -> bool:
        return (
            not self.failed
            and self.committed_checkpoint_sha256 is not None
            and self.physical_steps_advanced == 1
        )
