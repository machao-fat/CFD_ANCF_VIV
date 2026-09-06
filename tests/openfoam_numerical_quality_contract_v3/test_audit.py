from __future__ import annotations

import unittest

from coupling.openfoam_numerical_quality_contract_v3.audit import evaluate_quality_v3


CONTRACT = {
    "primary_terminal_residual_limit": {"Ux": 1e-3, "Uy": 1e-3, "p": 1e-3},
    "courant_max_limit": 1.0, "continuity_global_abs_limit": 1e-6,
    "solve_groups": {
        "fluid_primary": {"fields": ["Ux", "Uy", "p"], "absolute_tolerance": 1e-8, "relative_tolerance": .01, "max_iterations": 200},
        "mesh_motion_auxiliary": {"fields": ["cellDisplacementx", "cellDisplacementy"], "absolute_tolerance": 1e-8, "relative_tolerance": 0.0, "max_iterations": 200},
        "flux_correction_auxiliary": {"fields": ["pcorr"], "absolute_tolerance": 1e-2, "relative_tolerance": 0.0, "max_iterations": 200},
    },
}


def audit(solves):
    terminal = {field: rows[-1]["final_residual"] for field, rows in {name: [row for row in solves if row["field"] == name] for name in {row["field"] for row in solves}}.items()}
    return {"time_records": [{"time_s": .005, "courant_max": .2, "continuity": [{"global": 1e-12}], "solves": solves,
                               "metrics": {"field_terminal_final_residual": terminal}}]}


def solve(field, initial, final, iterations):
    return {"field": field, "initial_residual": initial, "final_residual": final, "linear_iterations": iterations}


class QualityContractV3Tests(unittest.TestCase):
    def test_zero_motion_auxiliary_is_explicitly_trivial(self):
        data = audit([solve("cellDisplacementx", 0, 0, 0), solve("cellDisplacementy", 0, 0, 0),
                      solve("pcorr", 1, .005, 3), solve("Ux", .01, 1e-9, 2), solve("Uy", .01, 1e-9, 2),
                      solve("p", .01, 1e-9, 2)])
        result = evaluate_quality_v3(data, CONTRACT)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(sum(item["trivially_converged"] for item in result["classifications"]), 2)

    def test_nonzero_auxiliary_must_converge(self):
        data = audit([solve("cellDisplacementx", .1, .01, 2), solve("cellDisplacementy", 0, 0, 0),
                      solve("pcorr", 1, .005, 3), solve("Ux", .01, 1e-9, 2), solve("Uy", .01, 1e-9, 2), solve("p", .01, 1e-9, 2)])
        self.assertEqual(evaluate_quality_v3(data, CONTRACT)["status"], "fail")

    def test_unknown_solve_fails_closed(self):
        data = audit([solve("cellDisplacementx", 0, 0, 0), solve("cellDisplacementy", 0, 0, 0), solve("pcorr", 1, .005, 3),
                      solve("Ux", .01, 1e-9, 2), solve("Uy", .01, 1e-9, 2), solve("p", .01, 1e-9, 2), solve("k", .01, 1e-9, 2)])
        self.assertEqual(evaluate_quality_v3(data, CONTRACT)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
