"""Regression checks for the isolated ANCF modal/free-vibration evidence."""
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULT = ROOT / "results/ancf_free_decay/undamped/cpp_50m_fixture_v2.json"


class AncfModalFreeEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not RESULT.is_file():
            raise unittest.SkipTest("run tools/solver_validation_v3/run_ancf_modal_free.py first")
        cls.result = json.loads(RESULT.read_text(encoding="utf-8"))

    def test_six_mass_normalized_positive_modes_are_retained(self) -> None:
        modes = self.result["cpp"]["modes"]
        self.assertEqual(len(modes), 6)
        self.assertTrue(all(float(mode["frequency_hz"]) > 0.0 for mode in modes))
        self.assertTrue(all(abs(float(mode["mass_norm"]) - 1.0) < 1.0e-10 for mode in modes))
        self.assertTrue(all(float(mode["residual"]) < 2.0e-8 for mode in modes))

    def test_zero_fluid_undamped_motion_persists_at_first_mode(self) -> None:
        contract = self.result["contract"]
        self.assertTrue(all(float(value) == 0.0 for value in contract["fluid_slice_force"]))
        self.assertEqual(float(contract["damping_alpha"]), 0.0)
        self.assertEqual(float(contract["damping_beta"]), 0.0)
        first_mode = float(self.result["cpp"]["modes"][0]["frequency_hz"])
        observed = float(self.result["analysis"]["modal_coordinate_1_frequency_hz"])
        self.assertLess(abs(observed - first_mode), 0.02)
        self.assertLess(float(self.result["cpp"]["summary"]["relative_incremental_energy_change"]), 1.0e-3)
        self.assertGreater(float(self.result["analysis"]["slice_observables"]["slice_0001"]["y_peak_to_peak_m"]), 1.0e-5)
        self.assertTrue(all("strain_energy_J" in row for row in self.result["cpp"]["samples"]))

    def test_reference_status_is_not_misrepresented(self) -> None:
        self.assertEqual(self.result["matlab_comparison"]["status"], "reference_not_available")
        self.assertEqual(self.result["real_process_starts"], {"CFD": 0, "MATLAB": 0, "OpenFOAM": 0, "WSL_OpenFOAM": 0})


if __name__ == "__main__":
    unittest.main()
