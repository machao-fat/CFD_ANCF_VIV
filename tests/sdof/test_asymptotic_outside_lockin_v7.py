"""Unit tests for the v7 forced/free transient decomposition."""

from __future__ import annotations

import math
import unittest

import numpy as np

try:
    from .analyze_asymptotic_outside_lockin_v7 import _classification, _fit
except ImportError:
    from analyze_asymptotic_outside_lockin_v7 import _classification, _fit


class AsymptoticOutsideLockinTests(unittest.TestCase):
    def test_two_frequency_fit_recovers_decay_and_amplitudes(self) -> None:
        fs, fn = 0.2, 0.125
        lambda_theory = 0.01 * 2.0 * math.pi * fn
        decay = 1.1 * lambda_theory
        times = np.arange(0.0, 80.0, 0.01)
        forced = 0.035 * np.sin(2.0 * math.pi * fs * times + 0.31)
        free = 0.018 * np.exp(-decay * times) * np.sin(2.0 * math.pi * fn * times - 0.7)
        trend = 0.0002 + 2.0e-6 * times
        # Deterministic, small measurement noise keeps the test representative.
        noise = 2.0e-5 * np.sin(2.0 * math.pi * 0.037 * times)
        fit = _fit(times, trend + forced + free + noise, fs, fn, lambda_theory, 0.0)
        self.assertAlmostEqual(float(fit["As_m"]), 0.035, delta=3.0e-4)
        self.assertAlmostEqual(float(fit["An_m"]), 0.018, delta=1.0e-3)
        self.assertAlmostEqual(float(fit["lambda_fit"]), decay, delta=5.0e-4)
        self.assertGreater(float(fit["r_squared"]), 0.999)
        self.assertLess(float(fit["normalized_residual_rms"]), 0.02)

    def test_classifier_is_not_reduced_velocity_specific(self) -> None:
        kwargs = dict(
            response_ratio=0.70,
            force_frequency_stable=True,
            force_rms_change=0.01,
            lift_rms_change=0.01,
            forced_amplitude_change=0.01,
            lambda_fit=0.015,
            lambda_theory=0.016,
            free_tail_ratio=0.01,
            no_new_growth_frequency=True,
            fit_residual=0.03,
            prediction_residual=0.04,
            cfd_finite_pass=True,
            cfd_energy_pass=True,
            forced_power_W=0.1,
            energy_balance_pass=True,
            free_monotone=True,
        )
        self.assertTrue(_classification(**kwargs)["asymptotically_periodic_outside_lockin"])
        kwargs["lambda_fit"] = 0.0
        self.assertFalse(_classification(**kwargs)["asymptotically_periodic_outside_lockin"])


if __name__ == "__main__":
    unittest.main()
