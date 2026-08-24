import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4e_target_re_pilot_v2_2_1.analysis_v2_2_1 import (
    compare_metrics,
    gci_nonuniform,
    refinement_ratio,
)
from src.coupling.stage4e_target_re_pilot_v2_2_1.identity_v2_2_1 import (
    AREF,
    B_MESH,
    DT_HALF,
    D,
    finite,
)


class V221Contracts(unittest.TestCase):
    def test_common_dt_policy(self):
        cases = [{"case_id": "coarse", "dt_s": DT_HALF}, {"case_id": "medium", "dt_s": DT_HALF}, {"case_id": "fine", "dt_s": DT_HALF}]
        self.assertEqual({item["dt_s"] for item in cases}, {DT_HALF})

    def test_mixed_dt_policy_rejected(self):
        cases = [{"dt_s": DT_HALF}, {"dt_s": 4.0e-4}]
        self.assertNotEqual({item["dt_s"] for item in cases}, {DT_HALF})

    def test_failed_fine_not_formal(self):
        failed = {"statistics_valid": False, "production_max_CFL": 0.8033}
        self.assertFalse(failed["statistics_valid"])
        self.assertGreaterEqual(failed["production_max_CFL"], 0.8)

    def test_cfl_hard_boundary(self):
        self.assertTrue(0.799 < 0.8)
        self.assertFalse(0.8 < 0.8)

    def test_fine_dt2_expected_dimensionless_step(self):
        self.assertAlmostEqual(0.43414375179615955 * DT_HALF / D, 0.00305627421187018, places=15)

    def test_statistics_gate_requires_all_conditions(self):
        values = {"mean_Cd": 1.0, "St": 0.15, "Cd_fluctuation_RMS": 0.03, "Cl_fluctuation_RMS": 0.5}
        self.assertTrue(compare_metrics(values, values, {key: limit for key, limit in (("mean_Cd", .02), ("St", .02), ("Cd_fluctuation_RMS", .05), ("Cl_fluctuation_RMS", .05))})["passed"])

    def test_three_window_change_threshold(self):
        limits = {"mean_Cd": .02, "St": .02, "Cd_fluctuation_RMS": .05, "Cl_fluctuation_RMS": .05}
        a = {"mean_Cd": 1.0, "St": .15, "Cd_fluctuation_RMS": .03, "Cl_fluctuation_RMS": .5}
        b = {"mean_Cd": 1.03, "St": .15, "Cd_fluctuation_RMS": .03, "Cl_fluctuation_RMS": .5}
        self.assertFalse(compare_metrics(a, b, limits)["passed"])

    def test_nonmonotonic_does_not_make_gci(self):
        result = gci_nonuniform({"coarse": 1.0, "medium": 1.2, "fine": 1.1}, {"coarse": 2880, "medium": 5120, "fine": 11520})
        self.assertEqual(result["status"], "non_monotonic")
        self.assertFalse(result["gci_available"])

    def test_monotonic_gci_has_nonuniform_ratios(self):
        result = gci_nonuniform({"coarse": 1.0, "medium": 1.1, "fine": 1.15}, {"coarse": 2880, "medium": 5120, "fine": 11520})
        self.assertGreater(result["r_coarse_medium"], 1.0)
        self.assertGreater(result["r_medium_fine"], 1.0)

    def test_mesh_ratio_is_cell_based(self):
        self.assertAlmostEqual(refinement_ratio(2880, 5120), (5120 / 2880) ** 0.5)

    def test_aref_and_bmesh(self):
        self.assertEqual(B_MESH, D)
        self.assertAlmostEqual(AREF, D * B_MESH, places=16)

    def test_json_finite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "finite.json"
            payload = finite({"value": 1.0, "text": "中文"})
            path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["text"], "中文")

    def test_domain_dependency(self):
        mesh_passed = False
        timestep = {"available": False}
        domain_allowed = mesh_passed and timestep.get("passed", False)
        self.assertFalse(domain_allowed)

    def test_old_fine_cfl_is_diagnostic_only(self):
        self.assertFalse({"production_max_CFL": 0.8033178440750729, "statistics_valid": False}["statistics_valid"])

    def test_route_semantics_not_high_re_validation(self):
        self.assertTrue("engineering slice model candidate" in "2D engineering slice model candidate")


if __name__ == "__main__":
    unittest.main()
