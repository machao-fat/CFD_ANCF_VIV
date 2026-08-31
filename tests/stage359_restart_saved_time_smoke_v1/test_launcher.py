from __future__ import annotations

import unittest
from pathlib import Path


class Stage359LauncherTests(unittest.TestCase):
    def test_saved_time_identity(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage359_restart_saved_time_smoke_v1/run_stage359.py").read_text(encoding="utf-8")
        self.assertIn("stage358_restart_saved_time_alignment_v1_fresh", text)
        self.assertIn("SOURCE_TIME = 79.995", text)
        self.assertIn('"continuation_started": False', text)


if __name__ == "__main__":
    unittest.main()
