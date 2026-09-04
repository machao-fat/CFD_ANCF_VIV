import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools.cpp_worker_fresh_t0_v1 import prepare_fresh_t0_potential_preflight_v1 as preflight
from tools.cpp_worker_fresh_t0_v1 import run_authorized_fresh_t0_001 as launch


class FreshPotentialPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = json.loads(
            (ROOT / "results/253_cpp_worker_fresh_potential_preflight_v1"
             / "stage4f_d_cpp_worker_fresh_potential_preflight_v1_gate.json")
            .read_text(encoding="utf-8"))
        cls.audit = json.loads(
            (ROOT / "results/253_cpp_worker_fresh_potential_preflight_v1"
             / "fresh_t0_real_launch_preflight.json").read_text(encoding="utf-8"))

    def test_gate_passes(self):
        self.assertEqual(
            self.gate["gate"],
            "STAGE4F_D_CPP_WORKER_FRESH_POTENTIAL_PREFLIGHT_V1_GATE: pass")

    def test_preflight_does_not_launch(self):
        self.assertFalse(self.gate["launch_performed"])
        self.assertEqual(self.gate["real_process_starts"],
                         {"CPP_WORKER": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})
        self.assertEqual(self.gate["owned_residual"], 0)
        self.assertFalse(self.gate["old_runtime_reused"])

    def test_three_slices_are_potential_flow(self):
        self.assertEqual(self.gate["potential_flow_internal_fields"], {"0": True, "1": True, "2": True})
        self.assertTrue(self.gate["checks"]["potential_flow_internal_fields"])
        for sid in range(3):
            path = preflight.TEMPLATE_ROOT / f"slice_{sid:04d}" / "0" / "U"
            self.assertTrue(path.is_file())
            text = path.read_text(encoding="utf-8")
            self.assertIn("internalField   nonuniform List<vector>", text)

    def test_bounded_fresh_contract(self):
        self.assertTrue(self.gate["checks"]["contract_valid"])
        self.assertEqual(self.gate["checks"]["three_slice_cases_complete"], True)
        self.assertEqual(self.gate["checks"]["three_slice_dt_consistent"], True)
        self.assertEqual(self.gate["checks"]["source_identity_zero"], True)

    def test_launcher_requires_authorization(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/cpp_worker_fresh_t0_v1/run_authorized_fresh_t0_001.py")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--authorize-real", result.stderr)

    def test_uniform_template_is_rejected_by_potential_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "U"
            path.write_text(
                "internalField   uniform (1 0 0);\nboundaryField\n{\n}\n",
                encoding="utf-8")
            self.assertFalse(preflight._potential_field_ok(path))


if __name__ == "__main__":
    unittest.main()
