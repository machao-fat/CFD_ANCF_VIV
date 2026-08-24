from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable
WRAPPER = ROOT / "tools" / "cpp_worker_comprehensive_audit_repair_v4" / "run_ownership_40step_replay.py"
WORKER = ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "stage158_build" / "Release" / "cfd_ancf_physics_ownership_worker.exe"
OUTPUT = ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" / "stage158_replay_40step_corrected.json"


class ForceSemanticsReplayTests(unittest.TestCase):
    def test_total_qext_semantics_do_not_false_fail_zero_cfd_replay(self) -> None:
        if not WORKER.is_file():
            self.skipTest("Stage 158 Release ownership worker has not been built")
        completed = subprocess.run(
            [PYTHON, str(WRAPPER), "--worker", str(WORKER), "--output", str(OUTPUT)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["legacy_validator_status"], "do_not_pass")
        self.assertEqual(result["response_external_force_semantics"], "total_Qext")
        self.assertEqual(result["steps_completed"], 40)
        self.assertEqual(result["worker_start_count"], 1)
        self.assertEqual(result["owned_residual"], 0)
        self.assertLessEqual(result["base_load_external_max_abs_error"], 1.0e-8)
        self.assertEqual(result["physical_process_starts"], {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0})


if __name__ == "__main__":
    unittest.main()
