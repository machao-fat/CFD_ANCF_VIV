from __future__ import annotations

import sys
import unittest
from pathlib import Path
import json

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

    def test_saved_field_alignment_is_explicit(self):
        raw = json.loads((Path(__file__).resolve().parents[2] / "results/345_restart_bootstrap_v1/restart_bootstrap_state.json").read_text(encoding="utf-8"))
        self.assertIn("saved_field_interface_xy", raw)
        self.assertLess(float(raw["saved_field_alignment_error_m"]), 1.0e-12)


if __name__ == "__main__":
    unittest.main()
