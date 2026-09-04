from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from coupling.stage306_offline_formalization_v1.audit import (
    AuditError,
    evaluate_formal_checks,
    parse_mapping_diagnostics,
    parse_openfoam_log,
    statistics_from_samples,
    validate_checkpoints,
)


class OpenFoamLogTests(unittest.TestCase):
    def write_log(self, text: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "fluid.stdout"
        path.write_text(text, encoding="utf-8")
        return path

    def test_parses_complete_quality_log(self) -> None:
        path = self.write_log(
            "Courant Number mean: 0.01 max: 0.61\n"
            "Time = 250s\n"
            "time step continuity errors : sum local = 1e-10, global = -2e-13, cumulative = 3e-11\n"
            "End\n"
        )
        result = parse_openfoam_log(path)
        self.assertEqual(result["courant_count"], 1)
        self.assertEqual(result["continuity_global_count"], 1)
        self.assertAlmostEqual(result["courant_max"], 0.61)
        self.assertAlmostEqual(result["continuity_global_abs_max"], 2e-13)

    def test_missing_or_truncated_quality_log_fails_closed(self) -> None:
        path = self.write_log("Courant Number mean: 0.01 max: 0.2\n")
        with self.assertRaises(AuditError):
            parse_openfoam_log(path)

    def test_nan_quality_value_fails_closed(self) -> None:
        path = self.write_log(
            "Courant Number mean: 0.01 max: NaN\n"
            "time step continuity errors : sum local = 1e-10, global = 2e-13, cumulative = 3e-11\nEnd\n"
        )
        with self.assertRaisesRegex(AuditError, "NaN/Inf"):
            parse_openfoam_log(path)


class IdentityTests(unittest.TestCase):
    def temporary_jsonl(self, rows: list[dict[str, object]]) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "evidence.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    @staticmethod
    def mapping_row(step: int) -> dict[str, object]:
        time_s = step * 0.005
        return {
            "global_step": step,
            "case_local_bridge_step": step,
            "time_s": time_s,
            "integer_tick": int(round(time_s * 1e9)),
            "fluid_resultant": [1.0, math.sin(time_s), 0.0],
            "mapped_resultant": [1.0, math.sin(time_s), 0.0],
            "virtual_work_error": 0.0,
            "force_balance_error": 0.0,
            "moment_balance_error": 0.0,
            "force_hashes": ["a" * 64, "b" * 64, "c" * 64],
        }

    def test_mapping_identity_discontinuity_fails_closed(self) -> None:
        rows = [self.mapping_row(1), self.mapping_row(3)]
        with self.assertRaisesRegex(AuditError, "global_step discontinuity"):
            parse_mapping_diagnostics(self.temporary_jsonl(rows), source_step=0, source_time_s=0.0, dt_s=0.005, expected_count=2, slice_count=3)

    def test_mapping_inf_fails_closed(self) -> None:
        row = self.mapping_row(1)
        row["virtual_work_error"] = float("inf")
        with self.assertRaisesRegex(AuditError, "NaN/Inf"):
            parse_mapping_diagnostics(self.temporary_jsonl([row]), source_step=0, source_time_s=0.0, dt_s=0.005, expected_count=1, slice_count=3)

    def test_checkpoint_tick_mismatch_fails_closed(self) -> None:
        row = {
            "global_step": 100,
            "case_local_bridge_step": 100,
            "time_s": 0.5,
            "integer_tick": 1,
            "worker_payload_sha256": "a" * 64,
            "q_sha256": "b" * 64,
        }
        with self.assertRaisesRegex(AuditError, "tick mismatch"):
            validate_checkpoints(self.temporary_jsonl([row]), source_step=0, source_time_s=0.0, target_step=100, dt_s=0.005)


class FormalDecisionTests(unittest.TestCase):
    @staticmethod
    def quality(cfl: float = 0.6) -> list[dict[str, object]]:
        return [
            {"courant_count": 100, "courant_max": cfl, "continuity_global_count": 500, "continuity_global_abs_max": 1e-12, "finite": True}
            for _ in range(3)
        ]

    @staticmethod
    def passing_statistics() -> dict[str, object]:
        return {
            "late_window_available": True,
            "late_cycle_count": 15,
            "windows": [{}, {}, {}],
            "frequency_drift_fraction": 0.01,
            "rms_drift_fraction": 0.01,
            "peak_to_peak_drift_fraction": 0.01,
            "mean_span_over_average_rms": 0.01,
            "fft_peak_relative_difference": 0.01,
        }

    def test_cfl_at_limit_fails_closed(self) -> None:
        checks = evaluate_formal_checks(self.passing_statistics(), self.quality(0.8))
        self.assertFalse(checks["courant_max_lt_0_8"])

    def test_missing_slice_quality_fails_closed(self) -> None:
        checks = evaluate_formal_checks(self.passing_statistics(), self.quality()[:2])
        self.assertFalse(checks["three_slice_quality_evidence_present"])

    def test_frequency_drift_failure_is_detected(self) -> None:
        summary = self.passing_statistics()
        summary["frequency_drift_fraction"] = 0.051
        checks = evaluate_formal_checks(summary, self.quality())
        self.assertFalse(checks["frequency_drift_le_5pct"])

    def test_insufficient_cycles_are_not_formalized(self) -> None:
        samples = [{"time_s": index * 0.05, "force_y": math.sin(2 * math.pi * 0.16 * index * 0.05)} for index in range(1000)]
        summary = statistics_from_samples(samples, required_cycles=15, fft_frequency_override=0.16)
        self.assertFalse(summary["late_window_available"])

    def test_stable_fifteen_cycle_fixture_passes_statistics(self) -> None:
        samples = [{"time_s": index * 0.05, "force_y": math.sin(2 * math.pi * 0.16 * index * 0.05)} for index in range(2200)]
        summary = statistics_from_samples(samples, required_cycles=15, fft_frequency_override=0.16)
        checks = evaluate_formal_checks(summary, self.quality())
        self.assertTrue(all(checks.values()))


if __name__ == "__main__":
    unittest.main()
