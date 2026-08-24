from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class DirectFinalAuditTests(unittest.TestCase):
    def test_direct_final_audit_accepts_valid_composite(self):
        root = Path(__file__).resolve().parents[2]
        matrix = json.loads((root / "results/95_performance_optimization_v2/real_measurements/matrix.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(dir=str(root / "results/95_performance_optimization_v2")) as out:
            result = subprocess.run([sys.executable, str(root / "tools/performance_optimization_v2/audit_direct_final.py"),
                                     "--matrix", str(root / "results/95_performance_optimization_v2/real_measurements/matrix.json"),
                                     "--final-runtime-result", str(root / "runtime/performance_optimization_v2/benchmarks/MOP_004/benchmark_result.json"),
                                     "--out-dir", out], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            gate = json.loads((Path(out) / "stage4f_d_solver_performance_optimization_v2_gate.json").read_text(encoding="utf-8"))
            self.assertEqual(gate["gate"], "STAGE4F_D_SOLVER_PERFORMANCE_OPTIMIZATION_V2_GATE: pass")
            self.assertGreaterEqual(gate["final"]["speedup"], 1.5)


if __name__ == "__main__":
    unittest.main()
