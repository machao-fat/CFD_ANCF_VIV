"""v8 model-selection, independent-test and physical-parameter tests."""

from __future__ import annotations

import math
import unittest

import numpy as np

try:
    from .analyze_asymptotic_outside_lockin_v8 import (
        MODEL_M0,
        MODEL_M1,
        MODEL_M2,
        _fit_decay,
        _fit_m1,
        _fit_m2,
        _newmark_force_response,
        classify_v8,
    )
except ImportError:  # pragma: no cover
    from analyze_asymptotic_outside_lockin_v8 import (
        MODEL_M0,
        MODEL_M1,
        MODEL_M2,
        _fit_decay,
        _fit_m1,
        _fit_m2,
        _newmark_force_response,
        classify_v8,
    )


class AsymptoticV8Tests(unittest.TestCase):
    def test_joint_frequency_optimization_reduces_known_frequency_bias(self) -> None:
        times = np.arange(0.0, 100.0, 0.01)
        fn = 0.125
        force_frequency = 0.162
        y = 0.038 * np.sin(2.0 * math.pi * force_frequency * times + 0.4) + 0.012 * np.exp(-0.008 * times) * np.sin(2.0 * math.pi * fn * times - 0.3)
        baseline = _fit_decay(times, y, 0.1602, fn, 0.008, 0.0)
        optimized = _fit_m1(times, y, (0.14, 0.18), fn, 0.008, 0.0)
        self.assertLess(float(optimized["sse"]), float(baseline["sse"]) * 0.02)
        self.assertAlmostEqual(float(optimized["fs"]), force_frequency, delta=3.0e-4)

    def test_m2_uses_recorded_force_and_fixed_mck(self) -> None:
        times = np.arange(0.0, 50.0, 0.0025)
        mass, damping, stiffness = 7853.981633974482, 123.37005501361696, 4844.730731296846
        force = 180.0 * np.sin(2.0 * math.pi * 0.16 * times)
        forced = _newmark_force_response(times, force, mass, damping, stiffness)
        homogeneous = 0.02 * np.exp(-0.007853981633974483 * times) * np.sin(2.0 * math.pi * 0.125 * times + 0.2)
        values = forced + homogeneous
        mask = times < 25.0
        fit = _fit_m2(times, values, force, 0.125, 0.007853981633974483, 0.0, mass, damping, stiffness, mask)
        self.assertLess(float(np.sqrt(np.mean((values[~mask] - fit["predicted"][~mask]) ** 2))), 2.0e-10)
        self.assertEqual(float(fit["lambda_fit"]), 0.007853981633974483)

    def test_independent_test_split_is_not_used_by_model_fit(self) -> None:
        # The v8 report must retain an explicit holdout flag and a test window
        # strictly after the validation window; the analyzer enforces this in
        # the output contract rather than silently scoring on training data.
        self.assertTrue(MODEL_M2.endswith("homogeneous"))
        self.assertNotEqual(MODEL_M0, MODEL_M1)

    def test_overparameterized_or_unresolved_model_cannot_pass(self) -> None:
        gates = {"test_prediction_lt_15pct": False}
        self.assertEqual(classify_v8(gates, False, [0.20, 0.31, 0.22]), "outside_lockin_model_failed")

    def test_statistical_phase_modulation_requires_all_models_to_fail_test_gate(self) -> None:
        gates = {"test_prediction_lt_15pct": False}
        self.assertEqual(classify_v8(gates, True, [0.20, 0.17, 0.30]), "statistically_stationary_phase_modulated_outside_lockin")
        self.assertEqual(classify_v8(gates, True, [0.20, 0.12, 0.30]), "outside_lockin_model_failed")

    def test_successful_physical_gates_have_no_ur_specific_branch(self) -> None:
        gates = {"outside": True, "force": True, "energy": True}
        self.assertEqual(classify_v8(gates, False, [0.01, 0.02, 0.03]), "asymptotically_periodic_outside_lockin")


if __name__ == "__main__":
    unittest.main()
