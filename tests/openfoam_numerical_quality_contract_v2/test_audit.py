from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coupling.openfoam_numerical_quality_contract_v2 import AuditError, audit_log, evaluate_quality


FV = '''solvers
{
p
{ solver GAMG;
  tolerance 1e-8;
  relTol 0.01; }
pFinal
{ $p;
  relTol 0; }
pcorr
{ solver GAMG;
  tolerance 1e-2;
  relTol 0; }
pcorrFinal
{ $pcorr;
  relTol 0; }
U
{ solver PBiCGStab;
  tolerance 1e-8;
  relTol 0.1; }
UFinal
{ $U;
  relTol 0; }
cellMotionUx
{ solver PCG;
  tolerance 1e-8;
  relTol 0; }
}
PIMPLE
{ nOuterCorrectors 1;
  nCorrectors 2;
  nNonOrthogonalCorrectors 0;
  correctPhi yes;
  correctMeshPhi yes; }
'''
LOG = '''Courant Number mean: 0.01 max: 0.2
Time = 0.005s
solver: Solving for Ux, Initial residual = 1, Final residual = 1e-9, No Iterations 2
solver: Solving for Uy, Initial residual = 1, Final residual = 1e-9, No Iterations 2
solver: Solving for p, Initial residual = 1, Final residual = 4e-3, No Iterations 3
time step continuity errors : sum local = 1e-8, global = 1e-9, cumulative = 1e-9
solver: Solving for p, Initial residual = 0.4, Final residual = 9e-9, No Iterations 9
time step continuity errors : sum local = 1e-12, global = 1e-13, cumulative = 1e-9
'''
CONTRACT = {
    "linear_solver_health": {"per_field_base_solver": {
        "p": {"absolute_tolerance": 1e-8, "relative_tolerance": .01},
        "U": {"absolute_tolerance": 1e-8, "relative_tolerance": .1}}},
    "pimple_terminal_convergence": {"required_fields": ["Ux", "Uy", "p"],
        "per_field_absolute_final_residual_limit": {"Ux": 1e-8, "Uy": 1e-8, "p": 1e-8}},
    "courant_quality": {"max_limit": .5}, "continuity_quality": {"global_abs_limit": 1e-6},
    "iteration_health": {"linear_iterations_max": 999},
}


class NumericalQualityAuditTests(unittest.TestCase):
    def _audit(self):
        directory = tempfile.TemporaryDirectory(); root = Path(directory.name)
        (root / "fvSolution").write_text(FV, encoding="utf-8")
        (root / "stdout").write_text(LOG, encoding="utf-8")
        return directory, audit_log(root / "stdout", root / "fvSolution")

    def test_intermediate_pressure_is_not_terminal(self):
        directory, audit = self._audit()
        self.addCleanup(directory.cleanup)
        row = audit["time_records"][0]
        self.assertEqual(row["metrics"]["legacy_max_final_residual"], .004)
        self.assertEqual(row["metrics"]["field_terminal_final_residual"]["p"], 9e-9)
        self.assertFalse(row["solves"][2]["terminal_for_field"])
        self.assertEqual(row["solves"][2]["pressure_corrector"], "unknown")

    def test_contract_uses_terminal_not_legacy(self):
        directory, audit = self._audit()
        self.addCleanup(directory.cleanup)
        result = evaluate_quality(audit, CONTRACT)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["legacy_max_final_residual_diagnostic"], .004)

    def test_missing_terminal_field_fails_closed(self):
        directory = tempfile.TemporaryDirectory(); root = Path(directory.name)
        (root / "fvSolution").write_text(FV, encoding="utf-8")
        (root / "stdout").write_text(LOG.replace("solver: Solving for Uy, Initial residual = 1, Final residual = 1e-9, No Iterations 2\n", ""), encoding="utf-8")
        audit = audit_log(root / "stdout", root / "fvSolution")
        result = evaluate_quality(audit, CONTRACT)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["observability_completeness"], "fail")
        directory.cleanup()

    def test_time_grammar_and_pending_courant_are_time_local(self):
        directory = tempfile.TemporaryDirectory(); root = Path(directory.name)
        (root / "fvSolution").write_text(FV, encoding="utf-8")
        lines = [
            "Courant Number mean: 0.01 max: 0.2", "Time = 5e-2 s",
            "solver: Solving for Ux, Initial residual = 1, Final residual = 1e-9, No Iterations 2",
            "solver: Solving for Uy, Initial residual = 1, Final residual = 1e-9, No Iterations 2",
            "solver: Solving for p, Initial residual = 1, Final residual = 1e-9, No Iterations 2",
            "time step continuity errors : sum local = 1e-9, global = 1e-9, cumulative = 1e-9",
            "Courant Number mean: 0.02 max: 0.3", "Time = .055",
            "solver: Solving for Ux, Initial residual = 1, Final residual = 1e-9, No Iterations 2",
            "solver: Solving for Uy, Initial residual = 1, Final residual = 1e-9, No Iterations 2",
            "solver: Solving for p, Initial residual = 1, Final residual = 1e-9, No Iterations 2",
            "time step continuity errors : sum local = 1e-9, global = 1e-9, cumulative = 1e-9",
        ]
        (root / "stdout").write_text("\n".join(lines) + "\n", encoding="utf-8")
        audit = audit_log(root / "stdout", root / "fvSolution")
        self.assertEqual([(item["time_s"], item["courant_max"]) for item in audit["time_records"]],
                         [(0.05, 0.2), (0.055, 0.3)])
        directory.cleanup()


if __name__ == "__main__":
    unittest.main()
