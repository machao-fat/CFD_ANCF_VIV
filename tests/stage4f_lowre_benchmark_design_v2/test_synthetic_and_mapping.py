import json
import math
import unittest
from pathlib import Path

from src.coupling.multi_slice_mapping.mapping import SliceManifest


ROOT = Path(__file__).resolve().parents[2]
RESULT = ROOT / "results" / "11_stage4f_lowre_benchmark_design_v2"


def load(name):
    return json.loads((RESULT / name).read_text(encoding="utf-8"))


class SyntheticAndMappingTests(unittest.TestCase):
    def _stopped_mapping(self, label):
        return load(f"{label}_slice_mapping.json")["status"] == "not_run_due_stop_condition_8"

    def test_synthetic_load_and_responses_are_diagnostic_nonzero_finite(self):
        contract = load("synthetic_load_contract.json")
        eb = load("synthetic_response_eb.json")
        ancf = load("synthetic_response_ancf.json")
        comparison = load("synthetic_response_comparison.json")
        self.assertEqual(contract["classification"], "synthetic_load_diagnostic_only")
        self.assertTrue(contract["not_VIV_prediction"])
        self.assertEqual(len(eb["modal_scenarios"]), 12)
        for document in (eb, ancf):
            response = document["response"]
            self.assertGreater(response["maximum_displacement_m"], 0.0)
            self.assertTrue(response["final_state_finite"])
            self.assertTrue(all(math.isfinite(value) for value in response.values() if isinstance(value, float)))
        self.assertTrue(comparison["comparison"]["both_finite"])
        self.assertTrue(comparison["comparison"]["no_immediate_divergence"])

    def test_uniform_manifests_cover_50_m(self):
        for label, count in (("three", 3), ("five", 5), ("nine", 9)):
            raw = load(f"{label}_slice_manifest.json")
            if raw.get("not_a_protocol_manifest"):
                self.assertEqual(raw["artifact_status"], "not_frozen_due_stop_condition_8")
                self.assertEqual(raw["slice_count"], count)
                continue
            manifest = SliceManifest.from_mapping(raw)
            self.assertEqual(len(manifest.slices), count)
            self.assertAlmostEqual(sum(item.slice_length_m for item in manifest.slices), 50.0, places=12)
            self.assertEqual(manifest.R_GL, ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))

    def test_formal_H_Htranspose_and_interpolation(self):
        for label in ("three", "five", "nine"):
            document = load(f"{label}_slice_mapping.json")
            if document["status"] == "not_run_due_stop_condition_8":
                self.assertFalse(document["formal_mapping_called"])
                continue
            for mesh in document["mesh_results"].values():
                self.assertTrue(all(mesh["formal_calls"].values()))
                self.assertLessEqual(mesh["direct_H_max_abs_error"], 1e-15)
                self.assertLessEqual(mesh["cubic_H_interpolation_max_abs_error_m"], 1e-12)
                self.assertLessEqual(mesh["H_transpose_manual_max_abs_error_N"], 1e-12)
                self.assertTrue(mesh["slice_length_applied_exactly_once"])

    def test_virtual_work_and_order_invariance(self):
        virtual = load("virtual_work_audit.json")
        if virtual["status"] == "not_run_due_stop_condition_8":
            self.assertIsNone(virtual["maximum_absolute_or_relative_error"])
            return
        self.assertEqual(virtual["status"], "passed")
        self.assertLessEqual(virtual["maximum_absolute_or_relative_error"], 1e-12)
        for label in ("three", "five", "nine"):
            if self._stopped_mapping(label):
                continue
            for mesh in load(f"{label}_slice_mapping.json")["mesh_results"].values():
                self.assertLessEqual(mesh["order_shuffle_generalized_force_max_abs_error_N"], 1e-12)

    def test_missing_duplicate_and_nonfinite_rejected(self):
        for label in ("three", "five", "nine"):
            if self._stopped_mapping(label):
                document = load(f"{label}_slice_mapping.json")
                self.assertFalse(document["formal_mapping_called"])
                continue
            for mesh in load(f"{label}_slice_mapping.json")["mesh_results"].values():
                self.assertTrue(mesh["missing_slice_rejected"])
                self.assertTrue(mesh["duplicate_slice_id_rejected"])
                self.assertTrue(mesh["nonfinite_load_rejected"])

    def test_slice_count_changes_are_quantified(self):
        comparison = load("slice_count_comparison.json")
        if comparison["status"] == "not_run_due_stop_condition_8":
            self.assertIsNone(comparison["relative_change_3_to_5_first_modal_force"])
            self.assertIsNone(comparison["relative_change_5_to_9_first_modal_force"])
            self.assertEqual(comparison["next_real_CFD_default_slice_count_if_reauthorized"], 3)
            return
        self.assertTrue(math.isfinite(comparison["relative_change_3_to_5_first_modal_force"]))
        self.assertTrue(math.isfinite(comparison["relative_change_5_to_9_first_modal_force"]))
        self.assertEqual(comparison["next_real_CFD_default_slice_count"], 3)


if __name__ == "__main__":
    unittest.main()
