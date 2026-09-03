import importlib.util
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "src/coupling/three_slice_statistics_v2/metrics.py"
spec = importlib.util.spec_from_file_location("three_slice_statistics_v2", SCRIPT)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ThreeSliceStatisticsV2Tests(unittest.TestCase):
    def rows(self):
        result = []
        for index in range(2400):
            time_s = index * 0.05
            result.append({
                "time_s": time_s,
                "slice_force_y": {
                    "slice_0000": 5.0 + math.sin(2.0 * math.pi * 0.2 * time_s),
                    "slice_0001": -3.0 + 1.1 * math.sin(2.0 * math.pi * 0.2 * time_s + 0.3),
                    "slice_0002": 2.0 + 0.9 * math.sin(2.0 * math.pi * 0.2 * time_s - 0.2),
                },
                "structure_displacement_y": 0.01 + 0.2 * math.sin(2.0 * math.pi * 0.2 * time_s),
            })
        return result

    def test_contract_and_demeaned_rms(self):
        contract = {
            "schema_version": 2, "slice_ids": list(m.SLICE_IDS),
            "primary_observables": ["per_slice_force_y", "structure_displacement_y", "phase_relation"],
            "amplitude_definition": "demeaned_rms_and_peak_to_peak",
            "frequency_methods": ["detrended_fft", "prominent_positive_peaks"],
            "physical_total_force_policy": "not_evaluable_from_legacy_evidence",
            "quality_gate_separate": True, "legacy_gate_unchanged": True,
            "missing_value_policy": "fail_closed_no_interpolation", "real_process_allowed": False,
        }
        self.assertEqual(m.validate_contract(contract)["status"], "pass")
        self.assertAlmostEqual(m.demeaned_rms([10.0, 12.0, 10.0, 8.0]), math.sqrt(2.0))

    def test_window_does_not_promote_average_force_to_physical_total(self):
        result = m.summarize_window(self.rows(), start_time_s=0.0, end_time_s=40.0, minimum_separation_s=3.0, prominence_fraction=0.1)
        self.assertEqual(result["physical_total_force"]["status"], "not_evaluable")
        self.assertAlmostEqual(result["per_slice_force_y"]["slice_0000"]["fft_frequency_hz"], 0.2, places=6)
        self.assertGreater(result["per_slice_force_y"]["slice_0000"]["demeaned_rms"], 0.7)

    def test_duplicate_time_fails_closed(self):
        rows = self.rows()[:4]
        rows[2]["time_s"] = rows[1]["time_s"]
        with self.assertRaises(m.StatisticalContractError):
            m.summarize_window(rows, start_time_s=0.0, end_time_s=1.0, minimum_separation_s=3.0, prominence_fraction=0.1)

    def test_trailing_stability_excludes_average_force(self):
        windows = [m.summarize_window(self.rows(), start_time_s=start, end_time_s=start + 40.0, minimum_separation_s=3.0, prominence_fraction=0.1) for start in (0.0, 40.0, 80.0)]
        result = m.assess_trailing_windows(
            windows,
            amplitude_drift_limit=0.05,
            frequency_drift_limit=0.05,
            phase_drift_limit_deg=45.0,
            phase_correlation_min=0.9,
        )
        self.assertTrue(result["primary_statistics_stable"])

    def test_phase_drift_prevents_primary_stability(self):
        windows = [m.summarize_window(self.rows(), start_time_s=start, end_time_s=start + 40.0, minimum_separation_s=3.0, prominence_fraction=0.1) for start in (0.0, 40.0, 80.0)]
        for window, phase in zip(windows, (0.0, 80.0, 160.0)):
            window["phase_relation"]["slice_0000__slice_0001"]["phase_deg"] = phase
        result = m.assess_trailing_windows(
            windows,
            amplitude_drift_limit=0.05,
            frequency_drift_limit=0.05,
            phase_drift_limit_deg=45.0,
            phase_correlation_min=0.9,
        )
        self.assertFalse(result["phase"]["slice_0000__slice_0001"]["stable"])
        self.assertFalse(result["primary_statistics_stable"])


if __name__ == "__main__":
    unittest.main()
