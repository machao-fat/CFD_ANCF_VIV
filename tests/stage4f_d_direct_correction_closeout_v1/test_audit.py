import unittest
from pathlib import Path
from coupling.stage4f_d_direct_correction_closeout_v1.audit import closeout


class CloseoutTests(unittest.TestCase):
    def test_existing_probe_is_fail_closed_without_return_code(self):
        root = Path(__file__).resolve().parents[2]
        runs = sorted((root / "runtime" / "stage4f_d_direct_correction_probe_v1").iterdir())
        audit = closeout(runs[-1])
        self.assertEqual(audit["matlab_output_status"], "generated_finite")
        self.assertIsNone(audit["matlab_return_code"])
        self.assertEqual(audit["gate"], "do_not_pass")
        self.assertEqual(audit["owned_residual"], 0)


if __name__ == "__main__":
    unittest.main()
