import math
import unittest

from src.coupling.stage4f_lowre_benchmark_design_v2.benchmark import (
    LowReContract,
    corrected_beta_screen,
)


class CorrectedContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = LowReContract()

    def test_slenderness_and_reynolds_number(self):
        self.assertEqual(self.contract.slenderness_ratio, 50.0)
        self.assertEqual(self.contract.reynolds_number, 100.0)

    def test_reduced_velocity_target(self):
        self.assertEqual(self.contract.Ur1_target, 5.5)
        self.assertAlmostEqual(self.contract.target_wet_frequency_Hz, 1.0 / 5.5, places=15)

    def test_annulus_area_and_second_moment(self):
        self.assertAlmostEqual(self.contract.area_m2, math.pi * 0.19 / 4.0, places=15)
        self.assertAlmostEqual(self.contract.second_moment_m4, math.pi * (1.0 - 0.9**4) / 64.0, places=15)

    def test_t_over_ea_formula_and_beta_screen(self):
        screen = corrected_beta_screen(self.contract)
        self.assertEqual([item["passes"] for item in screen["candidates"]], [False, True, True])
        self.assertAlmostEqual(screen["candidates"][0]["T_over_EA"], 0.04525, places=14)
        self.assertAlmostEqual(screen["candidates"][1]["T_over_EA"], 0.004525, places=14)
        self.assertAlmostEqual(screen["candidates"][2]["T_over_EA"], 0.000905, places=14)

    def test_mass_ratio_and_explicit_wet_mass(self):
        for ratio in (2, 5, 10):
            item = self.contract.mass_candidate(ratio)
            self.assertAlmostEqual(item["m_s_kgpm"], ratio * item["m_f_kgpm"], places=12)
            self.assertAlmostEqual(item["m_eff_kgpm"], item["m_s_kgpm"] + item["m_added_kgpm"], places=12)
            self.assertIn("M_added", item["mass_matrix_construction"])


if __name__ == "__main__":
    unittest.main()

