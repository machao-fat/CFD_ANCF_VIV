import json
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULT = ROOT / "results" / "11_stage4f_lowre_benchmark_design_v2"


def load(name):
    return json.loads((RESULT / name).read_text(encoding="utf-8"))


class StructuralResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inverse = load("inverse_structure_design.json")
        cls.selected = load("selected_structure_candidate.json")["candidate"]
        cls.eb = load("wet_modes_eb.json")
        cls.ancf = load("wet_modes_ancf.json")
        cls.cross = load("wet_mode_crosscheck.json")
        cls.mesh = load("structure_mesh_convergence.json")
        cls.static = load("static_initialization.json")

    def test_all_six_inverse_candidates_are_positive_and_finite(self):
        self.assertEqual(self.inverse["candidate_count"], 6)
        for item in self.inverse["candidates"]:
            for key in ("top_tension_N", "EI_Nm2", "E_Pa", "EA_N"):
                self.assertTrue(math.isfinite(item[key]) and item[key] > 0.0)
            self.assertLessEqual(item["T_over_EA"], 0.01)

    def test_selected_candidate_target_and_ur(self):
        self.assertTrue(self.selected["production_candidate_passed"])
        self.assertLessEqual(self.selected["target"]["eb_relative_error"], 0.01)
        self.assertLessEqual(self.selected["target"]["ancf_relative_error"], 0.01)
        self.assertGreaterEqual(self.selected["target"]["Ur1_ANCF"], 5.0)
        self.assertLessEqual(self.selected["target"]["Ur1_ANCF"], 6.0)

    def test_wet_modes_report_four_finite_frequencies(self):
        for document in (self.eb, self.ancf):
            self.assertTrue(document["wet_mass_explicit"])
            for candidate in document["candidates"]:
                for mesh in candidate["meshes"]:
                    frequency = mesh["modal"]["frequency_Hz"]
                    self.assertEqual(len(frequency), 4)
                    self.assertTrue(all(math.isfinite(value) and value > 0 for value in frequency))

    def test_ancf_eb_crosscheck(self):
        self.assertEqual(self.cross["status"], "passed")
        for candidate in self.cross["candidates"]:
            mesh32 = next(item for item in candidate["meshes"] if item["nElem"] == 32)
            self.assertLessEqual(mesh32["relative_frequency_difference"][0], 0.02)
            self.assertGreaterEqual(min(mesh32["MAC"]), 0.99)

    def test_nElem_16_32_convergence_and_mac(self):
        self.assertEqual(self.mesh["status"], "passed")
        self.assertEqual(self.mesh["formal_pair"], [16, 32])
        self.assertFalse(self.mesh["nElem_64_used"])
        for item in self.mesh["candidates"]:
            self.assertLessEqual(item["eb_relative_frequency_change"][0], 0.01)
            self.assertLessEqual(item["ancf_relative_frequency_change"][0], 0.01)
            self.assertGreaterEqual(min(item["eb_MAC"]), 0.99)
            self.assertGreaterEqual(min(item["ancf_MAC"]), 0.99)

    def test_eigen_residual_and_mass_orthogonality(self):
        for document in (self.eb, self.ancf):
            for candidate in document["candidates"]:
                mesh32 = next(item for item in candidate["meshes"] if item["nElem"] == 32)
                modal = mesh32["modal"]
                self.assertLessEqual(max(modal["eigen_residual"]), 1e-8)
                self.assertLessEqual(modal["mass_orthogonality_inf"], 1e-8)

    def test_static_initialization_and_checkpoint(self):
        for candidate in self.static["candidates"]:
            mesh32 = next(item for item in candidate["meshes"] if item["nElem"] == 32)
            audit = mesh32["audit"]
            if audit["passes"]:
                self.assertTrue(audit["converged"])
                self.assertTrue(audit["q_all_finite"])
                self.assertLessEqual(audit["maximum_green_strain"], 0.01)
                self.assertFalse(audit["large_range_negative_tension"])
                self.assertTrue(audit["checkpoint_passed"])


if __name__ == "__main__":
    unittest.main()

