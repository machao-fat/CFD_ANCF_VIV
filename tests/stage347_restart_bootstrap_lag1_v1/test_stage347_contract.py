from __future__ import annotations

import unittest
from pathlib import Path


class Stage347ContractTests(unittest.TestCase):
    def test_fresh_paths_and_lag1_candidate(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage347_restart_bootstrap_lag1_v1/run_stage347.py").read_text(encoding="utf-8")
        self.assertIn("results/347_restart_bootstrap_lag1_v1", text)
        self.assertIn("runtime/stage347_restart_bootstrap_lag1_smoke_v1", text)
        self.assertIn("run347_restart_bootstrap_lag1_smoke_v1", text)


if __name__ == "__main__":
    unittest.main()
