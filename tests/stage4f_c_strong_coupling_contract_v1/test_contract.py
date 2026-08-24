from __future__ import annotations

import copy
import hashlib
import json
import unittest

from src.coupling.stage4f_c_strong_coupling_contract_v1.contract import (
    MAX_ITERATIONS,
    StrongCouplingLedger,
    build_contract,
    iteration_passes_hard_gates,
    validate_contract,
)


PARENT = "a" * 64
COMMITTED = "b" * 64


def metrics(**updates):
    value = {
        "force_residual_relative": 0.0009,
        "force_residual_absolute_N": 24.0,
        "max_abs_Cd": 9.0,
        "max_CFL": 0.7,
        "position_difference_over_D": 0.004,
        "velocity_difference_over_U": 0.009,
        "virtual_work_relative_error": 1.0e-13,
        "force_conversion_relative_error": 1.0e-11,
        "all_three_slices_complete": True,
        "rollback_verified": True,
        "fatal_detected": False,
        "negative_volume_detected": False,
    }
    value.update(updates)
    return value


def rehash(value):
    candidate = dict(value)
    candidate.pop("contract_sha256", None)
    value["contract_sha256"] = hashlib.sha256(
        json.dumps(candidate, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class FrozenContractTests(unittest.TestCase):
    def test_frozen_contract_is_valid(self):
        validate_contract(build_contract(PARENT))

    def test_alpha_tamper_rejected_even_after_rehash(self):
        value = build_contract(PARENT)
        value["relaxation_alpha"] = 0.75
        rehash(value)
        with self.assertRaisesRegex(ValueError, "contract changed"):
            validate_contract(value)

    def test_residual_limit_tamper_rejected(self):
        value = build_contract(PARENT)
        value["force_residual_relative_max"] = 0.02
        rehash(value)
        with self.assertRaises(ValueError):
            validate_contract(value)

    def test_iteration_limit_tamper_rejected(self):
        value = build_contract(PARENT)
        value["max_iterations_per_physical_step"] = 9
        rehash(value)
        with self.assertRaises(ValueError):
            validate_contract(value)

    def test_invalid_parent_identity_rejected(self):
        with self.assertRaises(ValueError):
            build_contract("not-a-sha")


class HardGateTests(unittest.TestCase):
    def test_all_frozen_limits_pass_at_inclusive_boundaries_except_cfl(self):
        self.assertTrue(iteration_passes_hard_gates(metrics(
            force_residual_relative=0.001,
            force_residual_absolute_N=25.0,
            max_abs_Cd=10.0,
            max_CFL=0.799999,
            position_difference_over_D=0.005,
            velocity_difference_over_U=0.01,
            virtual_work_relative_error=1.0e-12,
            force_conversion_relative_error=1.0e-10,
        )))

    def test_each_numeric_gate_rejects_excess(self):
        cases = {
            "force_residual_relative": 0.0010001,
            "force_residual_absolute_N": 25.0001,
            "max_abs_Cd": 10.0001,
            "max_CFL": 0.8,
            "position_difference_over_D": 0.005001,
            "velocity_difference_over_U": 0.010001,
            "virtual_work_relative_error": 1.01e-12,
            "force_conversion_relative_error": 1.01e-10,
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                self.assertFalse(iteration_passes_hard_gates(metrics(**{name: value})))

    def test_nonfinite_metric_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                iteration_passes_hard_gates(metrics(force_residual_relative=value))

    def test_slice_fatal_volume_and_rollback_gates(self):
        for update in (
            {"all_three_slices_complete": False},
            {"rollback_verified": False},
            {"fatal_detected": True},
            {"negative_volume_detected": True},
        ):
            with self.subTest(update=update):
                self.assertFalse(iteration_passes_hard_gates(metrics(**update)))


class TransactionLedgerTests(unittest.TestCase):
    def ledger(self):
        return StrongCouplingLedger(PARENT, physical_step_index=3, target_time_s=1.51)

    def record(self, ledger, index=0, **metric_updates):
        return ledger.record_iteration(
            iteration_index=index,
            rollback_checkpoint_sha256=PARENT,
            physical_step_index=3,
            target_time_s=1.51,
            metrics=metrics(**metric_updates),
        )

    def test_iteration_does_not_advance_physical_step(self):
        ledger = self.ledger()
        self.assertFalse(self.record(ledger))
        self.assertEqual(ledger.physical_steps_advanced, 0)
        self.assertFalse(ledger.next_physical_step_authorized)

    def test_rollback_identity_mismatch_fails_step(self):
        ledger = self.ledger()
        with self.assertRaisesRegex(ValueError, "rollback identity"):
            ledger.record_iteration(
                iteration_index=0,
                rollback_checkpoint_sha256="c" * 64,
                physical_step_index=3,
                target_time_s=1.51,
                metrics=metrics(),
            )
        self.assertTrue(ledger.failed)
        self.assertFalse(ledger.next_physical_step_authorized)

    def test_iteration_cannot_change_time_or_physical_step(self):
        for step, time_value in ((4, 1.51), (3, 1.5101)):
            ledger = self.ledger()
            with self.subTest(step=step, time=time_value), self.assertRaises(ValueError):
                ledger.record_iteration(
                    iteration_index=0,
                    rollback_checkpoint_sha256=PARENT,
                    physical_step_index=step,
                    target_time_s=time_value,
                    metrics=metrics(),
                )
            self.assertTrue(ledger.failed)

    def test_iteration_sequence_must_be_contiguous(self):
        with self.assertRaises(ValueError):
            self.record(self.ledger(), index=1)

    def test_iteration_limit_failure_blocks_commit_and_next_step(self):
        ledger = self.ledger()
        for index in range(MAX_ITERATIONS):
            self.record(ledger, index=index, force_residual_relative=0.02)
        with self.assertRaisesRegex(RuntimeError, "limit"):
            self.record(ledger, index=MAX_ITERATIONS)
        with self.assertRaises(RuntimeError):
            ledger.commit(COMMITTED)
        self.assertFalse(ledger.next_physical_step_authorized)

    def test_nonconverged_iteration_cannot_commit(self):
        ledger = self.ledger()
        self.assertFalse(self.record(ledger, force_residual_relative=0.02))
        with self.assertRaisesRegex(RuntimeError, "before convergence"):
            ledger.commit(COMMITTED)

    def test_exactly_one_final_checkpoint(self):
        ledger = self.ledger()
        self.record(ledger)
        self.assertTrue(self.record(ledger, index=1))
        ledger.commit(COMMITTED)
        self.assertEqual(ledger.committed_checkpoint_sha256, COMMITTED)
        self.assertEqual(ledger.physical_steps_advanced, 1)
        self.assertTrue(ledger.next_physical_step_authorized)
        with self.assertRaisesRegex(RuntimeError, "already"):
            ledger.commit("c" * 64)

    def test_iterations_forbid_intermediate_checkpoint(self):
        ledger = self.ledger()
        self.record(ledger, force_residual_relative=0.02)
        self.assertIsNone(ledger.committed_checkpoint_sha256)
        self.record(ledger, index=1)
        self.record(ledger, index=2)
        ledger.commit(COMMITTED)
        self.assertEqual(len(ledger.iterations), 3)

    def test_explicit_failure_forbids_next_iteration_commit_and_next_step(self):
        ledger = self.ledger()
        ledger.fail("solver fatal")
        with self.assertRaises(RuntimeError):
            self.record(ledger)
        with self.assertRaises(RuntimeError):
            ledger.commit(COMMITTED)
        self.assertFalse(ledger.next_physical_step_authorized)

    def test_committed_step_forbids_more_iterations(self):
        ledger = self.ledger()
        self.record(ledger)
        self.record(ledger, index=1)
        ledger.commit(COMMITTED)
        with self.assertRaises(RuntimeError):
            self.record(ledger, index=2)


if __name__ == "__main__":
    unittest.main()
