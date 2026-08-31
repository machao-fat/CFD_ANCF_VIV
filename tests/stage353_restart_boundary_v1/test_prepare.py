from __future__ import annotations

import unittest
from pathlib import Path


class Stage353PreparationTests(unittest.TestCase):
    def test_uses_fresh_candidate_and_stage352_parser(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage353_restart_boundary_v1/prepare_boundary_aligned_restart.py").read_text(encoding="utf-8")
        self.assertIn("stage353_restart_boundary_v1_fresh_candidate", text)
        self.assertIn("stage352_restart_boundary_v1/prepare_boundary_aligned_restart.py", text)


if __name__ == "__main__":
    unittest.main()
