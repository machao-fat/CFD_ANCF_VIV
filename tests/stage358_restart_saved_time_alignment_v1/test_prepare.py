from __future__ import annotations

import unittest
from pathlib import Path


class Stage358PreparationTests(unittest.TestCase):
    def test_saved_time_contract(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage358_restart_saved_time_alignment_v1/prepare.py").read_text(encoding="utf-8")
        self.assertIn('SAVED_TIME = 79.995', text)
        self.assertIn('SAVED_DIR = "79.995"', text)
        self.assertIn('"state_field_clock_equal": True', text)


if __name__ == "__main__":
    unittest.main()
