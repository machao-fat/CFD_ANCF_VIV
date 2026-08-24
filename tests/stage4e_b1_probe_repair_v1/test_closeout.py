import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "results" / "09_stage4e_b1_probe_repair_v1"


class CloseoutEvidenceTests(unittest.TestCase):
    def test_real_probe_is_blocked_without_retry(self):
        result = json.loads((ROOT / "probe_repair_result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "environment_blocked")
        self.assertEqual(result["return_code"], 1)
        self.assertFalse(result["payload_exists"])
        self.assertEqual(result["owned_processes"]["started_records"], 5)
        self.assertEqual(result["owned_processes"]["closed_records"], 5)
        self.assertEqual(result["owned_processes"]["residual_records"], 0)
        self.assertTrue(result["no_retry"])

    def test_no_fsi_branch_was_started(self):
        result = json.loads((ROOT / "probe_repair_result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["attempt2"], {"branch_A_started": False, "branch_B_started": False, "branch_C_started": False})
        self.assertEqual(result["openfoam_started"], 0)
        self.assertEqual(result["parent_identity"]["protected_file_count"], 32)


if __name__ == "__main__":
    unittest.main()
