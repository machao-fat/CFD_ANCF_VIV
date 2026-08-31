from __future__ import annotations

import unittest
from pathlib import Path


class Stage357LauncherTests(unittest.TestCase):
    def test_uses_stage356_state_and_fresh_smoke_identity(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage357_restart_bootstrap_boundary_smoke_v1/run_stage357.py").read_text(encoding="utf-8")
        self.assertIn("stage356_restart_bootstrap_boundary_alignment_v1_fresh", text)
        self.assertIn("run357_restart_bootstrap_boundary_smoke_v1", text)
        self.assertIn('"continuation_started": False', text)


if __name__ == "__main__":
    unittest.main()
