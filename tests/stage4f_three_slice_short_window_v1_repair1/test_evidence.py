import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_three_slice_short_window_v1_repair1.evidence import (
    compare_parent_audits, numeric_file_comparison, parent_protection_audit,
)


class TestEvidence(unittest.TestCase):
    def test_parent_protection_set(self):
        audit = parent_protection_audit()
        self.assertEqual(audit["status"], "passed")
        self.assertEqual(audit["protected_file_count"], 32)
        self.assertEqual(audit["parent_checkpoint_sha256"], "5db86ae104015d51a8268862a1551579d96d0d80d82ddc7f55536371efc0334e")

    def test_parent_audit_comparison_detects_change(self):
        self.assertEqual(compare_parent_audits({"combined_sha256": "a", "files": []}, {"combined_sha256": "b", "files": []})["status"], "blocked")

    def test_numeric_file_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            left, right = Path(directory) / "a", Path(directory) / "b"
            left.write_text("value 1.0 2.0\n", encoding="utf-8")
            right.write_text("value 1.0 2.000000000001\n", encoding="utf-8")
            result = numeric_file_comparison(left, right)
            self.assertTrue(result["numeric_token_count_equal"])
            self.assertLess(result["max_relative_error"], 1e-11)

    def test_numeric_file_rejects_nonfinite(self):
        with tempfile.TemporaryDirectory() as directory:
            left, right = Path(directory) / "a", Path(directory) / "b"
            left.write_text("1e309\n", encoding="utf-8")
            right.write_text("1\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                numeric_file_comparison(left, right)


if __name__ == "__main__":
    unittest.main()
