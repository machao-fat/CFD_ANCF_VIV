from __future__ import annotations

import unittest

from coupling.performance_optimization_v2.attribution import attribute_measurements


class AttributionTests(unittest.TestCase):
    def test_weights_and_interaction(self):
        measurements = {
            "B": [100.0, 102.0], "M": [90.0, 91.0], "O": [95.0], "P": [92.0], "I": [99.0], "A": [98.0], "T": [97.0], "D": [100.0],
            "M+O": [82.0], "M+P": [80.0], "M+O+P": [65.0], "M+O+P+I": [63.0], "M+O+P+I+A": [60.0],
            "O+P+I+A+T+D": [70.0], "M+P+I+A+T+D": [69.0], "M+O+I+A+T+D": [68.0],
            "M+O+P+A+T+D": [67.0], "M+O+P+I+T+D": [66.0], "M+O+P+I+A+D": [65.0],
            "M+O+P+I+A+T": [64.0], "FINAL": [58.0, 59.0],
            "FINAL_FACTORS": ("M", "O", "P", "I", "A", "T", "D"),
        }
        result = attribute_measurements(measurements)
        self.assertAlmostEqual(result.baseline_median_s, 101.0)
        self.assertEqual(sum(result.normalized_weight.values()), 1.0)
        self.assertIn("M+O", result.interactions)

    def test_missing_final_is_fail_closed(self):
        with self.assertRaises(ValueError): attribute_measurements({"B": 10.0})
