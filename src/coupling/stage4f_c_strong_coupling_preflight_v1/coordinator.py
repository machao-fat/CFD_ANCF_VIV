"""Pure-Python transaction coordinator for the strong-coupling sidecar.

This module deliberately knows nothing about MATLAB, OpenFOAM, or the
production checkpoint manager.  A real adapter supplies trial observations
and one explicit promotion callback.  Keeping that boundary narrow makes it
possible to prove that fixed-point trials cannot masquerade as committed
physical steps before any expensive process is launched.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..stage4f_c_strong_coupling_contract_v1.contract import (
    ALPHA,
    DT_TICK_NS,
    FORCE_RESIDUAL_ABSOLUTE_MAX_N,
    FORCE_RESIDUAL_RELATIVE_MAX,
    MAX_ITERATIONS,
    START_TIME_TICK_NS,
    StrongCouplingLedger,
    iteration_passes_hard_gates,
)


FORCE_RESIDUAL_RELATIVE_SCALE_N = 25_000.0
SLICE_COUNT = 3


class StrongCouplingProtocolError(RuntimeError):
    """Raised when a trial violates the sidecar transaction contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_force(value: Sequence[Sequence[float]]) -> list[list[float]]:
    if len(value) != SLICE_COUNT:
        raise StrongCouplingProtocolError("strong-coupling force must contain exactly three slices")
    copied: list[list[float]] = []
    for row in value:
        if len(row) != 3:
            raise StrongCouplingProtocolError("each slice force must have three Cartesian components")
        candidate = [float(component) for component in row]
        if not all(math.isfinite(component) for component in candidate):
            raise StrongCouplingProtocolError("force contains a non-finite component")
        copied.append(candidate)
    return copied


