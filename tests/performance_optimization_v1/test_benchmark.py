import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.performance_optimization_v1.benchmark import STAGES, run_offline_benchmark


class BenchmarkTests(unittest.TestCase):
    def test_all_stages_emit_offline_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_offline_benchmark(tmp, steps=4)
            self.assertEqual([item["stage"] for item in report["measurements"]], list(STAGES))
            self.assertTrue(report["gate"]["optimization_gate_passed"])
            self.assertEqual(report["gate"]["external_process_starts"], 0)
            self.assertEqual(report["gate"]["owned_residual"], 0)
            self.assertTrue(report["gate"]["offline_only"])
            self.assertEqual(report["gate"]["forbidden_real_start_count"], 0)
            self.assertFalse(report["gate"]["forbidden_scope_expansion"])
            self.assertFalse(report["gate"]["physical_contract_modified"])
            self.assertFalse(report["config"]["contract_change_audit"]["ancf_core_modified"])
            self.assertFalse(report["config"]["contract_change_audit"]["eb_core_modified"])
            self.assertEqual(report["config"]["global_dt_s"], 0.0025)
            self.assertEqual(report["config"]["slice_count"], 3)
            for item in report["measurements"]:
                self.assertEqual(item["external_process_starts"], 0)
                self.assertEqual(item["owned_residual"], 0)
                self.assertIn("p95", item["per_step_ms"])
                self.assertIn("observed_per_step_ms", item)
                self.assertEqual(item["owned_residual"], 0)
            output = Path(tmp) / "results" / "90_performance_optimization_v1" / "performance_optimization_v1_report.json"
            self.assertTrue(output.is_file())
            json.loads(output.read_text(encoding="utf-8"))
