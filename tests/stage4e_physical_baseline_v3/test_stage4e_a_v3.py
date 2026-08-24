from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "08_stage4e_physical_baseline_v3"
SRC = ROOT / "src" / "coupling" / "stage4e_physical_baseline_v3" / "audit_vivdatashare_v3.py"


def read(name: str):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


class Stage4EAV3Tests(unittest.TestCase):
    def test_v3_artifacts_and_source_identity(self):
        self.assertTrue(SRC.is_file())
        d = read("source_identity_v3.json")
        self.assertEqual(d["schema_version"], "0.2.1")
        self.assertEqual(d["csv_sha256"], "507b6aadcda9437350c5035db384e7fbbbc0ebe708a6554df851c10498c743df")
        self.assertFalse(d["raw_csv_written_to_project"])
        self.assertFalse(d["real_cfd_started"])

    def test_correct_formula_and_manufactured_solution(self):
        d = read("corrected_units_and_formula.json")
        self.assertEqual(d["formula"]["epsilon"], "raw_microstrain*1e-6*(D/D1)")
        self.assertEqual(d["formula"]["q"], "pinv(A)@epsilon")
        self.assertEqual(d["units"]["q"], "m")
        self.assertTrue(d["manufactured_solution"]["status"] == "pass")
        for case in d["manufactured_solution"]["cases"].values():
            self.assertLessEqual(case["q_relative_error"], 1e-10)
            self.assertLessEqual(case["y_relative_error"], 1e-10)
        self.assertFalse(d["v2_forbidden_post_inverse_scaling_used"])
        self.assertFalse("displacement = basis @ coeff.T / (R * 1e6)" in SRC.read_text(encoding="utf-8"))

    def test_inverse_conditioning(self):
        d = read("modal_inverse_conditioning.json")
        for label, shape, rank in (("CF", [9, 8], 8), ("IL", [14, 13], 13)):
            self.assertEqual(d[label]["shape"], shape)
            self.assertEqual(d[label]["numerical_rank"], rank)
            self.assertGreater(d[label]["condition_number"], 1.0)
            self.assertEqual(len(d[label]["singular_values"]), rank)
            self.assertGreater(d[label]["high_order_noise_risk"]["largest_inverse_gain"], 1.0)

    def test_corrected_observables_have_meter_units(self):
        d = read("corrected_observables_v048.json")
        self.assertTrue(d["not_author_bpass_reproduction"])
        self.assertEqual(d["CF"]["q_units"], "m")
        self.assertEqual(d["IL"]["y_units"], "m")
        self.assertGreater(d["CF"]["span_rms_max_m"], 1e-4)
        self.assertGreater(d["IL"]["span_rms_max_m"], 1e-4)
        self.assertLess(d["CF"]["max_A_over_D"], 10.0)
        self.assertLess(d["IL"]["max_A_over_D"], 10.0)
        self.assertEqual(d["CF"]["mode_stats"][0]["mode"], 1)
        self.assertEqual(d["IL"]["mode_stats"][1]["mode"], 2)
        self.assertEqual(d["IL"]["mode_stats"][3]["mode"], 4)

    def test_filter_robustness_protocols(self):
        d = read("filter_robustness.json")
        self.assertFalse(d["author_bpass_available"])
        self.assertEqual(len(d["filters"]), 6)
        self.assertEqual(d["selected_project_protocol"], "butterworth_order4_0p01_20_zero_phase")
        for label in ("CF", "IL2", "IL4"):
            entries = d["target_comparison"][label]
            self.assertEqual(len(entries), 6)
            self.assertTrue(all(e["frequency_Hz"] is not None for e in entries))

    def test_target_mesh_thresholds(self):
        d = read("corrected_target_mesh.json")
        self.assertTrue(d["decision"]["pass"])
        self.assertEqual(d["decision"]["minimum_production_nElem"], 8)
        self.assertEqual(d["decision"]["recommended_reference_nElem"], 16)
        for result in d["comparison_nElem8_vs_nElem16"].values():
            self.assertLessEqual(result["wet_frequency_relative_change"], 0.02)
            self.assertGreaterEqual(result["subspace_MAC_min"], 0.95)
            self.assertLessEqual(result["physical_H_shape_relative_difference_max"], 0.01)

    def test_slice_freeze_rule(self):
        d = read("optimized_slice_design.json")
        self.assertTrue(d["uniform_5_not_frozen"])
        self.assertGreater(d["uniform"]["5"]["relative_errors"]["int_U2_relative_error"], 0.02)
        self.assertTrue(d["optimized_nonuniform_5"]["freeze_pass"])
        self.assertEqual(d["recommendation"], "optimized_nonuniform_5")
        self.assertLessEqual(d["optimized_nonuniform_5"]["relative_errors"]["int_abs_U_relative_error"], 0.02)
        self.assertLessEqual(d["optimized_nonuniform_5"]["relative_errors"]["int_U2_relative_error"], 0.02)
        self.assertLessEqual(d["optimized_nonuniform_5"]["relative_errors"]["int_U_absU_relative_error"], 0.05)

    def test_rotation_contract(self):
        d = read("signed_rotation_contract_candidate.json")
        self.assertEqual(d["status"], "pass")
        self.assertEqual(d["negative_flow_candidate"]["det"], 1.0)
        self.assertTrue(d["negative_flow_candidate"]["orthogonal"])
        self.assertEqual(d["negative_flow_candidate"]["local_plus_x_global"], [-1.0, 0.0, 0.0])
        self.assertLessEqual(d["max_virtual_work_relative_error"], 1e-12)
        self.assertFalse(d["reflection_det_minus_one_used"])

    def test_final_summary_is_not_real_cfd(self):
        d = read("stage4e_a_v3_final_candidate_summary.json")
        self.assertTrue(d["v3_implemented"])
        self.assertFalse(d["real_cfd_started"])
        self.assertEqual(d["status"], "completed_offline_only")


if __name__ == "__main__":
    unittest.main()
