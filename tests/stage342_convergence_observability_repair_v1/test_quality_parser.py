from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from coupling.convergence_observability_v2 import OpenFOAMQualityError, OpenFOAMQualityParser


class QualityParserTests(unittest.TestCase):
    def test_pending_courant_is_assigned_to_next_time(self):
        parser = OpenFOAMQualityParser()
        lines = (
            "Courant Number mean: 0.01 max: 0.20",
            "Time = 0.005",
            "Solving for p, Initial residual = 1, Final residual = 1e-5, No Iterations 3",
            "continuity errors : sum local = 1e-8, global = -2e-10, cumulative = 0",
            "Courant Number mean: 0.02 max: 0.30",
            "Time = 0.010",
            "Solving for p, Initial residual = 1, Final residual = 2e-5, No Iterations 4",
            "continuity errors : sum local = 1e-8, global = 3e-10, cumulative = 0",
        )
        for line in lines:
            parser.feed(line)
        result = parser.finalize()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["courant_max"], 0.20)
        self.assertEqual(result[1]["courant_max"], 0.30)
        self.assertEqual(result[0]["iterations_max"], 3)

    def test_missing_quality_fails_closed(self):
        parser = OpenFOAMQualityParser()
        for line in (
            "Courant Number mean: 0.01 max: 0.20",
            "Time = 0.005",
            "Solving for p, Initial residual = 1, Final residual = 1e-5, No Iterations 3",
        ):
            parser.feed(line)
        with self.assertRaises(OpenFOAMQualityError):
            parser.finalize()

    def test_no_solver_records_fails_closed(self):
        with self.assertRaises(OpenFOAMQualityError):
            OpenFOAMQualityParser().finalize()


if __name__ == "__main__":
    unittest.main()
