from __future__ import annotations

import unittest

from coupling.performance_optimization_v1.config import audit_candidate, optimize_control_dict, optimize_fv_solution


FV = """solvers { \"cellDisplacement.*\" { chacheAgglomeration true; } } PIMPLE { nOuterCorrectors 5; moveMeshOuterCorrectors yes; }"""
CONTROL = """application pimpleFoam; deltaT 0.005; writeInterval 1; writeFormat ascii;"""


class CandidateConfigTests(unittest.TestCase):
    def test_candidate_fixes_cache_and_mesh_frequency(self) -> None:
        candidate = optimize_fv_solution(FV)
        checks = audit_candidate(fv_solution=candidate, control_dict=optimize_control_dict(CONTROL))
        self.assertTrue(all(checks.values()))

    def test_physics_step_and_outer_count_are_preserved(self) -> None:
        fv = optimize_fv_solution(FV)
        control = optimize_control_dict(CONTROL)
        self.assertIn("nOuterCorrectors 5", fv)
        self.assertIn("deltaT 0.005", control)

    def test_baseline_can_be_audited_fail_closed(self) -> None:
        checks = audit_candidate(fv_solution=FV, control_dict=CONTROL)
        self.assertFalse(checks["cache_agglomeration_spelling_fixed"])
        self.assertFalse(checks["mesh_update_once_candidate"])


if __name__ == "__main__":
    unittest.main()
