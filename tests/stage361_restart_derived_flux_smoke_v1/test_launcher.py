from __future__ import annotations

import unittest
from pathlib import Path


class Stage361LauncherTests(unittest.TestCase):
    def test_uses_derived_flux_free_candidate(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage361_restart_derived_flux_smoke_v1/run_stage361.py").read_text(encoding="utf-8")
        self.assertIn("stage360_restart_derived_flux_repair_v1_fresh", text)
        self.assertIn('"phi", "meshPhi", "Uf"', text)
        self.assertIn('"continuation_started": False', text)


if __name__ == "__main__":
    unittest.main()
