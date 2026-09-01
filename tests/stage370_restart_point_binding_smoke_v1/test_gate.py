import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "results/370_restart_point_binding_smoke_v1/stage4f_d_restart_continuation_diagnostic_repair_v1_gate.json"


class Stage370GateTests(unittest.TestCase):
    def test_gate_records_zero_matlab_and_owned_residual(self):
        if not GATE.is_file():
            self.skipTest("Stage 370 has not run")
        data = json.loads(GATE.read_text(encoding="utf-8"))
        self.assertEqual(data["real_process_starts"]["matlab"], 0)
        self.assertEqual(data["owned_residual"], 0)
        self.assertIn(data["status"], ("pass", "do_not_pass"))


if __name__ == "__main__":
    unittest.main()
