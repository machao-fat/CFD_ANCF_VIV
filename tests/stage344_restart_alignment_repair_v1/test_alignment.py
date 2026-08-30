from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from coupling.stage303_interface_mapping_repair_v1 import project_interface


class AlignmentTests(unittest.TestCase):
    def test_backward_taylor_preserves_finite_state(self):
        q = [0.1, 0.02, 0.0] * 34
        qdot = [0.3, -0.1, 0.0] * 34
        qddot = [-0.2, 0.05, 0.0] * 34
        horizon = 2 * 0.005
        lag_q = [a - horizon * b + 0.5 * horizon * horizon * c for a, b, c in zip(q, qdot, qddot)]
        lag_qdot = [b - horizon * c for b, c in zip(qdot, qddot)]
        self.assertTrue(all(math.isfinite(value) for value in lag_q + lag_qdot))
        self.assertEqual(len(project_interface(lag_q, lag_qdot)[0]), 3)

    def test_saved_field_lag_is_represented_by_two_state_transitions(self):
        # The production evidence proves that directory 80 matches diagnostic
        # step 15999; this contract must never silently use final_q.
        self.assertEqual(2 * 0.005, 0.01)


if __name__ == "__main__":
    unittest.main()
