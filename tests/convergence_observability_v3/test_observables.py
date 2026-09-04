import unittest

from src.coupling.convergence_observability_v3 import (
    AuditError,
    audit_identity_rows,
    audit_quality_records,
    positive_peaks,
    validate_observability_contract,
)


class ObservabilityV3Tests(unittest.TestCase):
    def test_negative_local_maximum_is_rejected(self):
        times = [float(i) for i in range(18)]
        values = [0.0, 1.0, 0.0, -1.0, -0.2, -1.0, 0.0, 1.1, 0.0, -1.0, -0.1, -1.0, 0.0, 0.9, 0.0, -1.0, 0.0, 0.0]
        peaks = positive_peaks(times, values, minimum_separation_s=4.0)
        self.assertEqual([peak["time_s"] for peak in peaks], [1.0, 7.0, 13.0])

    def test_nonfinite_and_nonmonotonic_stream_fail_closed(self):
        with self.assertRaises(AuditError):
            positive_peaks([0.0, 1.0, 0.5], [0.0, 1.0, 0.0])
        with self.assertRaises(AuditError):
            positive_peaks([0.0, 1.0, 2.0], [0.0, float("nan"), 0.0])

    def test_identity_rejects_tick_mismatch_duplicate_and_slice_mismatch(self):
        row = {"global_step": 101, "case_local_bridge_step": 1, "time_s": 1.0, "integer_tick": 1000000000, "interface_positions_xy": [[0, 0], [0, 0], [0, 0]]}
        good = audit_identity_rows([row], source_global_step=100, dt_s=0.1)
        self.assertEqual(good["status"], "pass")
        bad = dict(row, integer_tick=999)
        self.assertEqual(audit_identity_rows([bad], source_global_step=100, dt_s=0.1)["status"], "do_not_pass")
        self.assertEqual(audit_identity_rows([row, row], source_global_step=100, dt_s=0.1)["status"], "do_not_pass")
        self.assertEqual(audit_identity_rows([dict(row, interface_positions_xy=[[0, 0]])], source_global_step=100, dt_s=0.1)["status"], "do_not_pass")

    def test_missing_terminal_courant_fails_without_interpolation(self):
        records = [{"time_s": 0.1, "courant_max": 0.5, "residual_max": 0.01, "continuity_global": 0.0, "iterations_max": 2}, {"time_s": 0.2, "residual_max": 0.01, "continuity_global": 0.0, "iterations_max": 2}]
        audit = audit_quality_records(records, expected_times=[0.1, 0.2])
        self.assertEqual(audit["status"], "do_not_pass")
        self.assertFalse(audit["checks"]["required_fields"])

    def test_time_mismatch_and_nan_quality_fail_closed(self):
        record = {"time_s": 0.1001, "courant_max": 0.5, "residual_max": 0.01, "continuity_global": 0.0, "iterations_max": 2}
        self.assertEqual(audit_quality_records([record], expected_times=[0.1])["status"], "do_not_pass")
        record["time_s"] = 0.1
        record["courant_max"] = float("inf")
        self.assertEqual(audit_quality_records([record], expected_times=[0.1])["status"], "do_not_pass")

    def test_short_window_contract_requires_terminal_quality_and_process_guard(self):
        contract = {
            "schema_version": 1,
            "identity_fields": ["run_id", "case_id", "slice_id", "global_step", "case_local_bridge_step", "time_s", "integer_tick", "request_id", "transaction_id"],
            "quality_fields": ["time_s", "courant_max", "residual_max", "continuity_global", "iterations_max"],
            "slice_ids": ["slice_0000", "slice_0001", "slice_0002"],
            "terminal_quality_required": True,
            "missing_value_policy": "fail_closed_no_interpolation",
            "finite_required": True,
            "real_process_allowed": False,
            "preserve_formal_status": True,
        }
        self.assertEqual(validate_observability_contract(contract)["status"], "pass")
        self.assertEqual(validate_observability_contract(dict(contract, terminal_quality_required=False))["status"], "do_not_pass")
        self.assertEqual(validate_observability_contract(dict(contract, real_process_allowed=True))["status"], "do_not_pass")


if __name__ == "__main__":
    unittest.main()
