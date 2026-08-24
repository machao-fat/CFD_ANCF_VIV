import hashlib
import json
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "08_stage4e_physical_baseline_v3_1"
V3 = ROOT / "results" / "08_stage4e_physical_baseline_v3"


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


class Stage4EV31Tests(unittest.TestCase):
    def test_protocol_and_source_pin(self):
        x = load("source_pin_and_hash.json")
        self.assertEqual(x["commit_sha"], "fe251f958ddf2f083b53cdb53a9d2addde85e17e")
        self.assertTrue(x["csv_hash_match"])
        self.assertTrue(x["main1_hash_match"])
        self.assertTrue(x["archive_download_verified"])
        self.assertFalse(x["raw_csv_written_to_project"])

    def test_il2_bandpass_is_not_strict_amplitude(self):
        x = load("amplitude_robustness_classification.json")
        self.assertGreater(x["explicit_IL2_bandpass_relative_RMS_span"], 0.10)
        self.assertEqual(x["target_classification"]["IL_mode_2"]["q_RMS_class_five_bandpass"], "not_strict_amplitude")

    def test_frequency_and_mode_remain_usable(self):
        x = load("amplitude_robustness_classification.json")
        for name in ("CF_mode_1", "IL_mode_2", "IL_mode_4"):
            self.assertTrue(x["target_classification"][name]["frequency_valid"])
            self.assertTrue(x["target_classification"][name]["mode_identity_stable"])

    def test_rms_peak_fields_are_distinct(self):
        x = load("corrected_amplitude_semantics.json")
        for label in ("CF", "IL"):
            y = x[label]
            for key in ("max_span_rms_m", "max_span_rms_over_D", "max_instantaneous_peak_abs_m", "max_instantaneous_peak_abs_over_D", "rms_peak_location_m", "instantaneous_peak_location_m", "amplitude_definition"):
                self.assertIn(key, y)
            self.assertNotEqual(y["max_span_rms_m"], y["max_instantaneous_peak_abs_m"])
            self.assertTrue(y["amplitude_definition"]["comparison_field_for_paper_RMS_curve"] == "max_span_rms_over_D")

    def test_nominal_amplitude_values(self):
        x = load("corrected_amplitude_semantics.json")
        self.assertAlmostEqual(x["CF"]["max_span_rms_over_D"], 0.245, delta=0.01)
        self.assertAlmostEqual(x["CF"]["max_instantaneous_peak_abs_over_D"], 0.646, delta=0.01)
        self.assertAlmostEqual(x["IL"]["max_span_rms_over_D"], 0.0545, delta=0.005)
        self.assertAlmostEqual(x["IL"]["max_instantaneous_peak_abs_over_D"], 0.228, delta=0.01)

    def test_formal_h_function_called_but_blocked_without_modal_dofs(self):
        x = load("formal_H_projection_8_vs_16.json")
        self.assertTrue(x["formal_H_function_called"])
        self.assertFalse(x["modal_state_source_available"])
        self.assertEqual(x["status"], "blocked_formal_modal_state_unavailable")
        self.assertFalse(x["decision"]["formal_projection_pass"])
        self.assertFalse(x["legacy_201_point_normalized_shape_used_as_formal_H_evidence"])
        self.assertEqual(sorted(x["nElem_compared"]), [8, 16])

    def test_h_call_dimensions(self):
        x = load("formal_H_projection_8_vs_16.json")
        for row in x["H_contract_sanity_calls"]:
            self.assertEqual(row["shape"][0], 3)
            self.assertEqual(row["shape"][1], 6 * (row["nElem"] + 1))
            self.assertEqual(row["nonzero_count"], 3 if abs(row["row_sum"][0] - 1.0) < 1e-12 else 12)

    def test_zero_crossing_is_detected(self):
        x = load("zero_crossing_constrained_slice_design.json")
        root = x["zero_crossing"]["depth_fraction"]
        self.assertAlmostEqual(root, 0.4742907801, places=8)
        constrained = x["candidates"]["zero_crossing_constrained_5"]
        self.assertEqual(len(constrained["slice_lengths_m"]), 5)
        self.assertTrue(constrained["root_on_boundary"])
        self.assertFalse(constrained["crosses_zero"])
        self.assertTrue(all(v > 0 for v in constrained["slice_lengths_m"]))

    def test_current_v3_candidate_is_not_frozen(self):
        x = load("zero_crossing_constrained_slice_design.json")
        current = x["candidates"]["current_v3_optimized_5"]
        self.assertTrue(current["crosses_zero"])
        self.assertFalse(current["root_on_boundary"])

    def test_modal_weighted_loads_use_delta_s_once(self):
        x = load("modal_weighted_load_errors.json")
        for name, row in x["candidates"].items():
            self.assertTrue(row["delta_s_applied_once"])
            self.assertEqual(set(row["modal_weighted_loads"]), {"1", "2", "4"})
            for modal in row["modal_weighted_loads"].values():
                self.assertIn("Q_m_drag_signed_relative_error", modal)
                self.assertIn("Q_m_drag_normalized_absolute_error", modal)
                self.assertIn("Q_m_magnitude_signed_relative_error", modal)
                self.assertIn("Q_m_magnitude_normalized_absolute_error", modal)

    def test_fixed_boundary_uncertainty(self):
        x = load("profile_uncertainty_robustness.json")
        self.assertEqual(x["sample_count"], 1000)
        self.assertEqual(x["random_seed"], 20260812)
        self.assertTrue(x["fixed_boundaries_not_reoptimized"])
        self.assertEqual(x["criteria"]["p95_global_error_max"], 0.05)
        self.assertEqual(x["criteria"]["p95_modal_weighted_error_max"], 0.10)
        for method in ("linear", "pchip"):
            for row in x["summary_by_method"][method].values():
                self.assertEqual(row["direction_classification_changed_count"], 0)

    def test_no_openfoam_and_no_raw_csv(self):
        x = load("stage4e_a_v3_1_final_candidate_summary.json")
        self.assertTrue(x["no_openfoam_started"])
        self.assertTrue(x["no_raw_csv_saved"])
        self.assertEqual(x["schema_version"], "0.2.1")

    def test_v3_read_only_hashes_are_present(self):
        x = load("stage4e_a_v3_1_final_candidate_summary.json")
        self.assertEqual(len(x["v3_read_only_hashes"]), 5)
        for digest in x["v3_read_only_hashes"].values():
            self.assertEqual(len(digest), 64)
            int(digest, 16)

    def test_gate_is_not_passed(self):
        x = load("stage4e_a_v3_1_final_candidate_summary.json")
        self.assertEqual(x["gate_recommendation"], "建议不通过")
        self.assertEqual(x["target_mesh_recommendation"], "none_not_frozen_until_formal_H_projection")


if __name__ == "__main__":
    unittest.main()
