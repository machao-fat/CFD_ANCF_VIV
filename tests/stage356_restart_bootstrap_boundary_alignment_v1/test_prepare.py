from __future__ import annotations

import unittest
from pathlib import Path


class Stage356PreparationTests(unittest.TestCase):
    def test_state_and_field_share_target_clock(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage356_restart_bootstrap_boundary_alignment_v1/prepare.py").read_text(encoding="utf-8")
        self.assertIn('"state_time_s": TARGET_TIME', text)
        self.assertIn('"state_boundary_clock_equal": True', text)
        self.assertIn('"patched_files": len(patched)', text)


if __name__ == "__main__":
    unittest.main()
