from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from coupling.restart_alignment_v1 import RestartAlignmentError, build_bootstrap


class RestartContractTests(unittest.TestCase):
    def test_bootstrap_has_explicit_lagged_state(self):
        item = build_bootstrap(
            source_global_step=16000, field_time_s=80.0,
            final_q=[1.0, 2.0], final_qdot=[0.1, 0.2], final_qddot=[0.0, 0.0],
            dt_s=0.005, lag_steps=2,
        )
        self.assertAlmostEqual(item.state_time_s, 79.99)
        self.assertTrue(item.direct_final_q_rejected)
        item.validate()

    def test_inconsistent_state_time_is_rejected(self):
        item = build_bootstrap(
            source_global_step=16000, field_time_s=80.0,
            final_q=[1.0], final_qdot=[0.1], final_qddot=[0.0],
            dt_s=0.005,
        )
        with self.assertRaises(RestartAlignmentError):
            item.__class__(**{**item.__dict__, "state_time_s": 80.0}).validate()


if __name__ == "__main__":
    unittest.main()
