from __future__ import annotations

import unittest
from pathlib import Path


class Stage352PreparationTests(unittest.TestCase):
    def test_binary_boundary_patch_is_scoped(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage352_restart_boundary_v1/prepare_boundary_aligned_restart.py").read_text(encoding="utf-8")
        self.assertIn("pointDisplacement", text)
        self.assertIn("cellDisplacement", text)
        self.assertIn('"wsl_starts": 0', text)
        self.assertIn('"source_read_only": True', text)


if __name__ == "__main__":
    unittest.main()
