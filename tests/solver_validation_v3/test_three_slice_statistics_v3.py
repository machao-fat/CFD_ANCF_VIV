"""Synthetic tests for V3 local statistics and phase-beating semantics."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.three_slice_statistics_v3.metrics import (  # noqa: E402
    SLICE_IDS, beat_diagnostic, cross_spectrum_at_targets, local_stationarity, signal_summary,
)


class ThreeSliceStatisticsV3Test(unittest.TestCase):
    def setUp(self) -> None:
        self.time = np.arange(0.0, 400.0, 0.05)

    def test_same_frequency_phase_lock_has_high_coherence(self) -> None:
        force = np.sin(2.0 * math.pi * 0.16 * self.time)
        displacement = 0.3 * np.sin(2.0 * math.pi * 0.16 * self.time - math.pi / 4.0)
        result = cross_spectrum_at_targets(self.time, force, displacement)
        target = result["targets"]["0.16_Hz"]
        self.assertGreater(float(target["coherence"]), 0.99)
        self.assertAlmostEqual(float(target["phase_deg_y_relative_to_left"]), -45.0, delta=5.0)

    def test_slight_frequency_difference_beats_without_local_instability(self) -> None:
        first = np.sin(2.0 * math.pi * 0.161 * self.time)
        second = np.sin(2.0 * math.pi * 0.163 * self.time)
        full = {"slices": {
            "slice_0000": {"Fy": signal_summary(self.time, first)},
            "slice_0001": {"Fy": signal_summary(self.time, second)},
            "slice_0002": {"Fy": signal_summary(self.time, first)},
        }}
        beat = beat_diagnostic(full)["slice_0000__slice_0001"]
        self.assertAlmostEqual(float(beat["delta_f_hz"]), 0.002, delta=2.0e-4)
        self.assertAlmostEqual(float(beat["estimated_beat_period_s"]), 500.0, delta=60.0)
        windows = []
        for start in (0.0, 50.0, 100.0):
            segment = self.time[(self.time >= start) & (self.time < start + 50.0)]
            windows.append({"slices": {
                "slice_0000": {"Fy": signal_summary(segment, np.sin(2.0 * math.pi * 0.161 * segment)), "y": signal_summary(segment, np.sin(2.0 * math.pi * 0.161 * segment))},
                "slice_0001": {"Fy": signal_summary(segment, np.sin(2.0 * math.pi * 0.163 * segment)), "y": signal_summary(segment, np.sin(2.0 * math.pi * 0.163 * segment))},
                "slice_0002": {"Fy": signal_summary(segment, np.sin(2.0 * math.pi * 0.161 * segment)), "y": signal_summary(segment, np.sin(2.0 * math.pi * 0.161 * segment))},
            }})
        stationarity = local_stationarity(windows)
        self.assertEqual(stationarity["status"], "pass")
        self.assertGreater(float(beat["phase_drift_deg_over_50s_from_delta_f"]), 30.0)


if __name__ == "__main__":
    unittest.main()
