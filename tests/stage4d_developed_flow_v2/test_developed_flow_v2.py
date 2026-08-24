from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.coupling.stage4d_campaign.developed_flow import DevelopedFlowError, ForceSample
from src.coupling.stage4d_campaign.developed_flow_v2 import (
    DT_S,
    MAX_PHYSICAL_TIME_S,
    SOURCE_FLOW_ROOT,
    SOURCE_RESULT_ROOT,
    _prepare_continuation_case,
    analyze_force_history_v2,
    merge_force_histories,
    prepare_v2_fresh_case,
    read_force_csv,
    rewrite_initial_velocity_files,
    zero_crossing_frequency,
)


class DevelopedFlowV2Tests(unittest.TestCase):
    @staticmethod
    def _samples(*, U: float = 1.0, frequency: float = 0.16, amplitude: float = 0.1, duration: float = 200.0, offset: float = 0.2) -> list[ForceSample]:
        times = np.arange(0.0, duration, DT_S)
        values = offset + amplitude * np.sin(2.0 * np.pi * frequency * times)
        drag = 1.2 + 0.02 * np.sin(2.0 * np.pi * frequency * times + 0.4)
        denominator = 0.5 * 1000.0 * U * U
        return [ForceSample(float(t), (float(denominator * cd), float(denominator * cl), 0.0)) for t, cd, cl in zip(times, drag, values)]

    def test_three_U_initial_velocity_definitions(self) -> None:
        for U in (0.8, 1.0, 1.2):
            with tempfile.TemporaryDirectory(prefix="stage4d_v2_velocity_") as directory:
                case = Path(directory) / f"re{int(U * 100)}"
                prepare_v2_fresh_case(case, U, run_id="unit", end_time_s=0.1)
                u_text = (case / "0" / "U").read_text(encoding="utf-8")
                fields_text = (case / "system" / "setFieldsDict").read_text(encoding="utf-8")
                self.assertIn(f"internalField   uniform ({U:g} 0 0)", u_text)
                self.assertIn(f"value           uniform ({U:g} 0 0)", u_text)
                self.assertIn(f"volVectorFieldValue U ({U:g} 0 0)", fields_text)
                self.assertIn(f"volVectorFieldValue U ({U:g} {0.1 * U:g} 0)", fields_text)

    def test_velocity_rewrite_uses_one_parameter_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage4d_v2_velocity_rewrite_") as directory:
            case = Path(directory) / "case"
            prepare_v2_fresh_case(case, 1.0, run_id="unit", end_time_s=0.1)
            result = rewrite_initial_velocity_files(case, 1.2)
            self.assertEqual(result["default_internal_U"], [1.2, 0.0, 0.0])
            self.assertEqual(result["inlet_U"], [1.2, 0.0, 0.0])
            self.assertEqual(result["perturbed_U"], [1.2, 0.12, 0.0])

    def test_setfields_is_not_called_by_continuation_builder(self) -> None:
        summary = json.loads((SOURCE_RESULT_ROOT / "re80" / "re80_summary.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="stage4d_v2_lineage_") as directory:
            lineage = _prepare_continuation_case(
                flow_id="re80",
                U=0.8,
                source_summary=summary,
                source_case=SOURCE_FLOW_ROOT / "re80",
                output=Path(directory) / "re80",
                run_id="unit",
            )
            self.assertFalse(lineage["setFields_called"])
            self.assertEqual(lineage["startFrom"], "latestTime")
            self.assertFalse((Path(directory) / "re80" / "0").exists())

    def test_cross_re_source_is_rejected(self) -> None:
        summary = json.loads((SOURCE_RESULT_ROOT / "re80" / "re80_summary.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="stage4d_v2_cross_re_") as directory:
            with self.assertRaises(DevelopedFlowError):
                _prepare_continuation_case(
                    flow_id="re100",
                    U=1.0,
                    source_summary=summary,
                    source_case=SOURCE_FLOW_ROOT / "re80",
                    output=Path(directory) / "re100",
                    run_id="unit",
                )

    def test_source_force_csv_is_strictly_read(self) -> None:
        samples = read_force_csv(SOURCE_RESULT_ROOT / "re80" / "force_history.csv")
        self.assertGreater(len(samples), 20000)
        self.assertAlmostEqual(samples[-1].time_s, 60.0, places=6)

    def test_merge_exact_overlap_keeps_one_value(self) -> None:
        source = self._samples(duration=1.0)
        continuation = [source[-1]] + [ForceSample(source[-1].time_s + (i + 1) * DT_S, source[-1].force_N) for i in range(15)]
        result = merge_force_histories(source, continuation)
        self.assertEqual(result["overlap_duplicates_removed"], 1)
        self.assertEqual(result["merged_sample_count"], len(source) + 15)

    def test_merge_conflicting_overlap_is_rejected(self) -> None:
        source = self._samples(duration=1.0)
        continuation = source[-16:]
        continuation[0] = ForceSample(source[-1].time_s, (continuation[0].force_N[0] + 1.0, *continuation[0].force_N[1:]))
        with self.assertRaises(DevelopedFlowError):
            merge_force_histories(source, continuation)

    def test_merge_time_gap_is_rejected(self) -> None:
        source = self._samples(duration=1.0)
        continuation = [ForceSample(source[-1].time_s + 2.0 * DT_S, source[-1].force_N)] + [ForceSample(source[-1].time_s + (i + 3) * DT_S, source[-1].force_N) for i in range(16)]
        with self.assertRaises(DevelopedFlowError):
            merge_force_histories(source, continuation)

    def test_zero_crossing_frequency(self) -> None:
        samples = self._samples(frequency=0.16, duration=80.0)
        times = [sample.time_s for sample in samples]
        values = [sample.force_N[1] for sample in samples]
        frequency = zero_crossing_frequency(times, values)
        self.assertLess(abs(frequency - 0.16), 0.002)

    def test_cl_rms_is_centered_and_dimensionless(self) -> None:
        stats = analyze_force_history_v2(self._samples(), U=1.0, discard_start_s=10.0)
        self.assertAlmostEqual(stats["window_2"]["Cl_rms"], 0.1 / math.sqrt(2.0), delta=0.002)
        self.assertGreater(stats["window_2"]["legacy_Cl_rms_raw"], stats["window_2"]["Cl_rms"] * 2.0)

    def test_cd_fluctuation_rms_is_centered(self) -> None:
        stats = analyze_force_history_v2(self._samples(), U=1.0, discard_start_s=10.0)
        self.assertAlmostEqual(stats["window_2"]["Cd_fluctuation_rms"], 0.02 / math.sqrt(2.0), delta=0.002)
        self.assertGreater(stats["window_2"]["Cd_rms"], stats["window_2"]["Cd_fluctuation_rms"] * 10.0)

    def test_chunk_rms_uses_dimensionless_cl(self) -> None:
        stats = analyze_force_history_v2(self._samples(), U=1.0, discard_start_s=10.0)
        self.assertTrue(stats["cl_chunk_rms"])
        self.assertLess(max(stats["cl_chunk_rms"]), 0.2)

    def test_fft_zero_crossing_crosscheck_is_reported(self) -> None:
        stats = analyze_force_history_v2(self._samples(), U=1.0, discard_start_s=10.0)
        self.assertIn("FFT_zero_crossing_frequency", stats["window_relative_changes"])
        self.assertLess(stats["window_2"]["frequency_crosscheck_relative_difference"], 0.03)

    def test_three_cycle_windows_are_required(self) -> None:
        stats = analyze_force_history_v2(self._samples(duration=20.0), U=1.0, discard_start_s=2.0)
        self.assertFalse(stats["criteria"]["three_complete_cycles_in_each_window"])
        self.assertFalse(stats["all_stable_criteria"])

    def test_twelve_cycle_requirement_is_explicit(self) -> None:
        stats = analyze_force_history_v2(self._samples(duration=200.0), U=1.0, discard_start_s=10.0)
        self.assertTrue(stats["criteria"]["total_complete_cycles_at_least_12"])

    def test_stable_criteria_do_not_use_single_window_only(self) -> None:
        stats = analyze_force_history_v2(self._samples(duration=200.0), U=1.0, discard_start_s=10.0)
        self.assertIn("window_1", stats)
        self.assertIn("window_2", stats)
        self.assertNotEqual(stats["window_1"]["start_time_s"], stats["window_2"]["start_time_s"])

    def test_peak_to_peak_change_is_reported(self) -> None:
        times = np.arange(0.0, 200.0, DT_S)
        normalized = np.where(times < 175.0, 0.05, 0.10) * np.sin(2.0 * np.pi * 0.16 * times) + 0.2
        denominator = 500.0
        samples = [ForceSample(float(t), (600.0, float(denominator * value), 0.0)) for t, value in zip(times, normalized)]
        stats = analyze_force_history_v2(samples, U=1.0, discard_start_s=10.0)
        self.assertGreater(stats["window_relative_changes"]["Cl_peak_to_peak"], 0.05)

    def test_upper_time_limit_is_240_seconds(self) -> None:
        self.assertEqual(MAX_PHYSICAL_TIME_S, 240.0)

    def test_bank_hash_policy_excludes_absolute_paths(self) -> None:
        identity_a = [{"flow_id": "re80", "developed_flow_sha256": "a"}]
        identity_b = [{"flow_id": "re80", "developed_flow_sha256": "a"}]
        self.assertEqual(json.dumps(identity_a, sort_keys=True), json.dumps(identity_b, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
