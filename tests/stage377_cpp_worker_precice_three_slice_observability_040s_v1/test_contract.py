import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "tools/stage377_cpp_worker_precice_three_slice_observability_040s_v1/run_stage377.py"
SPEC = importlib.util.spec_from_file_location("stage377_runner", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class Stage377ContractTests(unittest.TestCase):
    def test_new_identity_and_strict_quality_wrapper(self):
        self.assertEqual(MODULE.base.STEPS, 40)
        self.assertEqual(MODULE.base.TARGET_TIME, 0.2)
        self.assertEqual(MODULE.base.RUN_ID, "run377_cpp_worker_precice_three_slice_observability_040s_v1")
        self.assertTrue(str(MODULE.base.QUALITY).endswith("run_openfoam_with_metrics_v2.py"))


if __name__ == "__main__":
    unittest.main()
