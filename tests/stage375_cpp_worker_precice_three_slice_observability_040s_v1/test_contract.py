import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "tools/stage375_cpp_worker_precice_three_slice_observability_040s_v1/run_stage375.py"
SPEC = importlib.util.spec_from_file_location("stage375_runner", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class Stage375ContractTests(unittest.TestCase):
    def test_scope_is_fresh_zero_to_forty_steps(self):
        self.assertEqual(MODULE.STEPS, 40)
        self.assertEqual(MODULE.DT, 0.005)
        self.assertEqual(MODULE.TARGET_TIME, 0.2)

    def test_fresh_start_does_not_require_point_field_registry(self):
        for index in range(3):
            config = MODULE.precice_dict(index)
            self.assertIn("namePointDisplacement unused", config)
            self.assertIn(f"participant Fluid_{index:04d}", config)


if __name__ == "__main__":
    unittest.main()
