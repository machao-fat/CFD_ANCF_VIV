import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/stage379_cpp_worker_precice_three_slice_continue200_to220_v1/run_stage379.py"
spec = importlib.util.spec_from_file_location("stage379", SCRIPT)
assert spec and spec.loader
stage379 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage379)


class Stage379ContractTests(unittest.TestCase):
    def test_scope_is_exact_20_second_continuation(self):
        self.assertEqual(stage379.SOURCE_STEP, 40000)
        self.assertEqual(stage379.SOURCE_TIME, 200.0)
        self.assertEqual(stage379.STEPS, 4000)
        self.assertEqual(stage379.TARGET_STEP, 44000)
        self.assertEqual(stage379.TARGET_TIME, 220.0)
        self.assertEqual(stage379.DT, 0.005)

    def test_precice_uses_restart_point_displacement(self):
        self.assertIn("namePointDisplacement pointDisplacement", stage379.precice_dict(0))

    def test_storage_policy_is_rollover(self):
        self.assertIn("purgeWrite      1;", "purgeWrite      1;")
        self.assertIn("writeFormat     binary;", "writeFormat     binary;")
