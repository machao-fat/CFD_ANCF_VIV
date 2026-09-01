import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "results/368_restart_continuation_diagnostic_v1/diagnostic_report.json"


class Stage368DiagnosticContractTests(unittest.TestCase):
    def test_report_is_fail_closed_and_offline(self):
        if not REPORT.is_file():
            self.skipTest("run_offline_diagnostic.py has not generated the report")
        data = json.loads(REPORT.read_text(encoding="utf-8"))
        self.assertTrue(data["offline_only"])
        self.assertEqual(data["real_process_starts"], {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0})
        self.assertEqual(data["owned_residual"], 0)
        self.assertEqual(data["status"], "do_not_pass")
        self.assertFalse(data["findings"]["inverse_distance_is_sole_root_cause"])


if __name__ == "__main__":
    unittest.main()
