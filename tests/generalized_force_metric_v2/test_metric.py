from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.generalized_force_metric_v2 import evaluate, freeze_contract  # noqa: E402


class GeneralizedForceMetricV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = freeze_contract(3.125)

    def test_dimensionally_separates_position_and_slope_dofs(self) -> None:
        result = evaluate([0.0] * 6, [0.0] * 6, [[0.0] * 6] * 3, contract=self.contract)
        self.assertEqual(result["GENERALIZED_FORCE_MAPPING_V2"], "PASS")
        self.assertEqual(result["per_dof"][0]["q_unit"], "m")
        self.assertEqual(result["per_dof"][0]["Q_unit"], "N")
        self.assertEqual(result["per_dof"][3]["q_unit"], "1 (m/m)")
        self.assertEqual(result["per_dof"][3]["Q_unit"], "N*m")

    def test_cancellation_uses_contribution_scale_not_net_total(self) -> None:
        # Total is exactly zero, but the scale is 200 N: no cancellation denominator.
        result = evaluate([0.0] * 6, [1e-12] + [0.0] * 5,
                          [[100.0] + [0.0] * 5, [-100.0] + [0.0] * 5, [0.0] * 6],
                          contract=self.contract)
        dof = result["per_dof"][0]
        self.assertEqual(dof["contribution_scale"], 200.0)
        self.assertGreater(dof["threshold"], dof["atol"])
        self.assertTrue(dof["pass"])

    def test_zero_contribution_uses_absolute_floor(self) -> None:
        result = evaluate([0.0] * 6, [1e-10] + [0.0] * 5, [[0.0] * 6] * 3,
                          contract=self.contract)
        self.assertEqual(result["GENERALIZED_FORCE_MAPPING_V2"], "FAIL")
        self.assertFalse(result["per_dof"][0]["pass"])


if __name__ == "__main__":
    unittest.main()
