import unittest
from src.coupling.stage4f_c_numerical_stability_diagnostic_v1.diagnostic import *

class TestDiagnostic(unittest.TestCase):
    def test_repair2_first_failure(self):
        result = diagnose([
            {"max_abs_Cd": 2.68, "max_velocity_consistency_error": .003, "max_cfl": .14, "signed_force": 1},
            {"max_abs_Cd": 3.25, "max_velocity_consistency_error": .007, "max_cfl": .14, "signed_force": -1},
            {"max_abs_Cd": 11.003, "max_velocity_consistency_error": .0187, "max_cfl": .14, "signed_force": 1},
        ])
        self.assertEqual(result["first_hard_failure_index"], 2)
        self.assertTrue(result["alternating_growth_detected"])
    def test_d1_amplification(self):
        result = diagnose([
            {"max_abs_Cd": 4.25, "max_velocity_consistency_error": .0029, "max_cfl": .07, "signed_force": 1},
            {"max_abs_Cd": 7.96, "max_velocity_consistency_error": .0085, "max_cfl": .07, "signed_force": -1},
            {"max_abs_Cd": 22.95, "max_velocity_consistency_error": .0215, "max_cfl": .07, "signed_force": 1},
            {"max_abs_Cd": 346.65, "max_velocity_consistency_error": .339, "max_cfl": .08, "signed_force": -1},
        ])
        self.assertEqual(result["first_hard_failure_index"], 2)
        self.assertEqual(result["cd_failures"], [2, 3])
    def test_reject_nonfinite_and_cfl(self):
        with self.assertRaises(StabilityDiagnosticError): diagnose([{"max_abs_Cd":"NaN", "max_velocity_consistency_error":0, "max_cfl":.1}])
        with self.assertRaisesRegex(StabilityDiagnosticError, "CFL"): diagnose([{"max_abs_Cd":1, "max_velocity_consistency_error":0, "max_cfl":.8}])

if __name__ == "__main__": unittest.main()
