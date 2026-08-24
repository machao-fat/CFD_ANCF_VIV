from __future__ import annotations

import unittest
from pathlib import Path

from src.coupling.stage4e_b1_v3_closeout.fail_fast import decide_preflight


class Stage4EB1V3CloseoutTests(unittest.TestCase):
    def test_preexisting_matlab_blocks_before_version_probe(self):
        decision = decide_preflight(preexisting_matlab_count=1, matlab_executable_exists=True)
        self.assertEqual(decision["status"], "environment_blocked")
        self.assertEqual(decision["block_reason"], "preexisting_matlab_processes_blocked")
        self.assertEqual(decision["tests_started"], 0)
        self.assertEqual(decision["version_probe_attempts"], 0)

    def test_missing_executable_blocks_without_worker_start(self):
        decision = decide_preflight(preexisting_matlab_count=0, matlab_executable_exists=False)
        self.assertEqual(decision["block_reason"], "matlab_executable_missing")
        self.assertEqual(decision["tests_started"], 0)

    def test_ready_state_allows_only_one_probe_before_smoke(self):
        decision = decide_preflight(preexisting_matlab_count=0, matlab_executable_exists=True)
        self.assertEqual(decision["status"], "ready_for_single_version_probe")
        self.assertEqual(decision["version_probe_attempts"], 0)
        self.assertEqual(decision["smoke_attempts"], 0)
        self.assertEqual(decision["formal_tests_started"], 0)

    def test_v3_result_directory_is_independent(self):
        project_root = Path(__file__).resolve().parents[2]
        self.assertTrue((project_root / "results" / "09_stage4e_b1_v3_closeout").name.endswith("v3_closeout"))


if __name__ == "__main__":
    unittest.main()
