import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/stage382_cpp_worker_precice_three_slice_continue270_to370_v1/run_stage382.py"
spec = importlib.util.spec_from_file_location("stage382", SCRIPT)
assert spec and spec.loader
stage382 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage382)


class Stage382ContractTests(unittest.TestCase):
    def test_scope(self):
        self.assertEqual(stage382.SOURCE_TIME, 270.0)
        self.assertEqual(stage382.TARGET_TIME, 370.0)
        self.assertEqual(stage382.SOURCE_STEP, 54000)
        self.assertEqual(stage382.TARGET_STEP, 74000)
        self.assertEqual(stage382.STEPS, 20000)
        self.assertEqual(stage382.DT, 0.005)

    def test_new_runtime_and_ids(self):
        self.assertNotEqual(stage382.RUNTIME, stage382.SOURCE)
        self.assertIn("stage382", str(stage382.RUNTIME))
        self.assertIn("run382", stage382.RUN_ID)


if __name__ == "__main__":
    unittest.main()
