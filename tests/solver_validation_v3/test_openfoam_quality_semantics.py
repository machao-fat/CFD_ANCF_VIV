"""Completeness must not be promoted to numerical quality."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from coupling.openfoam_quality_contract_v3 import audit_records  # noqa: E402


def rows() -> list[dict[str, float | int]]:
    return [
        {"time_s": 1.0, "courant_max": 0.4, "residual_max": 1.0e-3, "continuity_global": 1.0e-9, "iterations_max": 4},
        {"time_s": 1.005, "courant_max": 0.5, "residual_max": 2.0e-3, "continuity_global": -1.0e-9, "iterations_max": 5},
    ]


class OpenFOAMQualitySemanticsTest(unittest.TestCase):
    def test_complete_history_without_frozen_contract_is_not_numerical_pass(self) -> None:
        result = audit_records(rows(), expected_count=2, expected_start_s=1.0)
        self.assertEqual(result["OBSERVABILITY_COMPLETENESS"]["status"], "pass")
        self.assertEqual(result["NUMERICAL_QUALITY"]["status"], "not_evaluable")

    def test_frozen_contract_evaluates_limits_and_definition(self) -> None:
        contract = {
            "schema_version": 1, "frozen_before_run": True, "courant_limit": 0.6,
            "residual_definition": "max_final_residual_across_all_parsed_Solving_for_lines_per_time", "residual_limit": 0.01,
            "continuity_definition": "last_parsed_global_continuity_error_per_time", "continuity_limit": 1.0e-7,
            "iteration_definition": "maximum_iterations_across_all_parsed_Solving_for_lines_per_time", "iteration_limit": 8,
        }
        self.assertEqual(audit_records(rows(), expected_count=2, expected_start_s=1.0, numerical_contract=contract)["NUMERICAL_QUALITY"]["status"], "pass")
        contract["residual_definition"] = "initial_residual"
        self.assertEqual(audit_records(rows(), expected_count=2, expected_start_s=1.0, numerical_contract=contract)["NUMERICAL_QUALITY"]["status"], "not_evaluable")

    def test_missing_field_fails_completeness(self) -> None:
        incomplete = rows()
        del incomplete[1]["continuity_global"]
        result = audit_records(incomplete, expected_count=2, expected_start_s=1.0)
        self.assertEqual(result["OBSERVABILITY_COMPLETENESS"]["status"], "fail")
        self.assertEqual(result["NUMERICAL_QUALITY"]["status"], "not_evaluable")


if __name__ == "__main__":
    unittest.main()
