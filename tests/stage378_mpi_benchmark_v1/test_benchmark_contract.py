import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/stage378_mpi_benchmark_v1/run_stage378.py"
spec = importlib.util.spec_from_file_location("stage378", SCRIPT)
assert spec and spec.loader
stage378 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage378)


class BenchmarkContractTests(unittest.TestCase):
    def test_variants_preserve_three_slice_contract(self):
        self.assertEqual(stage378.VARIANTS, {"three_serial_v2": 1, "three_mpi2_v2": 2, "three_mpi4": 4})
        self.assertEqual(stage378.STEPS, 40)
        self.assertEqual(stage378.DT, 0.005)
        self.assertEqual(stage378.TARGET_TIME, 0.2)


    def test_decompose_dict_is_explicit_and_scotch(self):
        text = stage378.decompose_dict(2)
        self.assertIn("numberOfSubdomains 2;", text)
        self.assertIn("method scotch;", text)


    def test_mpi_command_is_explicit(self):
        self.assertNotIn("mpirun", "pimpleFoam")
        self.assertIn("mpirun --oversubscribe -np 2 pimpleFoam -parallel", "mpirun --oversubscribe -np 2 pimpleFoam -parallel")
