from __future__ import annotations

import csv
import math
import tempfile
import unittest
from pathlib import Path

from tests.sdof.compare_dt import main, mean_time_integral, rms, time_window


class CompareDtTests(unittest.TestCase):
    def test_full_grid_rms_and_integral_are_independent_of_sampling_ratio(self) -> None:
        coarse = [{"time_s": i * 0.1, "y_m": math.sin(i * 0.1), "force_y_N": 2.0 * math.sin(i * 0.1), "instantaneous_power_W": 3.0} for i in range(11)]
        refined = [{"time_s": i * 0.05, "y_m": math.sin(i * 0.05), "force_y_N": 2.0 * math.sin(i * 0.05), "instantaneous_power_W": 3.0} for i in range(21)]
        a = time_window(coarse, 0.0, 1.0)
        b = time_window(refined, 0.0, 1.0)
        self.assertEqual(len(a), 11)
        self.assertEqual(len(b), 21)
        self.assertAlmostEqual(rms([row["y_m"] for row in a]), rms([row["y_m"] for row in b]), delta=0.01)
        self.assertAlmostEqual(mean_time_integral(a, "instantaneous_power_W"), 3.0, places=12)
        self.assertAlmostEqual(mean_time_integral(b, "instantaneous_power_W"), 3.0, places=12)

    def test_time_window_rejects_misaligned_or_nonmonotonic_data(self) -> None:
        with self.assertRaises(ValueError):
            time_window([{"time_s": 0.1, "y_m": 0.0}], 0.0, 1.0)
        with self.assertRaises(ValueError):
            time_window([{"time_s": 0.0, "y_m": 0.0}, {"time_s": 0.0, "y_m": 1.0}], 0.0, 0.0)


if __name__ == "__main__":
    unittest.main()
