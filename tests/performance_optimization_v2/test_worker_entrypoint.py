from __future__ import annotations

import unittest
from pathlib import Path


class WorkerEntrypointTests(unittest.TestCase):
    def test_matlab_file_primary_function_matches_filename(self):
        root = Path(__file__).resolve().parents[2]
        path = root / "src" / "coupling" / "performance_matlab_worker_bridge_v1" / "matlab_worker_loop.m"
        first = path.read_text(encoding="utf-8").splitlines()[0].strip()
        self.assertEqual(first, "function matlab_worker_loop(runtime_root)")

    def test_contract_generator_uses_matching_entrypoint(self):
        root = Path(__file__).resolve().parents[2]
        source = (root / "tools" / "performance_optimization_v2" / "write_benchmark_contract.py").read_text(encoding="utf-8")
        self.assertIn("matlab_worker_loop('{runtime_expr}')", source)
        self.assertNotIn("stage94_matlab_worker_loop('{runtime_expr}')", source)


if __name__ == "__main__":
    unittest.main()
