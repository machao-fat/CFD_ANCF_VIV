import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/stage381_cpp_worker_precice_three_slice_continue220_to270_v1/run_stage381.py"
spec = importlib.util.spec_from_file_location("stage381", SCRIPT)
assert spec and spec.loader
stage381 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage381)


class Stage381ContractTests(unittest.TestCase):
    def test_scope_is_exact_50_second_continuation(self):
        self.assertEqual(stage381.SOURCE_STEP, 44000)
        self.assertEqual(stage381.SOURCE_TIME, 220.0)
        self.assertEqual(stage381.STEPS, 10000)
        self.assertEqual(stage381.TARGET_STEP, 54000)
        self.assertEqual(stage381.TARGET_TIME, 270.0)
        self.assertEqual(stage381.DT, 0.005)

    def test_new_runtime_is_not_stage379(self):
        self.assertNotEqual(stage381.RUNTIME, stage381.SOURCE)
        self.assertIn("stage381", str(stage381.RUNTIME))

    def test_source_checks_require_finalized_220_endpoint(self):
        self.assertEqual(stage381.SOURCE_STEP, 44000)
        self.assertEqual(stage381.SOURCE_TIME, 220.0)


if __name__ == "__main__":
    unittest.main()
