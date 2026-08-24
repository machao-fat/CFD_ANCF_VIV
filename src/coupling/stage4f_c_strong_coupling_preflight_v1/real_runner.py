"""Guarded real-process adapter for the three physical-step preflight.

Importing this module is inert.  The CLI requires ``--execute`` before it can
construct a CandidateIterationEngine, so unit tests can exercise this layer
without starting MATLAB or OpenFOAM.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..multi_slice_mapping.mapping import atomic_write_json, sha256_file
from ..stage4f_c_strong_coupling_contract_v1.contract import (
    FORCE_RESIDUAL_ABSOLUTE_MAX_N,
    FORCE_RESIDUAL_RELATIVE_MAX,
    build_contract,
    iteration_passes_hard_gates,
    validate_contract,
)
from .coordinator import CheckpointIdentity, OuterFixedPointCoordinator, PromotionReceipt, PromotionRequest, TrialObservation, TrialRequest
from .iteration_engine import CandidateIterationEngine


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PARENT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_fixed_point_v5" / "formal_preflight_attempt3" / "checkpoints" / "checkpoint_step00000002_d4def62051c1.json"
DEFAULT_CASE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_c_strong_coupling_preflight_v1"
DEFAULT_RESULT_ROOT = PROJECT_ROOT / "results" / "14_stage4f_c_strong_coupling_preflight_v1"


class AdapterProtocolError(RuntimeError):
    pass


def _force(value: Sequence[Sequence[float]]) -> list[list[float]]:
    rows = [[float(component) for component in row] for row in value]
    if len(rows) != 3 or any(len(row) != 3 for row in rows):
        raise AdapterProtocolError("candidate force must be a 3 by 3 matrix")
    if not all(math.isfinite(component) for row in rows for component in row):
        raise AdapterProtocolError("candidate force contains non-finite values")
    return rows


def residuals(observed: Sequence[Sequence[float]], relaxed: Sequence[Sequence[float]]) -> tuple[float, float]:
    """The frozen coordinator formula, duplicated deliberately for lifecycle safety."""
    actual, guess = _force(observed), _force(relaxed)
    absolute = max(abs(a - b) for left, right in zip(actual, guess) for a, b in zip(left, right))
    denominator = max(25_000.0, *(abs(item) for row in actual for item in row), *(abs(item) for row in guess for item in row))
    return absolute, absolute / denominator


def _slice_id(exc: BaseException) -> int | None:
    if isinstance(getattr(exc, "slice_id", None), int):
        return int(exc.slice_id)
    match = re.search(r"slice[_ ]?(\\d+)", str(exc), re.I)
    return int(match.group(1)) if match else None


@dataclass
class _HeldCandidate:
    engine: Any
    request: TrialRequest
    observation: TrialObservation


class RealSidecarAdapter:
    """One fresh candidate engine per trial, with at most one engine alive.

    A non-selected candidate is discarded and shut down inside ``execute``.
    The only engine allowed to survive ``execute`` is the one that the
    coordinator's very next operation will promote.
    """

    def __init__(self, *, case_root: Path, result_root: Path, engine_factory: Callable[[Mapping[str, Any]], Any] = CandidateIterationEngine) -> None:
        self.case_root, self.result_root, self.engine_factory = Path(case_root), Path(result_root), engine_factory
        self.pending: _HeldCandidate | None = None
        self.engines: list[Any] = []
        self.trials: list[dict[str, Any]] = []
        self.gates: list[dict[str, Any]] = []
        self.processes: list[dict[str, Any]] = []
        self.first_failure: dict[str, Any] | None = None
        self._prior_hard_gate: dict[int, bool] = {}
        self._write_evidence()

    def _write_evidence(self) -> None:
        atomic_write_json(self.result_root / "trial_ledger.json", {"schema": "stage4f-c-strong-coupling-preflight-v1-trial-ledger-1.0.0", "trials": self.trials})
        atomic_write_json(self.result_root / "gate_decisions.json", {"schema": "stage4f-c-strong-coupling-preflight-v1-gates-1.0.0", "decisions": self.gates})
        atomic_write_json(self.result_root / "owned_process_registry.json", {"schema": "stage4f-c-strong-coupling-preflight-v1-process-registry-1.0.0", "maximum_live_candidate_engines": 1, "candidates": self.processes})
        if self.first_failure is not None:
            atomic_write_json(self.result_root / "first_failure.json", self.first_failure)

    def _root(self, request: TrialRequest) -> Path:
        return self.case_root / f"step_{request.physical_step:02d}" / f"iteration_{request.strong_iteration:02d}"

    def _record_process(self, engine: Any, request: TrialRequest, disposition: str) -> None:
        root = Path(getattr(engine, "root", self._root(request)))
        self.processes.append({"physical_step": request.physical_step, "strong_iteration": request.strong_iteration, "case_root": str(root), "disposition": disposition, "registry_path": str(root / "owned_process_registry.json")})

    def _dispose(self, engine: Any, request: TrialRequest, *, discard: bool, disposition: str) -> None:
        try:
            if discard:
                engine.discard_trial()
        finally:
            engine.shutdown()
            self._record_process(engine, request, disposition)
            if self.pending is not None and self.pending.engine is engine:
                self.pending = None

    def _fail(self, request: TrialRequest, exc: BaseException) -> None:
        if self.first_failure is None:
            self.first_failure = {"schema": "stage4f-c-strong-coupling-preflight-v1-first-failure-1.0.0", "physical_step": request.physical_step, "strong_iteration": request.strong_iteration, "slice_id": _slice_id(exc), "reason": f"{type(exc).__name__}: {exc}", "blocks_later_physical_steps": True}

    def record_terminal_failure(self, *, physical_step: int, strong_iteration: int | None, reason: str) -> None:
        """Persist coordinator-only failures such as iteration-limit exhaustion."""
        if self.first_failure is None:
            self.first_failure = {"schema": "stage4f-c-strong-coupling-preflight-v1-first-failure-1.0.0", "physical_step": physical_step, "strong_iteration": strong_iteration, "slice_id": None, "reason": reason, "blocks_later_physical_steps": True}
        self._write_evidence()

    def _metrics(self, row: Mapping[str, Any], request: TrialRequest) -> tuple[dict[str, Any], float, float]:
        absolute, relative = residuals(row["observed_slice_forces_N"], request.relaxed_force_N)
        metrics = {
            "force_residual_absolute_N": absolute, "force_residual_relative": relative,
            "max_abs_Cd": row["max_abs_Cd"], "max_CFL": row["max_cfl"],
            "position_difference_over_D": row["position_difference_over_D"], "velocity_difference_over_U": row["velocity_difference_over_U"],
            "virtual_work_relative_error": row["virtual_work_relative_error"], "force_conversion_relative_error": row["force_conversion_relative_error"],
            "all_three_slices_complete": row["all_three_slices_complete"],
            "rollback_verified": row["parent_checkpoint_sha256"] == request.parent.sha256 and Path(row["parent_checkpoint"]).resolve() == request.parent.path.resolve(),
            "fatal_detected": not bool(row["log_audit"]["passed"]),
            "negative_volume_detected": any("negative volume" in str(item).lower() for item in row["log_audit"].get("violations", [])),
        }
        return metrics, absolute, relative

    def execute(self, request: TrialRequest) -> TrialObservation:
        if self.pending is not None:
            raise AdapterProtocolError("a selected candidate was not promoted before the next candidate")
        request.parent.verify()
        root = self._root(request)
        plan = {"branch": "strong_preflight", "dt_s": (request.target_tick_ns - request.current_tick_ns) / 1e9, "physical_step": request.physical_step, "current_time_s": request.current_tick_ns / 1e9, "target_time_s": request.target_tick_ns / 1e9, "case_root": str(root.resolve()), "source_checkpoint": str(request.parent.path.resolve())}
        engine = self.engine_factory(plan)
        self.engines.append(engine)
        try:
            row = dict(engine.run_trial(previous_slice_forces_N=request.relaxed_force_N))
            metrics, absolute, relative = self._metrics(row, request)
            if not metrics["rollback_verified"]:
                raise AdapterProtocolError("candidate rollback source path or SHA-256 does not match the physical-step parent")
            hard = iteration_passes_hard_gates(metrics)
            prior = self._prior_hard_gate.get(request.physical_step, False)
            selected = hard and prior  # Identical condition to StrongCouplingLedger.record_iteration.
            self._prior_hard_gate[request.physical_step] = hard
            observation = TrialObservation(str(row["parent_checkpoint_sha256"]), Path(row["parent_checkpoint"]), request.physical_step, request.strong_iteration, 0, request.current_tick_ns, request.target_tick_ns, _force(row["observed_slice_forces_N"]), metrics)
            gate = {"physical_step": request.physical_step, "strong_iteration": request.strong_iteration, "force_residual_absolute_N": absolute, "force_residual_relative": relative, "residual_thresholds_passed": absolute <= FORCE_RESIDUAL_ABSOLUTE_MAX_N and relative <= FORCE_RESIDUAL_RELATIVE_MAX, "hard_gates_passed": hard, "previous_hard_gates_passed": prior, "coordinator_will_promote": selected, "disposition": "held_for_promotion" if selected else "discarded_and_shutdown"}
            self.trials.append({"physical_step": request.physical_step, "strong_iteration": request.strong_iteration, "parent_checkpoint": str(request.parent.path), "parent_checkpoint_sha256": request.parent.sha256, "parent_case_root": str(request.parent.path.parent.parent / "cases"), "candidate_root": str(root), "observed_force_N": observation.observed_force_N, "metrics": metrics, "gate": gate})
            self.gates.append(gate)
            atomic_write_json(root / "gate_decision.json", gate)
            if selected:
                self.pending = _HeldCandidate(engine, request, observation)
            else:
                self._dispose(engine, request, discard=True, disposition="discarded_and_shutdown")
            self._write_evidence()
            return observation
        except Exception as exc:
            self._fail(request, exc)
            try:
                self._dispose(engine, request, discard=getattr(engine, "_trial", None) is not None, disposition="failed_and_shutdown")
            except Exception as close_exc:
                self._fail(request, close_exc)
            self._write_evidence()
            raise

    def promote(self, request: PromotionRequest) -> PromotionReceipt:
        held = self.pending
        if held is None:
            raise AdapterProtocolError("promotion has no live selected candidate")
        if request.physical_step != held.request.physical_step or request.selected_strong_iteration != held.request.strong_iteration or request.parent.sha256 != held.request.parent.sha256 or request.parent.path.resolve() != held.request.parent.path.resolve():
            raise AdapterProtocolError("promotion request does not identify the held candidate")
        try:
            checkpoint = Path(held.engine.promote())
            receipt = PromotionReceipt(CheckpointIdentity(checkpoint, sha256_file(checkpoint), request.physical_step), request.physical_step, request.target_tick_ns, request.selected_strong_iteration, request.observed_force_N)
            self._record_process(held.engine, held.request, "promoted_and_shutdown")
            return receipt
        except Exception as exc:
            self._fail(held.request, exc)
            raise
        finally:
            held.engine.shutdown()
            self.pending = None
            self._write_evidence()

    def close(self) -> None:
        if self.pending is not None:
            held = self.pending
            try:
                self._dispose(held.engine, held.request, discard=True, disposition="adapter_close_discarded")
            except Exception as exc:
                self._fail(held.request, exc)
        self._write_evidence()


def _steps(results: Sequence[Any]) -> list[dict[str, Any]]:
    serial: list[dict[str, Any]] = []
    for result in results:
        promotion = result.promotion
        serial.append({"physical_step": result.physical_step, "current_tick_ns": result.current_tick_ns, "target_tick_ns": result.target_tick_ns, "parent_checkpoint_sha256": result.parent_checkpoint_sha256, "iterations": result.iterations, "status": result.status, "failure_reason": result.failure_reason, "promotion": None if promotion is None else {"checkpoint": str(promotion.checkpoint.path), "checkpoint_sha256": promotion.checkpoint.sha256, "selected_strong_iteration": promotion.selected_strong_iteration, "stored_observed_force_N": _force(promotion.stored_observed_force_N)}})
    return serial


def run_three_step(*, parent_checkpoint: str | Path = DEFAULT_PARENT, case_root: str | Path = DEFAULT_CASE_ROOT, result_root: str | Path = DEFAULT_RESULT_ROOT, engine_factory: Callable[[Mapping[str, Any]], Any] = CandidateIterationEngine) -> dict[str, Any]:
    """Execute production engines. Tests use ``engine_factory`` mocks only."""
    parent_path, cases, results = Path(parent_checkpoint).resolve(), Path(case_root).resolve(), Path(result_root).resolve()
    payload = json.loads(parent_path.read_text(encoding="utf-8"))
    parent_sha = sha256_file(parent_path)
    contract = build_contract(parent_sha)
    validate_contract(contract)  # Must happen before engine construction or evidence writing.
    parent = CheckpointIdentity(parent_path, parent_sha, int(payload["step"]))
    parent.verify()
    if results.exists() and any(results.iterdir()):
        raise FileExistsError(f"result root already contains evidence: {results}")
    results.mkdir(parents=True, exist_ok=True)
    atomic_write_json(results / "strong_coupling_contract.json", contract)
    envelope = {"schema": "stage4f-c-strong-coupling-preflight-v1-envelope-1.0.0", "contract_path": str(results / "strong_coupling_contract.json"), "contract_sha256": contract["contract_sha256"], "parent_checkpoint": str(parent.path), "parent_checkpoint_sha256": parent.sha256, "parent_source_physical_step": parent.source_physical_step, "case_root": str(cases), "requested_physical_steps": 3, "execution_mode": "real_process_adapter", "status": "running"}
    atomic_write_json(results / "execution_envelope.json", envelope)
    coordinator = OuterFixedPointCoordinator(initial_parent=parent, initial_force_N=payload["previous_slice_forces_N"])
    adapter = RealSidecarAdapter(case_root=cases, result_root=results, engine_factory=engine_factory)
    try:
        outcomes = coordinator.run_three_step_preflight(adapter.execute, adapter.promote)
    finally:
        adapter.close()
    failed = next((item for item in outcomes if item.status == "failed"), None)
    if failed is not None:
        last_iteration = failed.iterations[-1]["strong_iteration"] if failed.iterations else None
        adapter.record_terminal_failure(physical_step=failed.physical_step, strong_iteration=last_iteration, reason=failed.failure_reason or "strong-coupling physical step failed")
    steps = _steps(outcomes)
    envelope.update({"status": "passed" if len(steps) == 3 and all(step["status"] == "committed" for step in steps) else "failed", "committed_physical_steps": sum(step["status"] == "committed" for step in steps), "next_parent_checkpoint": str(coordinator.parent.path), "next_parent_checkpoint_sha256": coordinator.parent.sha256, "first_failure": adapter.first_failure, "steps": steps})
    atomic_write_json(results / "execution_envelope.json", envelope)
    return envelope


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="three-step strong-coupling real-process adapter")
    parser.add_argument("--parent-checkpoint", default=str(DEFAULT_PARENT)); parser.add_argument("--case-root", default=str(DEFAULT_CASE_ROOT)); parser.add_argument("--result-root", default=str(DEFAULT_RESULT_ROOT)); parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({"status": "not_executed", "reason": "pass --execute to launch real candidate engines", "parent_checkpoint": str(Path(args.parent_checkpoint).resolve()), "case_root": str(Path(args.case_root).resolve()), "result_root": str(Path(args.result_root).resolve())}, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(run_three_step(parent_checkpoint=args.parent_checkpoint, case_root=args.case_root, result_root=args.result_root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
