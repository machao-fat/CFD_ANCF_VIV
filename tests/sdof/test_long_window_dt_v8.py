"""Unit tests for v8 same-checkpoint and response-cycle window rules."""

from __future__ import annotations

import unittest

import numpy as np

try:
    from .analyze_long_window_dt_v8 import _boundary_rows, _last_five_cycle_window, _relative
except ImportError:  # pragma: no cover
    from analyze_long_window_dt_v8 import _boundary_rows, _last_five_cycle_window, _relative


def rows_for(cycles: float, dt: float = 0.01) -> list[dict[str, float]]:
    times = np.arange(0.0, cycles * 5.0 + dt * 0.5, dt)
    values = np.sin(2.0 * np.pi * times / 5.0)
    return [{"time_s": float(t), "y_m": float(y), "step": int(round(t / dt)), "startup_fixed": 0} for t, y in zip(times, values)]


class LongWindowDtV8Tests(unittest.TestCase):
    def test_five_cycles_require_six_positive_crossings(self) -> None:
        with self.assertRaises(ValueError):
            _last_five_cycle_window(rows_for(1.5))

    def test_five_cycles_are_measured_from_positive_crossings(self) -> None:
        start, end, crossings = _last_five_cycle_window(rows_for(7.0))
        self.assertEqual(len(crossings), 6)
        self.assertAlmostEqual(end - start, 25.0, delta=0.25)

    def test_boundary_interpolation_preserves_requested_window(self) -> None:
        rows = rows_for(7.0)
        block = _boundary_rows(rows, 1.235, 26.235)
        self.assertAlmostEqual(block[0]["time_s"], 1.235)
        self.assertAlmostEqual(block[-1]["time_s"], 26.235)
        self.assertGreater(len(block), 1000)

    def test_relative_change_is_symmetric_scale_normalized(self) -> None:
        self.assertAlmostEqual(_relative(100.0, 104.0), 0.04)
        self.assertAlmostEqual(_relative(-100.0, -104.0), 0.04)


if __name__ == "__main__":
    unittest.main()
