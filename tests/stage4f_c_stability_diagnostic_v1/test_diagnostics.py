import unittest

from src.coupling.stage4f_c_stability_diagnostic_v1 import (
    AuditFailure,
    analyze_amplification,
    audit_checkpoint_initial_state,
    audit_force_transaction,
    audit_time_layers,
    decide_next_action,
    recommend_minimal_repair,
)


class StabilityDiagnosticTests(unittest.TestCase):
    def test_amplifying_feedback_is_detected(self):
        result = analyze_amplification([1.0, 1.5, 2.25], dt=0.001)
        self.assertTrue(result["unstable_diagnostic"])
        self.assertEqual(result["classification"], "amplifying_feedback")

    def test_decay_is_not_classified_unstable(self):
        self.assertFalse(analyze_amplification([1.0, .5, .25], dt=.001)["unstable_diagnostic"])

    def test_zero_state_is_skipped(self):
        self.assertEqual(analyze_amplification([0, 1, 2], dt=.001)["ratios"], [2.0])

    def test_invalid_amplification_inputs_rejected(self):
        with self.assertRaises(AuditFailure):
            analyze_amplification([1, 2], dt=0)

    def test_time_layers_pass(self):
        rows = [{"step": i, "force_time": i, "committed_time": i, "predictor_time": i, "published_time": i, "force_consumed": True, "old_force_reused": False} for i in range(2)]
        self.assertTrue(audit_time_layers(rows)["passed"])

    def test_time_layer_mismatch_and_reuse_fail(self):
        row = {"step": 0, "force_time": 1, "committed_time": 0, "predictor_time": 0, "published_time": 1, "force_consumed": True, "old_force_reused": True}
        result = audit_time_layers([row])
        self.assertFalse(result["passed"])
        self.assertGreaterEqual(len(result["failure_reasons"]), 3)

    def test_duplicate_steps_fail(self):
        row = {"step": 0, "force_time": 0, "committed_time": 0, "predictor_time": 0, "published_time": 0, "force_consumed": True, "old_force_reused": False}
        self.assertFalse(audit_time_layers([row, row])["passed"])

    def test_force_transaction_passes(self):
        result = audit_force_transaction([2, 2], dt=.5, expected_impulse=2, applied_impulse=2)
        self.assertTrue(result["passed"])
        self.assertFalse(result["possible_dt_omission"])

    def test_force_transaction_detects_dt_omission(self):
        result = audit_force_transaction([2, 2], dt=.5, expected_impulse=2, applied_impulse=4)
        self.assertFalse(result["passed"])
        self.assertTrue(result["possible_dt_omission"])

    def test_force_transaction_detects_double_dt(self):
        result = audit_force_transaction([2, 2], dt=.5, expected_impulse=2, applied_impulse=1)
        self.assertFalse(result["passed"])
        self.assertTrue(result["possible_dt_double_application"])

    def test_checkpoint_identity(self):
        value = {"case_id": "c", "manifest_sha256": "m", "config_sha256": "g", "time_s": 1.5, "commit_seq": 2, "slice_ids": [0, 1, 2], "state": "committed"}
        self.assertTrue(audit_checkpoint_initial_state(value, value)["passed"])

    def test_checkpoint_mismatch_rejected(self):
        value = {"case_id": "c", "manifest_sha256": "m", "config_sha256": "g", "time_s": 1.5, "commit_seq": 2, "slice_ids": [0, 1, 2], "state": "committed"}
        expected = dict(value, time_s=1.4)
        self.assertFalse(audit_checkpoint_initial_state(value, expected)["passed"])

    def test_next_action_is_conservative(self):
        self.assertEqual(decide_next_action(d1_passed=False, d2_passed=False, evidence_ok=True), "failure_timestep_refinement_not_sufficient")
        self.assertEqual(decide_next_action(d1_passed=True, d2_passed=True, evidence_ok=True), "accepted_timestep_refinement_candidate")
        self.assertEqual(decide_next_action(d1_passed=True, d2_passed=True, evidence_ok=False), "failure_identity_or_runtime_blocked")

    def test_amplification_requires_new_fixed_point_authorization(self):
        result = recommend_minimal_repair(
            amplification_detected=True,
            time_layers_passed=True,
            force_transaction_passed=True,
            checkpoint_passed=True,
        )
        self.assertEqual(result["action"], "freeze_and_run_partitioned_fixed_point_stability_diagnostic")
        self.assertTrue(result["new_authorization_required"])
        self.assertIn("dt/8 continuation", result["forbidden_shortcuts"])

    def test_transaction_defect_precedes_algorithm_change(self):
        result = recommend_minimal_repair(
            amplification_detected=True,
            time_layers_passed=False,
            force_transaction_passed=True,
            checkpoint_passed=True,
        )
        self.assertEqual(result["action"], "repair_time_layer_transaction")
        self.assertFalse(result["new_authorization_required"])


if __name__ == "__main__":
    unittest.main()
