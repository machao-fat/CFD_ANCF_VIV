import unittest
from src.coupling.stage4f_c_numerical_stability_diagnostic_v1.relaxation_design import *

class TestRelaxationDesign(unittest.TestCase):
    raw = [35040.9, -65427.0, 188832.0, -446129.8, 1147458.4, -2849394.1]
    def test_alpha_is_explicit_and_reproducible(self):
        a = relaxed_sequence(self.raw, .25)
        self.assertEqual(a, relaxed_sequence(self.raw, .25))
        self.assertLess(abs(a[-1]), abs(self.raw[-1]))
    def test_alpha_bounds(self):
        with self.assertRaises(ValueError): relaxed_sequence(self.raw, 0.0)
        with self.assertRaises(ValueError): relaxed_sequence(self.raw, 1.1)
    def test_candidate_comparison(self):
        result = compare_alphas(self.raw, (.1, .25, .5, 1.0))
        self.assertEqual(len(result), 4)
        self.assertLess(result[0]["max_abs"], result[-1]["max_abs"])

if __name__ == "__main__": unittest.main()
