import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from tools.cpp_worker_fresh_t0_v1 import prepare_consistent_potential_preflight_v1 as preflight


class ConsistentPotentialPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = json.loads((ROOT / "results/258_cpp_worker_fresh_consistent_potential_preflight_v1"
                               / "stage4f_d_cpp_worker_fresh_consistent_potential_preflight_v1_gate.json").read_text(encoding="utf-8"))

    def test_gate_passes_without_launch(self):
        self.assertEqual(self.gate["gate"], "STAGE4F_D_CPP_WORKER_FRESH_CONSISTENT_POTENTIAL_PREFLIGHT_V1_GATE: pass")
        self.assertFalse(self.gate["launch_performed"])
        self.assertEqual(self.gate["real_process_starts"], {"CPP_WORKER": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})
        self.assertEqual(self.gate["owned_residual"], 0)

    def test_all_three_slices_have_consistent_fields(self):
        expected = {"U": True, "p": True, "phi": True}
        self.assertEqual(self.gate["consistent_u_p_phi"], {"0": expected, "1": expected, "2": expected})
        self.assertTrue(self.gate["checks"]["consistent_u_p_phi"])
        for sid in range(3):
            for name in ("U", "p", "phi"):
                self.assertTrue(preflight._nonuniform(preflight.TEMPLATE_ROOT / f"slice_{sid:04d}" / "0" / name))


if __name__ == "__main__":
    unittest.main()
