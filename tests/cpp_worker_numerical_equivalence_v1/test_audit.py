from __future__ import annotations

import unittest
from pathlib import Path

from tools.cpp_worker_numerical_equivalence_v1.run_numerical_equivalence_before_cfd import (
    _contract_mismatch,
    _fault_injection,
)


class NumericalEquivalenceAuditTests(unittest.TestCase):
    def test_native_matlab_contract_mismatch_is_explicit(self) -> None:
        result = _contract_mismatch({"integration": {"n_gauss": 5}, "time": {"max_newton": 50}})
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["matlab_native"], {"gauss_order": 5, "max_newton": 50})

    def test_matching_contract_is_not_rejected(self) -> None:
        result = _contract_mismatch({"integration": {"n_gauss": 3}, "time": {"max_newton": 40}})
        self.assertEqual(result["status"], "match")

    def test_required_failure_matrix_is_fail_closed(self) -> None:
        result = _fault_injection()
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["all_fail_closed"])
        self.assertEqual(result["real_process_starts"], {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})
        self.assertGreaterEqual(len(result["cases"]), 14)

    def test_matlab_exporter_is_bounded_and_atomic(self) -> None:
        project = Path(__file__).resolve().parents[2]
        source = (project / "tools/cpp_worker_numerical_equivalence_v1/export_step559_matlab_golden.m").read_text(encoding="utf-8")
        self.assertIn("double(state.step) ~= 559", source)
        self.assertIn("double(state.model.integration.n_gauss) ~= 5", source)
        self.assertIn("double(state.model.time.max_newton) ~= 50", source)
        self.assertIn("for index = 1:40", source)
        self.assertIn("record.request_id = 510000 + index", source)
        self.assertIn("record.transaction_id = 520000 + index", source)
        self.assertIn("record.payload_size_bytes = numel(payload_bytes)", source)
        self.assertIn("record.payload_hash = sha256_hex(payload_bytes)", source)
        self.assertIn("movefile(tmp, char(output_jsonl), 'f')", source)


if __name__ == "__main__":
    unittest.main()
