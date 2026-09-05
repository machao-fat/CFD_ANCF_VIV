from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULT = ROOT / "results" / "validation_matlab_cpp_v1" / "phase_a_result.json"


class PhaseAEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(RESULT.read_text(encoding="utf-8"))

    def test_frozen_matlab_cpp_contract_passes(self) -> None:
        self.assertEqual(self.data["status"], "pass")
        self.assertEqual(self.data["matlab_execution"]["status"], "pass")
        self.assertEqual(self.data["contract"]["duration_s"], 50.0)
        self.assertEqual(self.data["contract"]["damping_alpha"], 0.0)
        self.assertEqual(self.data["contract"]["damping_beta"], 0.0)

    def test_static_modal_dynamic_and_core_evidence(self) -> None:
        comparison = self.data["comparison"]
        self.assertLessEqual(comparison["static"]["normalized_l2_shape_error"], 5.0e-3)
        self.assertEqual(len(comparison["modal"]), 6)
        for mode in comparison["modal"]:
            self.assertLessEqual(mode["relative_frequency_error"], 5.0e-3)
            self.assertGreater(mode["MAC"], 0.95)
        for station in comparison["dynamic"]["slices"].values():
            self.assertLessEqual(station["relative_frequency_error"], 5.0e-3)
            self.assertLessEqual(station["rms_relative_error"], 2.0e-2)
            self.assertLessEqual(station["y_time_series_nrmse"], 2.0e-2)
        self.assertLess(comparison["core"]["mass_matrix"]["relative_l2"], 1.0e-12)
        self.assertLess(comparison["core"]["internal_force"]["relative_l2"], 1.0e-12)
        self.assertLess(comparison["core"]["tangent_matrix"]["relative_l2"], 1.0e-12)


if __name__ == "__main__":
    unittest.main()
