from __future__ import annotations

import math
import unittest

try:
    from .analyze_campaign import frequency_reliable, zero_crossing_frequency
    from .analyze_response_cycle_aligned_v6 import dft_frequency, positive_crossings
    from .lockin_classification_v6 import classify_lockin
except ImportError:  # Direct execution from tests/sdof remains supported.
    from analyze_campaign import frequency_reliable, zero_crossing_frequency
    from analyze_response_cycle_aligned_v6 import dft_frequency, positive_crossings
    from lockin_classification_v6 import classify_lockin


class ResponseCycleV6Tests(unittest.TestCase):
    def test_response_period_is_measured_from_positive_crossings(self) -> None:
        dt = 0.0025
        times = [i * dt for i in range(int(80.0 / dt) + 1)]
        values = [0.2 * math.sin(2.0 * math.pi * 0.2 * t) for t in times]
        crossings = positive_crossings(values, times)
        self.assertGreaterEqual(len(crossings), 15)
        self.assertAlmostEqual(1.0 / statistics_mean_diff(crossings), 0.2, delta=0.002)
        self.assertAlmostEqual(dft_frequency(values, times), 0.2, delta=0.003)

    def test_dft_and_zero_crossing_agree_after_offset_and_drift(self) -> None:
        dt = 0.0025
        times = [i * dt for i in range(int(80.0 / dt) + 1)]
        values = [0.2 * math.sin(2.0 * math.pi * 0.2 * t) + 0.05 + 0.0002 * t for t in times]
        self.assertAlmostEqual(zero_crossing_frequency(values, times), 0.2, delta=0.002)
        self.assertAlmostEqual(dft_frequency(values, times), 0.2, delta=0.003)

    def test_window_frequency_is_not_doubled(self) -> None:
        dt = 0.0025
        times = [i * dt for i in range(int(60.0 / dt) + 1)]
        values = [0.2 * math.sin(2.0 * math.pi * 0.2 * t) for t in times]
        frequency = zero_crossing_frequency(values, times)
        self.assertLess(abs(frequency - 0.2) / 0.2, 0.01)
        self.assertNotAlmostEqual(frequency, 0.4, delta=0.01)

    def test_lockin_positive_power_and_positive_phase_cosine(self) -> None:
        result = classify_lockin(
            final_steady_window_pass=True, frequency_state="frequency_synchronized",
            response_frequency_reliable=True, y_rms_m=0.4, amplitude_baseline_m=0.02,
            mean_power_W=10.0, force_velocity_phase_deg=-57.0,
            power_noise_floor_W=0.5,
        )
        self.assertEqual(result, "locked_or_near_lockin")

    def test_lockin_never_uses_nan_phase_as_positive_input(self) -> None:
        result = classify_lockin(
            final_steady_window_pass=True, frequency_state="frequency_synchronized",
            response_frequency_reliable=True, y_rms_m=0.4, amplitude_baseline_m=0.02,
            mean_power_W=10.0, force_velocity_phase_deg=float("nan"),
            power_noise_floor_W=0.5,
        )
        self.assertEqual(result, "outside_lockin")

    def test_unsteady_and_low_power_states_are_not_lockin(self) -> None:
        self.assertEqual(classify_lockin(
            final_steady_window_pass=False, frequency_state="frequency_synchronized",
            response_frequency_reliable=True, y_rms_m=0.4, amplitude_baseline_m=0.02,
            mean_power_W=10.0, force_velocity_phase_deg=0.0, power_noise_floor_W=0.5,
        ), "transitional_or_unsteady")
        self.assertEqual(classify_lockin(
            final_steady_window_pass=True, frequency_state="outside_frequency_sync",
            response_frequency_reliable=True, y_rms_m=0.1, amplitude_baseline_m=0.02,
            mean_power_W=0.1, force_velocity_phase_deg=0.0, power_noise_floor_W=0.5,
        ), "outside_lockin")

    def test_quasi_periodic_classification_requires_stationarity(self) -> None:
        self.assertEqual(classify_lockin(
            final_steady_window_pass=True, frequency_state="frequency_synchronized",
            response_frequency_reliable=True, y_rms_m=0.2, amplitude_baseline_m=0.02,
            mean_power_W=1.0, force_velocity_phase_deg=0.0, power_noise_floor_W=0.5,
            quasi_periodic=True,
        ), "quasi_periodic_or_multifrequency")


def statistics_mean_diff(values: list[float]) -> float:
    return sum(b - a for a, b in zip(values, values[1:])) / (len(values) - 1)


if __name__ == "__main__":
    unittest.main()
