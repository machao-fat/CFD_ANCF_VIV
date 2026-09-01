import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "results/371_diffusivity_offline_compare_v1/diffusivity_compare.json"


class DiffusivityCompareTests(unittest.TestCase):
    def test_comparison_is_offline_and_non_mutating(self):
        if not REPORT.is_file():
            self.skipTest("comparison has not run")
        data = json.loads(REPORT.read_text(encoding="utf-8"))
        self.assertTrue(data["offline_only"])
        self.assertFalse(data["production_configuration_changed"])
        self.assertEqual(data["real_process_starts"]["matlab"], 0)
        self.assertEqual(data["real_process_starts"]["openfoam"], 0)
        self.assertEqual(data["owned_residual"], 0)
        self.assertTrue(data["candidates"]["source_files_present"]["quadratic"])
        self.assertTrue(data["candidates"]["source_files_present"]["exponential"])


if __name__ == "__main__":
    unittest.main()
