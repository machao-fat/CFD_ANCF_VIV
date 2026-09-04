import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "tools/stage376_cpp_worker_precice_three_slice_observability_040s_v1/run_stage376.py"
SPEC = importlib.util.spec_from_file_location("stage376_runner", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class Stage376ContractTests(unittest.TestCase):
    def test_fresh_identity_and_scope(self):
        self.assertEqual(MODULE.BASE.STEPS, 40)
        self.assertEqual(MODULE.BASE.DT, 0.005)
        self.assertEqual(MODULE.BASE.TARGET_TIME, 0.2)
        self.assertEqual(MODULE.BASE.RUN_ID, "run376_cpp_worker_precice_three_slice_observability_040s_v1")
        self.assertIn("namePointDisplacement unused", MODULE.BASE.precice_dict(0))


if __name__ == "__main__":
    unittest.main()
