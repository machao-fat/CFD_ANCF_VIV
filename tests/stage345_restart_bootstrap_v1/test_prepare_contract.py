from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from coupling.restart_alignment_v1 import build_bootstrap  # noqa: E402


class BootstrapPreparationTests(unittest.TestCase):
    def test_candidate_is_not_final_state(self):
        item = build_bootstrap(
            source_global_step=16000, field_time_s=80.0,
            final_q=[1.0, 2.0], final_qdot=[0.1, 0.2], final_qddot=[0.0, 0.0],
            dt_s=0.005, lag_steps=2,
        )
        self.assertNotEqual(item.q, (1.0, 2.0))
        self.assertLess(item.state_time_s, item.field_time_s)
        self.assertTrue(item.direct_final_q_rejected)


if __name__ == "__main__":
    unittest.main()
