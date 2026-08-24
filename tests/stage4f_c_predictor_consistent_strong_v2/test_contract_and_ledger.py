from __future__ import annotations

import hashlib
import json
import unittest

from src.coupling.stage4f_c_predictor_consistent_strong_v2.contract import (
    ALPHA,
    CONSECUTIVE_CONVERGED_ITERATIONS,
    MAX_ITERATIONS,
    build_contract,
    validate_contract,
)
from src.coupling.stage4f_c_predictor_consistent_strong_v2.ledger import (
    CfdMotionEvidence,
    PredictorConsistentStrongLedger,
    PredictorState,
    PromotionReceipt,
    TrialObservation,
)


PARENT = "a" * 64
COMMIT = "b" * 64
INITIAL_FORCE = ((0.0, 0.0, 0.0),) * 3
OBSERVED_FORCE = ((10.0, 0.0, 0.0),) * 3


def _rehash(value):
    payload = dict(value)
    payload.pop("contract_sha256", None)
    value["contract_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _metrics(**changes):
    value = {
        "max_abs_Cd": 6.0,
        "max_CFL": 0.2,
        "virtual_work_relative_error": 1.0e-14,
        "force_conversion_relative_error": 0.0,
        "position_difference_over_D": 0.001,
        "velocity_difference_over_U": 0.001,
        "fatal_detected": False,
        "negative_volume_detected": False,
        "all_slices_complete": True,
        "geometry_valid": True,
    }
    value.update(changes)
    return value


class _OfflineHarness:
    """No process/file execution: all candidate evidence is deterministic in memory."""

    def __init__(self, *, faults=(), cd_by_iteration=None, observed=OBSERVED_FORCE):
        self.faults = set(faults)
        self.cd_by_iteration = dict(cd_by_iteration or {})
        self.observed = observed
        self.requests = []
        self.promotions = []

    def predictor(self, step, iteration, relaxed):
        return PredictorState.build(relaxed, {"q": [float(step), float(iteration)], "source": "relaxed-force-predictor"})

    def executor(self, request):
        self.requests.append(request)
        motion = CfdMotionEvidence.build(request.predictor, {"slice_motion": [request.strong_iteration, 0, 0]})
        metrics = _metrics(max_abs_Cd=self.cd_by_iteration.get(request.strong_iteration, 6.0))
        if "motion_origin" in self.faults:
            payload = dict(motion.motion)
            payload["predictor_state_sha256"] = "0" * 64
            motion = CfdMotionEvidence(payload, hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest())
        if "motion_hash" in self.faults:
            motion = CfdMotionEvidence({**motion.motion, "mutated_after_hash": True}, motion.cfd_motion_sha256)
        if "fatal" in self.faults:
            metrics["fatal_detected"] = True
        if "cfl" in self.faults:
            metrics["max_CFL"] = 0.8
        if "nonfinite" in self.faults:
            metrics["max_abs_Cd"] = float("nan")
        if "geometry" in self.faults:
            metrics["geometry_valid"] = False
        return TrialObservation(
            physical_step=request.physical_step,
            strong_iteration=request.strong_iteration,
            rollback_checkpoint_sha256=("0" * 64 if "rollback" in self.faults else request.parent_checkpoint_sha256),
            observed_force_N=self.observed,
            metrics=metrics,
            cfd_motion=motion,
            trial_checkpoint_committed="trial_commit" in self.faults,
            partial_cfd_failure="partial_cfd" in self.faults,
        )

    def promoter(self, request):
        self.promotions.append(request)
        return PromotionReceipt(
            checkpoint_sha256=COMMIT,
            physical_step=request.physical_step,
            strong_iteration=request.strong_iteration,
            committed_predictor_state_sha256=("0" * 64 if "state_commit" in self.faults else request.predictor.predictor_state_sha256),
            committed_cfd_motion_sha256=("0" * 64 if "field_commit" in self.faults else request.cfd_motion.cfd_motion_sha256),
            previous_slice_forces_N=(request.predictor.relaxed_force_N if "relaxed_stored" in self.faults else request.observed_force_N),
        )


class ContractTests(unittest.TestCase):
    def test_frozen_contract_contains_predictor_and_final_cd_policies(self):
        contract = build_contract(PARENT)
        validate_contract(contract)
        self.assertEqual(contract["execution_scope"], "three_physical_step_real_preflight")
        self.assertEqual(contract["relaxation_alpha"], ALPHA)
        self.assertIn("predictor", contract["commit_policy"])

    def test_rehashed_contract_tampering_is_rejected(self):
        contract = build_contract(PARENT)
        contract["max_iterations_per_physical_step"] = 9
        _rehash(contract)
        with self.assertRaisesRegex(ValueError, "frozen"):
            validate_contract(contract)


class PredictorConsistentLedgerTests(unittest.TestCase):
    def _ledger(self):
        return PredictorConsistentStrongLedger(
            initial_parent_checkpoint_sha256=PARENT,
            initial_previous_slice_forces_N=INITIAL_FORCE,
        )

    def test_converged_commit_uses_same_predictor_state_and_motion_field(self):
        harness = _OfflineHarness()
        ledger = self._ledger()
        result = ledger.run_physical_step(0, harness.predictor, harness.executor, harness.promoter)
        self.assertEqual(result.status, "committed")
        self.assertEqual(len(result.candidates), CONSECUTIVE_CONVERGED_ITERATIONS)
        self.assertEqual(len(harness.promotions), 1)
        selected = result.candidates[-1]
        promotion = harness.promotions[0]
        self.assertEqual(promotion.predictor.predictor_state_sha256, selected["predictor_state_sha256"])
        self.assertEqual(promotion.cfd_motion.cfd_motion_sha256, selected["cfd_motion_sha256"])
        self.assertEqual(ledger.previous_slice_forces_N, OBSERVED_FORCE)
        self.assertNotEqual(harness.requests[1].relaxed_force_N, OBSERVED_FORCE)
        self.assertEqual(harness.requests[1].predictor.relaxed_force_N, harness.requests[1].relaxed_force_N)

    def test_finite_excess_cd_is_recorded_but_does_not_hard_stop_intermediate_trial(self):
        harness = _OfflineHarness(cd_by_iteration={0: 12.0, 1: 12.0, 2: 6.0})
        result = self._ledger().run_physical_step(0, harness.predictor, harness.executor, harness.promoter)
        self.assertEqual(result.status, "committed")
        self.assertEqual([row["max_abs_Cd"] for row in result.candidates], [12.0, 12.0, 6.0])
        self.assertFalse(result.candidates[1]["final_acceptance_passed"])
        self.assertTrue(result.candidates[2]["final_acceptance_passed"])

    def test_fault_injection_hard_stops_before_promotion(self):
        faults = ("motion_origin", "motion_hash", "fatal", "cfl", "nonfinite", "geometry", "rollback", "trial_commit", "partial_cfd")
        for fault in faults:
            with self.subTest(fault=fault):
                harness = _OfflineHarness(faults={fault})
                result = self._ledger().run_physical_step(0, harness.predictor, harness.executor, harness.promoter)
                self.assertEqual(result.status, "failed_hard_gate")
                self.assertEqual(harness.promotions, [])

    def test_fault_injection_rejects_mismatched_final_artifacts_and_relaxed_force_storage(self):
        for fault in ("state_commit", "field_commit", "relaxed_stored"):
            with self.subTest(fault=fault):
                harness = _OfflineHarness(faults={fault})
                result = self._ledger().run_physical_step(0, harness.predictor, harness.executor, harness.promoter)
                self.assertEqual(result.status, "failed_hard_gate")
                self.assertEqual(len(harness.promotions), 1)

    def test_iteration_limit_blocks_later_steps_without_any_commit(self):
        enormous = ((100_000.0, 0.0, 0.0),) * 3
        harness = _OfflineHarness(observed=enormous)
        ledger = self._ledger()
        result = ledger.run_physical_step(0, harness.predictor, harness.executor, harness.promoter)
        self.assertEqual(result.status, "failed_iteration_limit")
        self.assertEqual(len(result.candidates), MAX_ITERATIONS)
        self.assertEqual(harness.promotions, [])
        with self.assertRaisesRegex(RuntimeError, "blocks"):
            ledger.run_physical_step(1, harness.predictor, harness.executor, harness.promoter)


if __name__ == "__main__":
    unittest.main()
