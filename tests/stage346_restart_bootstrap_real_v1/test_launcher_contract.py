from __future__ import annotations

import unittest
from pathlib import Path


class Stage346LauncherContractTests(unittest.TestCase):
    def test_launcher_is_new_stage_and_fail_closed(self):
        path = Path(__file__).resolve().parents[2] / "tools/stage346_restart_bootstrap_real_v1/run_stage346.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn("refusing to reuse runtime", text)
        self.assertIn("if smoke_gate[\"status\"] != \"pass\":", text)
        self.assertIn("continuation_started", text)
        self.assertIn("watchdog()", text)


if __name__ == "__main__":
    unittest.main()
