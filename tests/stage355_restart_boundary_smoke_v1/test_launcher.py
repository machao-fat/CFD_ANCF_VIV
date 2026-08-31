from __future__ import annotations

import unittest
from pathlib import Path


class Stage355LauncherTests(unittest.TestCase):
    def test_smoke_only_and_fresh_identity(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage355_restart_boundary_smoke_v1/run_stage355.py").read_text(encoding="utf-8")
        self.assertIn("stage354_restart_boundary_v1_fresh_candidate", text)
        self.assertIn("run355_restart_boundary_smoke_v1", text)
        self.assertIn('"continuation_started": False', text)


if __name__ == "__main__":
    unittest.main()
