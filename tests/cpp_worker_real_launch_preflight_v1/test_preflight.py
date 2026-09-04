import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "results/238_cpp_worker_real_launch_preflight_v1/real_launch_preflight.json"


class RealLaunchPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = json.loads(AUDIT.read_text(encoding="utf-8"))

    def test_preflight_is_complete_but_does_not_launch(self):
        self.assertTrue(self.audit["checks"]["cpp_state_equilibrated"])
        expected = "STAGE4F_D_CPP_WORKER_REAL_LAUNCH_PREFLIGHT_V1_GATE: pass"
        if self.audit["unowned_cpp_workers"]:
            expected = "STAGE4F_D_CPP_WORKER_REAL_LAUNCH_PREFLIGHT_V1_GATE: do_not_pass"
        self.assertEqual(self.audit["gate"], expected)
        self.assertFalse(self.audit["launch_performed"])

    def test_three_slice_contract(self):
        self.assertTrue(self.audit["checks"]["three_slice_cases_complete"])
        self.assertTrue(self.audit["checks"]["three_slice_dt_consistent"])
        self.assertEqual(len(self.audit["slices"]), 3)

    def test_no_real_processes(self):
        starts = self.audit["real_process_starts"]
        self.assertEqual(starts["CPP_WORKER"], 0)
        self.assertEqual(starts["MATLAB"], 0)
        self.assertEqual(starts["OpenFOAM"], 0)
        self.assertEqual(starts["WSL"], 0)
        self.assertEqual(starts["CFD"], 0)
        self.assertEqual(self.audit["owned_residual"], 0)


if __name__ == "__main__":
    unittest.main()
