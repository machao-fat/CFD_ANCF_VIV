from __future__ import annotations

import math
import unittest

from tests.sdof.analyze_campaign import dominant_frequency, zero_crossing_frequency


class ZeroCrossingFrequencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frequency_hz = 0.2
        self.times = [i * 0.0025 for i in range(0, 10001)]

    def assert_frequency(self, values: list[float]) -> None:
        estimate = zero_crossing_frequency(values, self.times)
        self.assertLess(abs(estimate - self.frequency_hz) / self.frequency_hz, 0.01)
        self.assertNotAlmostEqual(estimate, 0.4, delta=0.01)

    def test_standard_sine(self) -> None:
        self.assert_frequency([math.sin(2.0 * math.pi * self.frequency_hz * t) for t in self.times])

    def test_constant_offset(self) -> None:
        self.assert_frequency([1.75 + math.sin(2.0 * math.pi * self.frequency_hz * t) for t in self.times])

    def test_linear_drift(self) -> None:
        self.assert_frequency([0.2 * t + math.sin(2.0 * math.pi * self.frequency_hz * t) for t in self.times])

    def test_small_deterministic_noise(self) -> None:
        values = [
            math.sin(2.0 * math.pi * self.frequency_hz * t)
            + 0.003 * math.sin(2.0 * math.pi * 1.7 * t)
            for t in self.times
        ]
        self.assert_frequency(values)

    def test_two_harmonics_keep_the_fundamental(self) -> None:
        values = [
            math.sin(2.0 * math.pi * self.frequency_hz * t)
            + 0.4 * math.sin(2.0 * math.pi * 2.0 * self.frequency_hz * t)
            for t in self.times
        ]
        estimate = dominant_frequency(values, 0.0025)
        self.assertLess(abs(estimate - self.frequency_hz) / self.frequency_hz, 0.01)
        self.assertNotAlmostEqual(estimate, 0.4, delta=0.01)


if __name__ == "__main__":
    unittest.main()
