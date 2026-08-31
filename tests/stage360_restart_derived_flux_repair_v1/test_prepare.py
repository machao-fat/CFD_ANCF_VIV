from __future__ import annotations

import unittest
from pathlib import Path


class Stage360PreparationTests(unittest.TestCase):
    def test_removes_only_derived_flux_fields(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage360_restart_derived_flux_repair_v1/prepare.py").read_text(encoding="utf-8")
        self.assertIn('REMOVED_DERIVED = ("phi", "meshPhi", "Uf")', text)
        self.assertIn('"U", "p", "pointDisplacement", "cellDisplacement", "Force"', text)


if __name__ == "__main__":
    unittest.main()
