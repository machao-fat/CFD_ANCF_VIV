import json
import pathlib
import sys
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.coupling.stage4e_route1_plus_2_v2_3_1.authorization import (
    S_INPUT,
    authorize_scenario_s,
    validate_s_input_contract,
)


class ScenarioSAuthorizationTests(unittest.TestCase):
    def test_low_amplitude_n_authorizes_s(self):
        result = authorize_scenario_s("rejected_low_amplitude", True)
        self.assertTrue(result["authorized"])

    def test_transition_not_activated_n_authorizes_s(self):
        result = authorize_scenario_s("transition_not_activated", True)
        self.assertTrue(result["authorized"])

    def test_stable_evaluable_n_rejects_s(self):
        result = authorize_scenario_s("stable_evaluable", True)
        self.assertFalse(result["authorized"])

    def test_source_failure_rejects_s(self):
        result = authorize_scenario_s("rejected_low_amplitude", False)
        self.assertFalse(result["authorized"])

    def test_second_s_run_rejected(self):
        result = authorize_scenario_s("rejected_low_amplitude", True, scenario_count=1)
        self.assertFalse(result["authorized"])

    def test_fine_request_rejected(self):
        result = authorize_scenario_s("rejected_low_amplitude", True, fine_requested=True)
        self.assertFalse(result["authorized"])

    def test_s_contract_is_exactly_frozen(self):
        self.assertTrue(validate_s_input_contract(S_INPUT)["passed"])

    def test_s_contract_rejects_fitted_velocity(self):
        values = dict(S_INPUT)
        values["Tu_percent"] += 0.01
        self.assertFalse(validate_s_input_contract(values)["passed"])

    def test_contract_reports_missing_values(self):
        values = dict(S_INPUT)
        values.pop("omega_1ps")
        result = validate_s_input_contract(values)
        self.assertFalse(result["passed"])
        self.assertIn("omega_1ps", result["mismatches"])

    def test_old_v2_3_source_audit_and_n_status_authorize_s(self):
        path = PROJECT_ROOT / "results" / "10_stage4e_route1_plus_2_v2_3" / "kOmegaSSTLM_source_audit.json"
        source = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(source["source_readable"])
        self.assertTrue(source["sha256_computable"])
        result = authorize_scenario_s("rejected_low_amplitude", True)
        self.assertTrue(result["authorized"])

    def test_corrected_result_records_s_authorized(self):
        result_dir = PROJECT_ROOT / "results" / "10_stage4e_route1_plus_2_v2_3_1"
        record = json.loads((result_dir / "corrected_sensitivity_authorization.json").read_text(encoding="utf-8"))
        self.assertTrue(record["S"]["authorized"])
        self.assertTrue(record["source_audit_passed"])

    def test_s_statistics_use_full_production_sample_count(self):
        result_dir = PROJECT_ROOT / "results" / "10_stage4e_route1_plus_2_v2_3_1"
        record = json.loads((result_dir / "scenario_s_statistics.json").read_text(encoding="utf-8"))
        self.assertEqual(record["samples"]["sample_count"], 14001)
        self.assertEqual(record["frequency_status"], "not_evaluable_low_amplitude")
        self.assertEqual(len(record["windows"]), 3)

    def test_force_crosscheck_passes(self):
        result_dir = PROJECT_ROOT / "results" / "10_stage4e_route1_plus_2_v2_3_1"
        record = json.loads((result_dir / "scenario_s_force_crosscheck.json").read_text(encoding="utf-8"))
        self.assertTrue(record["passed_1e-10"])
        self.assertEqual(record["matched_count"], record["sample_count_coeffs"])

    def test_yplus_final_is_finite_and_below_target(self):
        result_dir = PROJECT_ROOT / "results" / "10_stage4e_route1_plus_2_v2_3_1"
        record = json.loads((result_dir / "scenario_s_yplus.json").read_text(encoding="utf-8"))
        self.assertTrue(record["passed"])
        self.assertIn("9.0", record["endpoint_stats"])

    def test_checkpoint_lineage_is_strict_and_complete(self):
        result_dir = PROJECT_ROOT / "results" / "10_stage4e_route1_plus_2_v2_3_1"
        record = json.loads((result_dir / "scenario_s_checkpoint_lineage.json").read_text(encoding="utf-8"))
        self.assertTrue(record["strictly_increasing"])
        self.assertEqual(record["block_ends_s"], [2.0, 4.0, 6.0, 9.0])
        self.assertEqual(record["force_history_actual_sample_count"], 14001)

    def test_fine_is_not_authorized(self):
        result_dir = PROJECT_ROOT / "results" / "10_stage4e_route1_plus_2_v2_3_1"
        record = json.loads((result_dir / "fine_not_authorized.json").read_text(encoding="utf-8"))
        self.assertFalse(record["authorized"])
        self.assertFalse(record["run"])

    def test_parent_v2_3_hash_audit_has_no_mismatch(self):
        result_dir = PROJECT_ROOT / "results" / "10_stage4e_route1_plus_2_v2_3_1"
        record = json.loads((result_dir / "old_v2_3_evidence_hash_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(record["mismatches"], [])
        self.assertTrue(record["parent_identity_not_modified"])

    def test_process_cleanup_is_zero(self):
        result_dir = PROJECT_ROOT / "results" / "10_stage4e_route1_plus_2_v2_3_1"
        record = json.loads((result_dir / "process_cleanup_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(record["residual_count"], 0)
        self.assertEqual(record["started_count"], record["closed_count"])

    def test_all_v2_3_1_json_is_finite_and_utf8(self):
        result_dir = PROJECT_ROOT / "results" / "10_stage4e_route1_plus_2_v2_3_1"
        for path in result_dir.glob("*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(": NaN", text)
            self.assertNotIn(": Infinity", text)
            json.loads(text)


if __name__ == "__main__":
    unittest.main()
