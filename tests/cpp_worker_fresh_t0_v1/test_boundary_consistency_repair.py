import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.cpp_worker_fresh_t0_v1 import prepare_boundary_consistent_template_v1 as repair
from tools.cpp_worker_fresh_t0_v1 import prepare_boundary_consistent_preflight_v1 as preflight


class BoundaryConsistencyRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repair_gate = json.loads(
            (repair.RESULTS / "stage4f_d_cpp_worker_fresh_boundary_consistency_repair_v4_gate.json").read_text(encoding="utf-8"))
        cls.preflight_gate = json.loads(
            (preflight.RESULTS / "stage4f_d_cpp_worker_fresh_boundary_consistency_preflight_v1_gate.json").read_text(encoding="utf-8"))

    def test_repair_and_preflight_pass_without_external_processes(self):
        self.assertTrue(self.repair_gate["gate"].endswith(": pass"))
        self.assertTrue(self.preflight_gate["gate"].endswith(": pass"))
        self.assertFalse(self.preflight_gate["launch_performed"])
        self.assertEqual(self.repair_gate["real_process_starts"],
                         {"CPP_WORKER": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})
        self.assertEqual(self.preflight_gate["owned_residual"], 0)

    def test_each_target_patch_has_matching_phi_and_uf_count(self):
        for sid in range(3):
            row = self.preflight_gate["slices"][sid]
            for patch in repair.TARGET_PATCHES:
                expected = row["patches"][patch]["nFaces"]
                self.assertEqual(row["counts"][patch]["phi"], expected)
                self.assertEqual(row["counts"][patch]["Uf"], expected)
            self.assertTrue(row["meshPhi_zero_explicit"])

    def test_single_line_patch_is_not_mixed_with_next_patch(self):
        path = repair.DEST / "slice_0000" / "0" / "phi"
        text = path.read_text(encoding="utf-8")
        inlet = re.search(r"(?ms)^\s*inlet\s*\{([^{}]*)\}", text)
        outlet = re.search(r"(?ms)^\s*outlet\s*\{([^{}]*)\}", text)
        self.assertIsNotNone(inlet)
        self.assertIsNotNone(outlet)
        self.assertIn("nonuniform List<scalar>", inlet.group(1))
        self.assertIn("nonuniform List<scalar>", outlet.group(1))
        self.assertEqual(int(re.search(r"List<scalar>\s+(\d+)", inlet.group(1)).group(1)), 60)
        self.assertEqual(int(re.search(r"List<scalar>\s+(\d+)", outlet.group(1)).group(1)), 60)

    def test_count_corruption_is_detectable_fail_closed(self):
        source = repair.DEST / "slice_0000" / "0" / "phi"
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "phi"
            shutil.copy2(source, copy)
            text = copy.read_text(encoding="utf-8")
            text, changed = re.subn(
                r"(?ms)(^\s*inlet\s*\{[^{}]*?List<scalar>\s+)60",
                r"\g<1>59", text, count=1)
            self.assertEqual(changed, 1)
            copy.write_text(text, encoding="utf-8")
            body = preflight._field_patch(copy, "inlet")
            count = int(re.search(r"List<scalar>\s+(\d+)", body).group(1))
            self.assertNotEqual(count, self.preflight_gate["slices"][0]["patches"]["inlet"]["nFaces"])

    def test_dt_and_scope_are_unchanged(self):
        self.assertTrue(self.preflight_gate["checks"]["dt_consistent"])
        self.assertTrue(self.preflight_gate["checks"]["source_is_separate"])
        self.assertTrue(self.preflight_gate["checks"]["no_old_runtime_reused"])

    def test_new_real_launcher_is_inert_without_authorization(self):
        launcher = ROOT / "tools/cpp_worker_fresh_t0_v1/run_authorized_boundary_consistent_001.py"
        result = __import__("subprocess").run(
            [sys.executable, str(launcher)], cwd=ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--authorize-real", result.stderr)


if __name__ == "__main__":
    unittest.main()