def _max_force_difference(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> float:
    return max(abs(left - right) for left_row, right_row in zip(a, b) for left, right in zip(left_row, right_row))


def _max_force_norm(value: Sequence[Sequence[float]]) -> float:
    return max(abs(component) for row in value for component in row)


def _relax(previous: Sequence[Sequence[float]], observed: Sequence[Sequence[float]]) -> list[list[float]]:
    return [[(1.0 - ALPHA) * old + ALPHA * new for old, new in zip(old_row, new_row)] for old_row, new_row in zip(previous, observed)]


def _same_force(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> bool:
    return all(left == right for left_row, right_row in zip(a, b) for left, right in zip(left_row, right_row))


def _passes_safety_gates(metrics: Mapping[str, Any]) -> bool:
    """Apply all original numerical gates without treating early residuals as fatal.

    The fixed-point residual is expected to be large before convergence.  CFL,
    force scaling, geometry, virtual-work, conversion, slice completeness,
    rollback, FATAL and negative-volume checks are safety gates on *every*
    candidate; only the two residual limits are convergence gates.
    """
    candidate = dict(metrics)
    candidate["force_residual_relative"] = 0.0
    candidate["force_residual_absolute_N"] = 0.0
    return iteration_passes_hard_gates(candidate)


@dataclass(frozen=True)
class CheckpointIdentity:
    """Immutable identity of the rollback source for a physical step."""

    path: Path
    sha256: str
    source_physical_step: int

    def verify(self) -> None:
        if self.source_physical_step < 0:
            raise StrongCouplingProtocolError("source physical step must be nonnegative")
        if not self.path.is_file():
            raise StrongCouplingProtocolError("restart source checkpoint path is missing")
        actual = sha256_file(self.path)
        if actual != self.sha256:
            raise StrongCouplingProtocolError("restart source checkpoint SHA-256 mismatch")


@dataclass(frozen=True)
class TrialRequest:
    physical_step: int
    strong_iteration: int
    inner_iteration: int
    current_tick_ns: int
    target_tick_ns: int
    parent: CheckpointIdentity
    relaxed_force_N: tuple[tuple[float, float, float], ...]


@dataclass(frozen=True)
class TrialObservation:
    """Evidence returned by a single, rollback-only candidate execution."""

    rollback_checkpoint_sha256: str
    rollback_source_path: Path
    physical_step: int
    strong_iteration: int
    inner_iteration: int
    current_tick_ns: int
    target_tick_ns: int
    observed_force_N: Sequence[Sequence[float]]
    metrics: Mapping[str, Any]
    trial_checkpoint_committed: bool = False
    partial_cfd_failure: bool = False


@dataclass(frozen=True)
class PromotionRequest:
    physical_step: int
    target_tick_ns: int
    parent: CheckpointIdentity
    selected_strong_iteration: int
    observed_force_N: tuple[tuple[float, float, float], ...]
    relaxed_force_N: tuple[tuple[float, float, float], ...]
    trial_evidence: TrialObservation


@dataclass(frozen=True)
class PromotionReceipt:
    checkpoint: CheckpointIdentity
    physical_step: int
    target_tick_ns: int
    selected_strong_iteration: int
    stored_observed_force_N: Sequence[Sequence[float]]


TrialExecutor = Callable[[TrialRequest], TrialObservation]
Promoter = Callable[[PromotionRequest], PromotionReceipt]


@dataclass
class PhysicalStepResult:
    physical_step: int
    current_tick_ns: int
    target_tick_ns: int
    parent_checkpoint_sha256: str
    iterations: list[dict[str, Any]] = field(default_factory=list)
    status: str = "running"
    failure_reason: str | None = None
    promotion: PromotionReceipt | None = None


class OuterFixedPointCoordinator:
    """Enforces rollback-only trials and exactly one promotion per step."""

    def __init__(self, *, initial_parent: CheckpointIdentity, initial_force_N: Sequence[Sequence[float]]) -> None:
        initial_parent.verify()
        self._parent = initial_parent
        self._force = _copy_force(initial_force_N)
        self._next_physical_step = 0
        self._blocked = False
        self.results: list[PhysicalStepResult] = []

    @property
    def blocked(self) -> bool:
        return self._blocked

    @property
    def parent(self) -> CheckpointIdentity:
        return self._parent

    @property
    def next_physical_step(self) -> int:
        return self._next_physical_step

    def run_three_step_preflight(self, executor: TrialExecutor, promoter: Promoter) -> list[PhysicalStepResult]:
        for physical_step in range(3):
            result = self.run_physical_step(physical_step, executor, promoter)
            if result.status != "committed":
                break
        return list(self.results)

    def run_physical_step(self, physical_step: int, executor: TrialExecutor, promoter: Promoter) -> PhysicalStepResult:
        if self._blocked:
            raise StrongCouplingProtocolError("a failed physical step blocks all later physical steps")
        if physical_step != self._next_physical_step:
            raise StrongCouplingProtocolError("physical steps must be stage-local and contiguous")
        current_tick = START_TIME_TICK_NS + physical_step * DT_TICK_NS
        target_tick = current_tick + DT_TICK_NS
        parent = self._parent
        parent.verify()
        ledger = StrongCouplingLedger(parent.sha256, physical_step, target_tick / 1_000_000_000.0)
        result = PhysicalStepResult(physical_step, current_tick, target_tick, parent.sha256)
        self.results.append(result)
        relaxed = _copy_force(self._force)

        for iteration in range(MAX_ITERATIONS):
            request = TrialRequest(
                physical_step=physical_step,
                strong_iteration=iteration,
                inner_iteration=0,
                current_tick_ns=current_tick,
                target_tick_ns=target_tick,
                parent=parent,
                relaxed_force_N=tuple(tuple(row) for row in relaxed),
            )
            try:
                observation = executor(request)
                observed = self._validate_trial(request, observation)
                residual_abs = _max_force_difference(observed, relaxed)
                residual_rel = residual_abs / max(FORCE_RESIDUAL_RELATIVE_SCALE_N, _max_force_norm(observed), _max_force_norm(relaxed))
                metrics = dict(observation.metrics)
                supplied_abs = metrics.get("force_residual_absolute_N")
                supplied_rel = metrics.get("force_residual_relative")
                if supplied_abs is not None and not math.isclose(float(supplied_abs), residual_abs, rel_tol=0.0, abs_tol=1.0e-12):
                    raise StrongCouplingProtocolError("trial reported a force residual different from the frozen calculation")
                if supplied_rel is not None and not math.isclose(float(supplied_rel), residual_rel, rel_tol=0.0, abs_tol=1.0e-15):
                    raise StrongCouplingProtocolError("trial reported a relative residual different from the frozen calculation")
                metrics["force_residual_absolute_N"] = residual_abs
                metrics["force_residual_relative"] = residual_rel
                if not _passes_safety_gates(metrics):
                    raise StrongCouplingProtocolError("candidate violated a frozen numerical safety gate")
                converged = ledger.record_iteration(
                    iteration_index=iteration,
                    rollback_checkpoint_sha256=observation.rollback_checkpoint_sha256,
                    physical_step_index=physical_step,
                    target_time_s=target_tick / 1_000_000_000.0,
                    metrics=metrics,
                )
                result.iterations.append({
                    "strong_iteration": iteration,
                    "inner_iteration": 0,
                    "parent_checkpoint_sha256": parent.sha256,
                    "observed_force_N": observed,
                    "relaxed_force_N": _copy_force(relaxed),
                    "force_residual_absolute_N": residual_abs,
                    "force_residual_relative": residual_rel,
                    "hard_gates_passed": ledger.iterations[-1]["hard_gates_passed"],
                    "converged": converged,
                })
                if not converged:
                    relaxed = _relax(relaxed, observed)
                    continue
                receipt = promoter(PromotionRequest(
                    physical_step=physical_step,
                    target_tick_ns=target_tick,
                    parent=parent,
                    selected_strong_iteration=iteration,
                    observed_force_N=tuple(tuple(row) for row in observed),
                    relaxed_force_N=tuple(tuple(row) for row in relaxed),
                    trial_evidence=observation,
                ))
                self._validate_promotion(receipt, request, observed)
                receipt.checkpoint.verify()
                ledger.commit(receipt.checkpoint.sha256)
                result.status = "committed"
                result.promotion = receipt
                self._parent = receipt.checkpoint
                self._force = observed
                self._next_physical_step += 1
                return result
            except Exception as exc:
                ledger.fail(str(exc))
                result.status = "failed"
                result.failure_reason = f"{type(exc).__name__}: {exc}"
                self._blocked = True
                return result

        ledger.fail("strong-coupling iteration limit reached without convergence")
        result.status = "failed"
        result.failure_reason = "strong-coupling iteration limit reached without convergence"
        self._blocked = True
        return result

    def _validate_trial(self, request: TrialRequest, observation: TrialObservation) -> list[list[float]]:
        if observation.trial_checkpoint_committed:
            raise StrongCouplingProtocolError("candidate iteration committed a checkpoint before promotion")
        if observation.partial_cfd_failure:
            raise StrongCouplingProtocolError("candidate iteration has a partial CFD failure")
        if observation.rollback_checkpoint_sha256 != request.parent.sha256 or Path(observation.rollback_source_path) != request.parent.path:
            raise StrongCouplingProtocolError("candidate rollback source does not match the physical-step parent")
        identity = (observation.physical_step, observation.strong_iteration, observation.inner_iteration, observation.current_tick_ns, observation.target_tick_ns)
        expected = (request.physical_step, request.strong_iteration, 0, request.current_tick_ns, request.target_tick_ns)
        if identity != expected:
            raise StrongCouplingProtocolError("candidate physical step, strong iteration, or time tick is incorrect")
        return _copy_force(observation.observed_force_N)

    def _validate_promotion(self, receipt: PromotionReceipt, request: TrialRequest, observed: Sequence[Sequence[float]]) -> None:
        if receipt.physical_step != request.physical_step or receipt.target_tick_ns != request.target_tick_ns:
            raise StrongCouplingProtocolError("promotion physical-step identity is incorrect")
        if receipt.selected_strong_iteration != request.strong_iteration:
            raise StrongCouplingProtocolError("promotion selected the wrong candidate iteration")
        if receipt.checkpoint.source_physical_step != request.physical_step:
            raise StrongCouplingProtocolError("promoted checkpoint records an incorrect source physical step")
        stored = _copy_force(receipt.stored_observed_force_N)
        if not _same_force(stored, observed):
            raise StrongCouplingProtocolError("promotion stored relaxed force instead of observed CFD force")
