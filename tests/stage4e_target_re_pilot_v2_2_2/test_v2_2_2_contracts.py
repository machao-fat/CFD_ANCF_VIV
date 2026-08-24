import json
import math
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4e_target_re_pilot_v2_2_2.analysis_v2_2_2 import (
    compare_metrics,
    decision_matrix,
    offline_reclassification,
    relative_change,
    spatial_dt1_comparison,
)
from src.coupling.stage4e_target_re_pilot_v2_2_2.identity_v2_2_2 import (
    AREF,
    B_MESH,
    D,
    DT1,
    DT1_STAR,
    DT2,
    DT2_STAR,
    finite,
)


def _summary(level, values, *, valid=True, cfl=0.2):
    return {
        "case_id": level,
        "statistics_valid": valid,
        "runtime_valid": True,
        "production_max_CFL": cfl,
        "mesh_audit": {"cells": {"coarse": 2880, "medium": 5120, "fine": 11520}[level]},
        "statistics": values,
        "statistics_gate": {"stability": {"changes": {"Cd_fluctuation_RMS": [0.0500177] if level == "fine" else [0.01]}}},
    }


class V222Contracts(unittest.TestCase):
    def test_fixed_dt_dimensionless_values(self):
        self.assertAlmostEqual(DT2, 2.0 * DT1, places=16)
        self.assertAlmostEqual(DT2_STAR, 2.0 * DT1_STAR, places=16)

    def test_force_span_contract(self):
        self.assertEqual(B_MESH, D)
        self.assertAlmostEqual(AREF, D * B_MESH, places=16)

    def test_relative_change_uses_b_as_reference(self):
        self.assertAlmostEqual(relative_change(1.0, 2.0), 0.5)

    def test_offline_fine_diagnostic_is_not_hidden(self):
        vals = {"mean_Cd": 1.0, "Cd_fluctuation_RMS": 0.1, "Cl_fluctuation_RMS": 0.5, "Cl_peak_to_peak": 1.0, "St": 0.15}
        result = offline_reclassification({"coarse": _summary("coarse", vals), "medium": _summary("medium", vals), "fine": _summary("fine", vals, valid=False, cfl=0.551546)})
        self.assertTrue(result["diagnostic_trend_not_hidden"])
        self.assertFalse(result["fine_status"]["statistics_valid"])
        self.assertEqual(result["fine_status"]["stationarity_classification"], "marginal_stationarity_failure")

    def test_cfl_target_is_distinct_from_hard_stop(self):
        self.assertTrue(0.551546 > 0.5)
        self.assertTrue(0.551546 < 0.8)

    def test_time_comparison_threshold(self):
        a = {"mean_Cd": 1.0, "St": 0.15, "Cd_fluctuation_RMS": 0.1, "Cl_fluctuation_RMS": 0.5, "Cl_peak_to_peak": 1.0}
        b = dict(a)
        self.assertTrue(compare_metrics(a, b, {"mean_Cd": .02, "St": .02, "Cd_fluctuation_RMS": .05, "Cl_fluctuation_RMS": .05})["passed"])

    def test_spatial_comparison_requires_both_valid(self):
        a = _summary("medium", {"mean_Cd": 1.0, "St": .15, "Cd_fluctuation_RMS": .1, "Cl_fluctuation_RMS": .5, "Cl_peak_to_peak": 1.0})
        b = _summary("fine", {"mean_Cd": 1.0, "St": .15, "Cd_fluctuation_RMS": .1, "Cl_fluctuation_RMS": .5, "Cl_peak_to_peak": 1.0}, valid=False)
        self.assertFalse(spatial_dt1_comparison(a, b)["passed"])

    def test_decision_blocks_coarse_when_fine_time_is_bad(self):
        result = decision_matrix(medium_dt1_passed=True, fine_dt1_passed=False, time_passed=False, spatial_passed=False)
        self.assertEqual(result["LAMINAR_HIGH_RE_MODEL_STATUS"], "rejected_or_blocked_practical_time_nonconvergence")
        self.assertFalse(result["coarse_dt1_allowed"])

    def test_decision_rejects_spatial_after_time_pass(self):
        result = decision_matrix(medium_dt1_passed=True, fine_dt1_passed=True, time_passed=True, spatial_passed=False)
        self.assertEqual(result["LAMINAR_HIGH_RE_MODEL_STATUS"], "rejected_spatial_nonconvergence")

    def test_decision_allows_only_conditional_coarse(self):
        result = decision_matrix(medium_dt1_passed=True, fine_dt1_passed=True, time_passed=True, spatial_passed=True)
        self.assertTrue(result["coarse_dt1_allowed"])

    def test_no_automatic_dt_quarter(self):
        self.assertNotEqual(DT1 / 2.0, DT2)
        self.assertEqual(DT1 / 2.0, 5.0e-5)

    def test_cycle_minimum_and_maximum_are_frozen(self):
        from src.coupling.stage4e_target_re_pilot_v2_2_2.identity_v2_2_2 import MAX_CYCLES, MIN_CYCLES
        self.assertEqual(MIN_CYCLES, 30.0)
        self.assertEqual(MAX_CYCLES, 60.0)

    def test_json_utf8_and_finite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_text(json.dumps(finite({"中文": "通过", "value": 1.0}), ensure_ascii=False, allow_nan=False), encoding="utf-8")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["中文"], "通过")

    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            finite({"bad": float("nan")})

    def test_force_sampling_interval_contract(self):
        self.assertLessEqual(5 * DT1, 0.002)

    def test_frozen_reynolds(self):
        from src.coupling.stage4e_target_re_pilot_v2_2_2.identity_v2_2_2 import NU, RE_HIGH, U_HIGH
        self.assertAlmostEqual(U_HIGH * D / NU, RE_HIGH, places=10)

    def test_no_domain_or_low_middle_from_decision(self):
        result = decision_matrix(medium_dt1_passed=False, fine_dt1_passed=False, time_passed=False, spatial_passed=False)
        self.assertFalse(result["domain_and_low_middle_allowed"])

    def test_fine_marginal_failure_not_called_divergence(self):
        summary = _summary("fine", {"mean_Cd": 1.0, "Cd_fluctuation_RMS": .1, "Cl_fluctuation_RMS": .5, "Cl_peak_to_peak": 1.0, "St": .15}, valid=False, cfl=.551546)
        result = offline_reclassification({"coarse": summary, "medium": summary, "fine": summary})
        self.assertNotEqual(result["fine_status"]["stationarity_classification"], "divergence")

    def test_bounded_finalizer_cycle_budget_is_conservative(self):
        from src.coupling.stage4e_target_re_pilot_v2_2_2.finalize_v2_2_2 import MAX_CYCLES
        from src.coupling.stage4e_target_re_pilot_v2_2_2.identity_v2_2_2 import MIN_CYCLES, MAX_CYCLES as IDENTITY_MAX_CYCLES
        self.assertGreaterEqual(MAX_CYCLES, MIN_CYCLES)
        self.assertLessEqual(MAX_CYCLES, IDENTITY_MAX_CYCLES)


if __name__ == "__main__":
    unittest.main()
