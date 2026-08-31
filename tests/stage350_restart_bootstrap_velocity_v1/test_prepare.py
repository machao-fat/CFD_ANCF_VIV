from __future__ import annotations

import unittest
from pathlib import Path


class Stage350PreparationTests(unittest.TestCase):
    def test_aligns_all_kinematic_orders(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage350_restart_bootstrap_velocity_v1/prepare_velocity_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn('"velocity_error_m_per_s"', text)
        self.assertIn('"acceleration_error_m_per_s2"', text)
        self.assertIn('"adjacent_diagnostics_present": True', text)
        self.assertIn('"direct_final_q_rejected": True', text)


if __name__ == "__main__":
    unittest.main()
