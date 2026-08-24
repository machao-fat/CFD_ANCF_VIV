import json
import math
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT_ROOT / "results" / "07_stage4d_c_time_diagnostics"


def read_json(name):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def assert_finite(testcase, value):
    if isinstance(value, dict):
        for item in value.values():
            assert_finite(testcase, item)
    elif isinstance(value, list):
        for item in value:
            assert_finite(testcase, item)
    elif isinstance(value, float):
        testcase.assertTrue(math.isfinite(value))


class Stage4DTimeDiagnosticsTests(unittest.TestCase):
    def test_state_timestamps_and_newmark_kinematics(self):
        audit = read_json("state_semantics_audit.json")
        self.assertFalse(audit["time_label_error_found"])
        for run in audit["runs"].values():
            self.assertEqual(run["duplicate_command_ids"], [])
            self.assertTrue(run["finite"])
            self.assertLess(run["newmark_qv"]["max_abs_residual"], 1.0e-15)
            self.assertLess(run["newmark_qa"]["max_abs_residual"], 1.0e-15)
            self.assertEqual(run["checkpoint_state_consistency"]["max_save_vs_correct_q_abs"], 0.0)
            self.assertEqual(run["checkpoint_state_consistency"]["max_finalize_vs_correct_q_abs"], 0.0)
            for row in run["timestamp_rows"]:
                self.assertLessEqual(row["time_error_s"], 1.0e-12)

    def test_dynamic_metrics_remove_static_configuration(self):
        metrics = read_json("dynamic_metric_reanalysis.json")
        self.assertLess(metrics["full_q_nrmse_not_used"], 1.0e-5)
        self.assertGreater(metrics["dynamic_free_q_nrmse"], 1.0e-2)
        self.assertEqual(len(metrics["free_indices_1based"]), 13)
        self.assertEqual(set(metrics["slice_center_metrics"]), {"0", "1", "2"})
        assert_finite(self, metrics)

    def test_newmark_formula_and_second_order_trend(self):
        audit = read_json("newmark_dispersion_audit.json")
        self.assertEqual(audit["duration_s"], 0.25)
        first = audit["frequencies"][0]
        self.assertAlmostEqual(first["frequency_Hz"], 27.50934575579332)
        rows = first["time_steps"]
        expected = (2.0 / rows[0]["dt_s"]) * math.atan(first["omega_radps"] * rows[0]["dt_s"] / 2.0) / (2.0 * math.pi)
        self.assertAlmostEqual(rows[0]["numerical_frequency_Hz"], expected, places=12)
        self.assertGreater(rows[0]["displacement_nrmse_observed_order_to_next"], 1.8)
        self.assertGreater(rows[1]["displacement_nrmse_observed_order_to_next"], 1.8)
        self.assertLess(rows[-1]["displacement_nrmse"], rows[0]["displacement_nrmse"])

    def test_force_samples_are_exact_and_recommendation_is_separate(self):
        source = read_json("force_replay_source_audit.json")
        force = read_json("force_replay_input.json")
        self.assertEqual(source["sample_count"], 200)
        self.assertTrue(source["original_samples_exact"])
        self.assertFalse(source["filtering"])
        self.assertFalse(source["smoothing"])
        self.assertEqual(force["force"]["times_s"][0], 0.0)
        self.assertEqual(len(force["force"]["times_s"]), 201)
        self.assertIn("piecewise_linear", source["interpolation_rule"])
        recommendation = read_json("real_dt_pair_recommendation.json")
        self.assertIsNone(recommendation["recommended_release_real_dt_pair"])
        self.assertIsNone(recommendation["recommended_preload_real_dt_pair"])
        self.assertTrue(recommendation["time_shift_not_used_for_recommendation"])

    def test_release_and_preload_are_distinct_offline_routes(self):
        release = read_json("release_force_replay.json")
        preload = read_json("preload_force_replay.json")
        self.assertEqual(release["route"], "release")
        self.assertEqual(preload["route"], "preload")
        self.assertNotEqual(release["pairs"][0]["q_dynamic_free_nrmse"], preload["pairs"][0]["q_dynamic_free_nrmse"])
        init = read_json("initialization_comparison.json")
        self.assertTrue(init["release"]["static_diagnostics"]["converged"])
        self.assertTrue(init["preload"]["static_diagnostics"]["converged"])
        self.assertEqual(init["release"]["initial_qdot_norm"], 0.0)
        self.assertEqual(init["preload"]["initial_qddot_norm"], 0.0)
        self.assertIn("offline candidate only", init["interpretation"])

    def test_no_real_openfoam_campaign_was_invoked(self):
        candidate = read_json("stage4d_c_a_v2_candidate_summary.json")
        self.assertTrue(candidate["diagnostic_only"])
        self.assertFalse(candidate["new_real_openfoam_campaign"])
        self.assertFalse(candidate["openfoam_invoked"])
        self.assertFalse(candidate["checkMesh_invoked"])
        self.assertFalse(candidate["setFields_invoked"])
        self.assertTrue(candidate["sol_decision_required"])

    def test_outputs_are_finite(self):
        for name in (
            "dynamic_metric_reanalysis.json",
            "newmark_dispersion_audit.json",
            "release_force_replay.json",
            "preload_force_replay.json",
            "initialization_comparison.json",
        ):
            assert_finite(self, read_json(name))


if __name__ == "__main__":
    unittest.main()
