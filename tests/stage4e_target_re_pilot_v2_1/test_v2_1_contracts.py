import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.coupling.stage4e_target_re_pilot_v2.identity_v2 import canonical_json_bytes
from src.coupling.stage4e_target_re_pilot_v2_1.analysis_v2_1 import field_equivalence, numeric_file_values, output_metrics, parse_raw_force_history, parse_yplus_file
from src.coupling.stage4e_target_re_pilot_v2_1.case_generator_v2_1 import FIELD_WRITE_INTERVAL_STEPS, FORCE_WRITE_INTERVAL_STEPS, PRODUCTION_DT_S, control_dict_v2_1, case_freshness
from src.coupling.stage4e_target_re_pilot_v2_1.online_cfl_monitor import IncrementalCFLMonitor
from src.coupling.stage4e_target_re_pilot_v2_1.runner_v2_1 import OwnedRunnerV21


class V21ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get("B2A_V2_1_TEST_TMP") or os.environ.get("TMPDIR") or "D:\\研二文件\\开题准备\\CFD_ANCF_VIV\\runtime"
        Path(root).mkdir(parents=True, exist_ok=True)
        cls.tmp = tempfile.TemporaryDirectory(dir=root)
        cls.tmp_path = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_warmup_has_adaptive_time_step(self):
        text = control_dict_v2_1(0.4, end_time=0.2, model="laminar", mode="warmup")
        self.assertIn("adjustTimeStep yes", text)
        self.assertIn("maxDeltaT 0.0004", text)

    def test_production_has_fixed_time_step(self):
        text = control_dict_v2_1(0.4, end_time=3.0, model="laminar", mode="production")
        self.assertIn("startFrom latestTime", text)
        self.assertIn("adjustTimeStep no", text)
        self.assertIn("deltaT 0.0004", text)

    def test_yplus_not_written_in_production_control(self):
        text = control_dict_v2_1(0.4, end_time=3.0, model="laminar", mode="production")
        self.assertNotIn("yPlus", text)
        self.assertNotIn("writeInterval 1;", text)

    def test_yplus_is_only_explicit_benchmark_option(self):
        text = control_dict_v2_1(0.4, end_time=0.4, model="laminar", mode="io_benchmark_old", include_yplus=True)
        self.assertIn("yPlus", text)
        self.assertIn("writeInterval 1", text)
        new_text = control_dict_v2_1(0.4, end_time=0.4, model="laminar", mode="io_benchmark_new", include_yplus=False)
        self.assertNotIn("yPlus", new_text)

    def test_force_sampling_interval_is_five_steps(self):
        text = control_dict_v2_1(0.4, end_time=3.0, model="laminar", mode="production")
        self.assertIn(f"writeInterval {FORCE_WRITE_INTERVAL_STEPS};", text)

    def test_field_sampling_interval_is_sparse(self):
        text = control_dict_v2_1(0.4, end_time=3.0, model="laminar", mode="production")
        self.assertIn(f"writeInterval {FIELD_WRITE_INTERVAL_STEPS};", text)

    def test_force_sampling_meets_100_samples_per_fastest_cycle(self):
        f_max = 0.25 * 0.43414375179615955 / 0.02841
        samples = 1.0 / f_max / (FORCE_WRITE_INTERVAL_STEPS * PRODUCTION_DT_S)
        self.assertGreaterEqual(samples, 100.0)

    def test_online_cfl_049_continues(self):
        monitor = IncrementalCFLMonitor()
        self.assertIsNone(monitor.feed("Courant Number mean: 0.1 max: 0.49\n"))
        self.assertFalse(monitor.stopped)

    def test_online_cfl_0799_continues(self):
        monitor = IncrementalCFLMonitor()
        self.assertIsNone(monitor.feed("Courant Number mean: 0.1 max: 0.799\n"))
        self.assertFalse(monitor.stopped)

    def test_online_cfl_08_stops(self):
        monitor = IncrementalCFLMonitor()
        event = monitor.feed("Courant Number mean: 0.1 max: 0.8\n")
        self.assertEqual(event["reason"], "max_cfl_ge_0.8")

    def test_online_cfl_12_stops(self):
        monitor = IncrementalCFLMonitor()
        event = monitor.feed("Courant Number mean: 0.1 max: 1.2\n")
        self.assertEqual(event["reason"], "max_cfl_ge_0.8")

    def test_online_cfl_nan_stops(self):
        monitor = IncrementalCFLMonitor()
        event = monitor.feed("Courant Number mean: nan max: 0.2\n")
        self.assertEqual(event["reason"], "non_finite_cfl")

    def test_online_cfl_inf_stops(self):
        monitor = IncrementalCFLMonitor()
        event = monitor.feed("Courant Number mean: 0.1 max: Inf\n")
        self.assertEqual(event["reason"], "non_finite_cfl")

    def test_incomplete_log_line_waits_for_next_chunk(self):
        monitor = IncrementalCFLMonitor()
        self.assertIsNone(monitor.feed("Courant Number mean: 0.1 max: 0."))
        event = monitor.feed("8\n")
        self.assertEqual(event["reason"], "max_cfl_ge_0.8")

    def test_incomplete_non_courant_line_does_not_stop(self):
        monitor = IncrementalCFLMonitor()
        self.assertIsNone(monitor.feed("Courant Number mean: 0.1 max: 0."))
        self.assertFalse(monitor.stopped)

    def test_monitor_records_physical_time(self):
        monitor = IncrementalCFLMonitor()
        event = monitor.feed("Time = 1.25s\nCourant Number mean: 0.1 max: 0.8\n")
        self.assertEqual(event["time_s"], 1.25)

    def test_production_has_no_adjust_max_delta(self):
        text = control_dict_v2_1(0.4, end_time=3.0, model="kOmegaSST", mode="production")
        self.assertNotIn("maxDeltaT", text)

    def test_case_freshness_rejects_numeric_time(self):
        case = self.tmp_path / "freshness"
        (case / "0").mkdir(parents=True)
        (case / "constant").mkdir()
        (case / "system").mkdir()
        (case / "0.2").mkdir()
        self.assertFalse(case_freshness(case)["passed"])

    def test_numeric_field_values_reject_nonfinite(self):
        path = self.tmp_path / "badField"
        path.write_text("internalField uniform nan;\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            numeric_file_values(path)

    def test_field_equivalence_accepts_identical_fields(self):
        a, b = self.tmp_path / "a", self.tmp_path / "b"
        for case in (a, b):
            (case / "0.4").mkdir(parents=True)
            (case / "0.4" / "U").write_text("internalField uniform (1 2 3);\n", encoding="utf-8")
            (case / "0.4" / "p").write_text("internalField uniform 4;\n", encoding="utf-8")
        self.assertTrue(field_equivalence(a, b)["passed"])

    def test_output_directory_estimate_is_below_fifty(self):
        estimated = 1 + int(np.ceil(10.5 / (FIELD_WRITE_INTERVAL_STEPS * PRODUCTION_DT_S)))
        self.assertLessEqual(estimated, 50)

    def test_json_nan_is_rejected(self):
        with self.assertRaises(ValueError):
            canonical_json_bytes({"bad": float("nan")})

    def test_json_inf_is_rejected(self):
        with self.assertRaises(ValueError):
            canonical_json_bytes({"bad": float("inf")})

    def test_runner_source_uses_exact_process_stop(self):
        source = inspect.getsource(OwnedRunnerV21._kill_exact_tree)
        self.assertIn("managed.terminate()", source)
        self.assertIn("_descendants(pid)", source)

    def test_runner_source_has_online_monitor(self):
        source = inspect.getsource(OwnedRunnerV21.execute)
        self.assertIn("IncrementalCFLMonitor", source)
        self.assertIn("online_cfl_stop", source)

    def test_checkpoint_lineage_requires_latest_time(self):
        self.assertTrue("latestTime" in control_dict_v2_1(0.4, end_time=3.0, model="laminar", mode="production"))

    def test_production_statistics_are_separate_from_warmup(self):
        warm = control_dict_v2_1(0.4, end_time=0.2, model="laminar", mode="warmup")
        prod = control_dict_v2_1(0.4, end_time=3.0, model="laminar", mode="production")
        self.assertIn("startFrom startTime", warm)
        self.assertIn("startFrom latestTime", prod)

    def test_continuation_force_history_combines_blocks_and_deduplicates(self):
        first = self.tmp_path / "force_a.dat"
        second = self.tmp_path / "force_b.dat"
        first.write_text("0.2 1 0 0 0 0 0\n0.4 2 0 0 0 0 0\n", encoding="utf-8")
        second.write_text("0.4 2 0 0 0 0 0\n0.6 3 0 0 0 0 0\n", encoding="utf-8")
        history = parse_raw_force_history([second, first])
        self.assertTrue(history["available"])
        self.assertEqual(history["rows"], 3)
        self.assertEqual(history["time_s"].tolist(), [0.2, 0.4, 0.6])

    def test_sst_yplus_uses_solver_postprocess_context(self):
        from src.coupling.stage4e_target_re_pilot_v2_1 import pilot_v2_1
        source = inspect.getsource(pilot_v2_1._run_model)
        self.assertIn('"pimpleFoam"', source)
        self.assertIn("-postProcess -func yPlus -latestTime", source)

    def test_yplus_field_reports_independent_p95_and_summary_crosscheck(self):
        field = self.tmp_path / "10" / "yPlus"
        field.parent.mkdir(parents=True)
        field.write_text("boundaryField { cylinder { type calculated; value nonuniform List<scalar> 3 (1 2 3); } }\n", encoding="utf-8")
        summary = self.tmp_path / "10" / "yPlus.dat"
        summary.write_text("# Time patch min max average\n10 cylinder 1 3 2\n", encoding="utf-8")
        audit = parse_yplus_file(field, summary_path=summary)
        self.assertEqual(audit["sample_count"], 3)
        self.assertEqual(audit["p95_y_plus"], 2.9)
        self.assertTrue(audit["summary_crosscheck_passed"])


if __name__ == "__main__":
    unittest.main()
