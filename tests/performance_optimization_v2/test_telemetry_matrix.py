from __future__ import annotations

import unittest

from coupling.performance_optimization_v2.matrix import required_matrix, validate_matrix
from coupling.performance_optimization_v2.telemetry import StepTiming, TelemetryError, summarize_timings


class TelemetryTests(unittest.TestCase):
    def record(self, step: int, bridge: int) -> StepTiming:
        return StepTiming("run", "case", step, bridge, 2.2075 + bridge * .0025, 2207500000 + bridge * 2500000,
                          f"r{step}", f"t{step}", {name: .1 for name in ("matlab", "wsl", "openfoam", "ipc", "checkpoint_audit", "total")}, 123, {"0": 200, "1": 201, "2": 202}, {}, {"matlab": 0, "openfoam": 0}, 0)

    def test_contiguous_bridge_and_start_counts(self):
        summary = summarize_timings([self.record(560, 1), self.record(561, 2)])
        self.assertEqual(summary["steps"], 2); self.assertEqual(summary["matlab_start_count"], 1); self.assertEqual(summary["openfoam_start_count"], 3)

    def test_gap_rejected(self):
        with self.assertRaises(TelemetryError): summarize_timings([self.record(560, 1), self.record(562, 3)])

    def test_matrix_is_complete(self):
        validate_matrix(item.label for item in required_matrix())
