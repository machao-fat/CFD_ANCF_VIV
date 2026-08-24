"""Pure offline ledger for Stage 4F-C predictor-consistent strong coupling.

The module contains no process, filesystem, MATLAB, or OpenFOAM execution.
Adapters supply immutable candidate evidence and a single promotion receipt.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .contract import (
    ALPHA,
    CONSECUTIVE_CONVERGED_ITERATIONS,
    FORCE_CONVERSION_RELATIVE_ERROR_MAX,
    FORCE_RESIDUAL_ABSOLUTE_MAX_N,
    FORCE_RESIDUAL_RELATIVE_MAX,
    FORCE_RESIDUAL_RELATIVE_SCALE_N,
    MAX_ABS_CD,
    MAX_CFL_EXCLUSIVE,
    MAX_ITERATIONS,
    POSITION_DIFFERENCE_OVER_D_MAX,
    VELOCITY_DIFFERENCE_OVER_U_MAX,
    VIRTUAL_WORK_RELATIVE_ERROR_MAX,
    canonical_sha256,
    is_sha256,
)


SLICE_COUNT = 3


class PredictorConsistentProtocolError(RuntimeError):
    """A candidate or promotion breached the frozen offline transaction contract."""


def _force(value: Sequence[Sequence[float]]) -> tuple[tuple[float, float, float], ...]:
    if len(value) != SLICE_COUNT:
        raise PredictorConsistentProtocolError("force must contain exactly three slices")
    rows: list[tuple[float, float, float]] = []
    for row in value:
        if len(row) != 3:
            raise PredictorConsistentProtocolError("each slice force must have three Cartesian components")
        candidate = tuple(float(component) for component in row)
        if not all(math.isfinite(component) for component in candidate):
            raise PredictorConsistentProtocolError("force contains a non-finite component")
        rows.append(candidate)
    return tuple(rows)


def _same_force(left: Sequence[Sequence[float]], right: Sequence[Sequence[float]]) -> bool:
    return tuple(tuple(row) for row in left) == tuple(tuple(row) for row in right)


def _relax(previous: Sequence[Sequence[float]], observed: Sequence[Sequence[float]]) -> tuple[tuple[float, float, float], ...]:
    return tuple(tuple((1.0 - ALPHA) * old + ALPHA * new for old, new in zip(old_row, new_row)) for old_row, new_row in zip(previous, observed))


def _residual(observed: Sequence[Sequence[float]], relaxed: Sequence[Sequence[float]]) -> tuple[float, float]:
    absolute = max(abs(a - b) for left, right in zip(observed, relaxed) for a, b in zip(left, right))
    norm = max(abs(component) for row in tuple(observed) + tuple(relaxed) for component in row)
    return absolute, absolute / max(FORCE_RESIDUAL_RELATIVE_SCALE_N, norm)


def _finite_metric(metrics: Mapping[str, Any], name: str) -> float:
    try:
        value = float(metrics[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise PredictorConsistentProtocolError(f"candidate metric {name} is missing or invalid") from exc
    if not math.isfinite(value):
        raise PredictorConsistentProtocolError(f"candidate metric {name} is non-finite")
    return value


def _validate_safety(metrics: Mapping[str, Any]) -> float:
    """Return finite Cd; only the listed physical/numerical faults hard-stop a trial."""
    cd = _finite_metric(metrics, "max_abs_Cd")
    if cd < 0.0:
        raise PredictorConsistentProtocolError("candidate metric max_abs_Cd is negative")
    cfl = _finite_metric(metrics, "max_CFL")
    virtual_work = _finite_metric(metrics, "virtual_work_relative_error")
    conversion = _finite_metric(metrics, "force_conversion_relative_error")
    position = _finite_metric(metrics, "position_difference_over_D")
    velocity = _finite_metric(metrics, "velocity_difference_over_U")
    if cfl < 0.0 or cfl >= MAX_CFL_EXCLUSIVE:
        raise PredictorConsistentProtocolError("candidate CFL safety gate failed")
    if virtual_work < 0.0 or virtual_work > VIRTUAL_WORK_RELATIVE_ERROR_MAX:
        raise PredictorConsistentProtocolError("candidate virtual-work safety gate failed")
    if conversion < 0.0 or conversion > FORCE_CONVERSION_RELATIVE_ERROR_MAX:
        raise PredictorConsistentProtocolError("candidate force-conversion safety gate failed")
    if position < 0.0 or position > POSITION_DIFFERENCE_OVER_D_MAX:
        raise PredictorConsistentProtocolError("candidate position geometry safety gate failed")
    if velocity < 0.0 or velocity > VELOCITY_DIFFERENCE_OVER_U_MAX:
        raise PredictorConsistentProtocolError("candidate velocity geometry safety gate failed")
    if bool(metrics.get("fatal_detected")):
        raise PredictorConsistentProtocolError("candidate reported FATAL")
    if bool(metrics.get("negative_volume_detected")):
        raise PredictorConsistentProtocolError("candidate reported negative volume")
    if not bool(metrics.get("all_slices_complete")):
        raise PredictorConsistentProtocolError("candidate CFD slices are incomplete")
    if not bool(metrics.get("geometry_valid")):
        raise PredictorConsistentProtocolError("candidate geometry is invalid")
    return cd


@dataclass(frozen=True)
class PredictorState:
    """ANCF candidate state deterministically associated with relaxed CFD force."""

    relaxed_force_N: tuple[tuple[float, float, float], ...]
    ancf_state: Mapping[str, Any]
    relaxed_force_sha256: str
    predictor_state_sha256: str

    @classmethod
    def build(cls, relaxed_force_N: Sequence[Sequence[float]], ancf_state: Mapping[str, Any]) -> "PredictorState":
        force = _force(relaxed_force_N)
        force_hash = canonical_sha256(force)
        state = dict(ancf_state)
        return cls(force, state, force_hash, canonical_sha256({"relaxed_force_sha256": force_hash, "ancf_state": state}))

    def verify(self, expected_relaxed_force: Sequence[Sequence[float]]) -> None:
        force = _force(self.relaxed_force_N)
        if not _same_force(force, expected_relaxed_force):
            raise PredictorConsistentProtocolError("predictor was not generated from the current relaxed force")
        force_hash = canonical_sha256(force)
        state_hash = canonical_sha256({"relaxed_force_sha256": force_hash, "ancf_state": dict(self.ancf_state)})
        if self.relaxed_force_sha256 != force_hash or self.predictor_state_sha256 != state_hash:
            raise PredictorConsistentProtocolError("predictor state hash is not reproducible")


@dataclass(frozen=True)
class CfdMotionEvidence:
    """CFD motion/geometry evidence linked to precisely one predictor state."""

    motion: Mapping[str, Any]
    cfd_motion_sha256: str

    @classmethod
    def build(cls, predictor: PredictorState, motion: Mapping[str, Any]) -> "CfdMotionEvidence":
        payload = dict(motion)
        payload["predictor_state_sha256"] = predictor.predictor_state_sha256
        payload["relaxed_force_sha256"] = predictor.relaxed_force_sha256
        return cls(payload, canonical_sha256(payload))

    def verify(self, predictor: PredictorState) -> None:
        motion = dict(self.motion)
        if self.cfd_motion_sha256 != canonical_sha256(motion):
            raise PredictorConsistentProtocolError("CFD motion hash is not reproducible")
        if motion.get("predictor_state_sha256") != predictor.predictor_state_sha256:
            raise PredictorConsistentProtocolError("CFD motion is not sourced from the predictor state")
        if motion.get("relaxed_force_sha256") != predictor.relaxed_force_sha256:
            raise PredictorConsistentProtocolError("CFD motion relaxed-force provenance is incorrect")


@dataclass(frozen=True)
class TrialRequest:
    physical_step: int
    strong_iteration: int
    parent_checkpoint_sha256: str
    relaxed_force_N: tuple[tuple[float, float, float], ...]
    predictor: PredictorState


@dataclass(frozen=True)
class TrialObservation:
    physical_step: int
    strong_iteration: int
    rollback_checkpoint_sha256: str
    observed_force_N: Sequence[Sequence[float]]
    metrics: Mapping[str, Any]
    cfd_motion: CfdMotionEvidence
    trial_checkpoint_committed: bool = False
    partial_cfd_failure: bool = False


@dataclass(frozen=True)
class PromotionRequest:
    physical_step: int
    strong_iteration: int
    parent_checkpoint_sha256: str
    predictor: PredictorState
    cfd_motion: CfdMotionEvidence
    observed_force_N: tuple[tuple[float, float, float], ...]
    residual_absolute_N: float
    residual_relative: float
    trial_observation: TrialObservation


@dataclass(frozen=True)
class PromotionReceipt:
    checkpoint_sha256: str
    physical_step: int
    strong_iteration: int
    committed_predictor_state_sha256: str
    committed_cfd_motion_sha256: str
    previous_slice_forces_N: Sequence[Sequence[float]]


PredictorBuilder = Callable[[int, int, tuple[tuple[float, float, float], ...]], PredictorState]
TrialExecutor = Callable[[TrialRequest], TrialObservation]
Promoter = Callable[[PromotionRequest], PromotionReceipt]


@dataclass
class PhysicalStepLedger:
    physical_step: int
    parent_checkpoint_sha256: str
    candidates: list[dict[str, Any]] = field(default_factory=list)
    status: str = "running"
    failure_reason: str | None = None
    committed_checkpoint_sha256: str | None = None


class PredictorConsistentStrongLedger:
    """In-memory transaction ledger; execution adapters are injected callbacks only."""

    def __init__(self, *, initial_parent_checkpoint_sha256: str, initial_previous_slice_forces_N: Sequence[Sequence[float]]) -> None:
        if not is_sha256(initial_parent_checkpoint_sha256):
            raise ValueError("initial parent checkpoint SHA-256 is invalid")
        self._parent_checkpoint_sha256 = initial_parent_checkpoint_sha256
        self._previous_slice_forces_N = _force(initial_previous_slice_forces_N)
        self._next_physical_step = 0
        self._blocked = False
        self.steps: list[PhysicalStepLedger] = []

    @property
    def blocked(self) -> bool:
        return self._blocked

    @property
    def previous_slice_forces_N(self) -> tuple[tuple[float, float, float], ...]:
        return self._previous_slice_forces_N

    @property
    def parent_checkpoint_sha256(self) -> str:
        return self._parent_checkpoint_sha256

    def run_physical_step(self, physical_step: int, predictor_builder: PredictorBuilder, executor: TrialExecutor, promoter: Promoter) -> PhysicalStepLedger:
        if self._blocked:
            raise PredictorConsistentProtocolError("a failed physical step blocks all later physical steps")
        if physical_step != self._next_physical_step:
            raise PredictorConsistentProtocolError("physical steps must be contiguous")
        result = PhysicalStepLedger(physical_step, self._parent_checkpoint_sha256)
        self.steps.append(result)
        relaxed = self._previous_slice_forces_N
        residual_streak = 0

        for iteration in range(MAX_ITERATIONS):
            try:
                predictor = predictor_builder(physical_step, iteration, relaxed)
                predictor.verify(relaxed)
                request = TrialRequest(physical_step, iteration, self._parent_checkpoint_sha256, relaxed, predictor)
                observation = executor(request)
                observed = self._validate_observation(request, observation)
                residual_absolute, residual_relative = _residual(observed, relaxed)
                cd = _validate_safety(observation.metrics)
                residual_ok = residual_absolute <= FORCE_RESIDUAL_ABSOLUTE_MAX_N and residual_relative <= FORCE_RESIDUAL_RELATIVE_MAX
                residual_streak = residual_streak + 1 if residual_ok else 0
                final_candidate = residual_streak >= CONSECUTIVE_CONVERGED_ITERATIONS
                acceptance_passed = final_candidate and cd <= MAX_ABS_CD
                row = {
                    "strong_iteration": iteration,
                    "relaxed_force_N": relaxed,
                    "observed_force_N": observed,
                    "predictor_state_sha256": predictor.predictor_state_sha256,
                    "cfd_motion_sha256": observation.cfd_motion.cfd_motion_sha256,
                    "force_residual_absolute_N": residual_absolute,
                    "force_residual_relative": residual_relative,
                    "residual_converged": residual_ok,
                    "residual_consecutive_count": residual_streak,
                    "max_abs_Cd": cd,
                    "final_candidate": final_candidate,
                    "final_acceptance_passed": acceptance_passed,
                }
                result.candidates.append(row)
                if acceptance_passed:
                    receipt = promoter(PromotionRequest(physical_step, iteration, self._parent_checkpoint_sha256, predictor, observation.cfd_motion, observed, residual_absolute, residual_relative, observation))
                    self._validate_promotion(receipt, request, observation.cfd_motion, observed)
                    result.committed_checkpoint_sha256 = receipt.checkpoint_sha256
                    result.status = "committed"
                    self._parent_checkpoint_sha256 = receipt.checkpoint_sha256
                    self._previous_slice_forces_N = observed
                    self._next_physical_step += 1
                    return result
                relaxed = _relax(relaxed, observed)
            except Exception as exc:
                result.status = "failed_hard_gate"
                result.failure_reason = f"{type(exc).__name__}: {exc}"
                self._blocked = True
                return result

        result.status = "failed_iteration_limit"
        result.failure_reason = "strong-coupling iteration limit reached without accepted final candidate"
        self._blocked = True
        return result

    def _validate_observation(self, request: TrialRequest, observation: TrialObservation) -> tuple[tuple[float, float, float], ...]:
        if observation.trial_checkpoint_committed:
            raise PredictorConsistentProtocolError("candidate committed a checkpoint before final acceptance")
        if observation.partial_cfd_failure:
            raise PredictorConsistentProtocolError("candidate has a partial CFD failure")
        if observation.rollback_checkpoint_sha256 != request.parent_checkpoint_sha256:
            raise PredictorConsistentProtocolError("candidate rollback checkpoint does not match the physical-step parent")
        if (observation.physical_step, observation.strong_iteration) != (request.physical_step, request.strong_iteration):
            raise PredictorConsistentProtocolError("candidate physical-step identity is incorrect")
        request.predictor.verify(request.relaxed_force_N)
        observation.cfd_motion.verify(request.predictor)
        return _force(observation.observed_force_N)

    def _validate_promotion(
        self,
        receipt: PromotionReceipt,
        request: TrialRequest,
        cfd_motion: CfdMotionEvidence,
        observed: tuple[tuple[float, float, float], ...],
    ) -> None:
        if not is_sha256(receipt.checkpoint_sha256):
            raise PredictorConsistentProtocolError("promotion checkpoint SHA-256 is invalid")
        if (receipt.physical_step, receipt.strong_iteration) != (request.physical_step, request.strong_iteration):
            raise PredictorConsistentProtocolError("promotion selected a different candidate")
        if receipt.committed_predictor_state_sha256 != request.predictor.predictor_state_sha256:
            raise PredictorConsistentProtocolError("promotion did not commit the selected predictor ANCF state")
        if receipt.committed_cfd_motion_sha256 != cfd_motion.cfd_motion_sha256:
            raise PredictorConsistentProtocolError("promotion did not commit the selected predictor-geometry CFD field")
        stored = _force(receipt.previous_slice_forces_N)
        if not _same_force(stored, observed):
            raise PredictorConsistentProtocolError("previous_slice_forces must store actual observed CFD force")
