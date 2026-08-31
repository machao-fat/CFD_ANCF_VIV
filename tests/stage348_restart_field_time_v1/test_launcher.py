from __future__ import annotations

import unittest
from pathlib import Path


class Stage348LauncherTests(unittest.TestCase):
    def test_starts_from_matching_saved_field_step(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage348_restart_field_time_v1/run_stage348.py").read_text(encoding="utf-8")
        self.assertIn("impl.SOURCE_STEP = 15999", text)
        self.assertIn("impl.SOURCE_TIME = 79.995", text)
        self.assertIn('aligned = case / "79.995"', text)
        self.assertIn("impl.SMOKE_STEPS = 41", text)

    def test_shared_launcher_uses_real_bash_pid_expansion(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage346_restart_bootstrap_real_v1/run_stage346.py").read_text(encoding="utf-8")
        self.assertIn("spid=\\$!", text)
        self.assertIn('watchdog() { while kill -0 \\"\\$spid\\"', text)
        self.assertIn('wait \\"\\$spid\\"', text)


if __name__ == "__main__":
    unittest.main()
