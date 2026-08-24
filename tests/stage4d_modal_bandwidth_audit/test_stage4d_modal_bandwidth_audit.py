import hashlib
import json
import math
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT_ROOT / "results" / "07_stage4d_c_modal_bandwidth_audit_v3"


def read_json(name):
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_finite(testcase, value):
    if isinstance(value, dict):
        for item in value.values():
            assert_finite(testcase, item)
    elif isinstance(value, list):
        for item in value:
            assert_finite(testcase, item)
    elif isinstance(value, float):
        testcase.assertTrue(math.isfinite(value))


class Stage4DModalBandwidthTests(unittest.TestCase):
    def test_input_hashes_recompute_and_identity_has_no_absolute_path(self):
        audit = read_json("input_hash_audit.json")
        self.assertEqual(audit["protocol_version"], "0.2.1")
        self.assertEqual(audit["manifest_sha256"], "d53ae3578f269e94f9fe02f691e1cc150b9dcb2563f837d222eb3c750e6a0ed3")
        self.assertTrue(audit["identity_hash_excludes_absolute_paths"])
        for entry in audit["source_inputs"]:
            label = entry["label"]
            if label == "raw_replay_json":
                path = PROJECT_ROOT / "results/07_stage4d_c_time_diagnostics/ancf_replay_raw.json"
            elif label == "sol_review_json":
                path = PROJECT_ROOT / "results/07_stage4d_c_time_diagnostics/stage4d_c_a_v2_sol_review.json"
            elif label == "v3_developed_flow_bank":
                path = PROJECT_ROOT / "results/06_developed_flow_v3/developed_flow_bank_v3.json"
            elif label == "diagnostic_python":
                path = PROJECT_ROOT / "src/coupling/stage4d_time_diagnostics/diagnostics.py"
            elif label == "diagnostic_matlab":
                path = PROJECT_ROOT / "src/coupling/stage4d_time_diagnostics/ancf_diagnostic_replay.m"
            else:
                path = PROJECT_ROOT / "results/07_stage4d_c_time_diagnostics" / {
                    "state_semantics_json": "state_semantics_audit.json",
                    "dynamic_metrics_json": "dynamic_metric_reanalysis.json",
                    "newmark_v2_json": "newmark_dispersion_audit.json",
                    "release_replay_json": "release_force_replay.json",
                    "preload_replay_json": "preload_force_replay.json",
                    "force_input_json": "force_replay_input.json",
                    "force_source_audit_json": "force_replay_source_audit.json",
                }[label]
            self.assertEqual(sha256(path), entry["sha256"], label)

    def test_complete_modal_system_matches_free_dofs(self):
        audit = read_json("modal_system_audit.json")
        self.assertEqual(audit["nElem"], 2)
        self.assertEqual(audit["free_dof_count"], audit["mode_count"])
        self.assertEqual(audit["mode_count"], 13)
        self.assertTrue(audit["all_free_modes_retained"])
        self.assertLess(audit["M_orthogonality_max_abs"], 1.0e-12)
        self.assertLess(audit["K_diagonal_relative_error"], 1.0e-12)
        self.assertEqual(audit["fixed_modal_max_abs"], 0.0)
        self.assertGreater(audit["mass_min_eigenvalue"], 0.0)
        self.assertGreater(audit["stiffness_min_eigenvalue"], 0.0)
        assert_finite(self, audit)

    def test_full_state_and_H_reconstruction(self):
        result = read_json("full_modal_reconstruction.json")
        self.assertTrue(result["all_pass"])
        for run in result["runs"].values():
            for key in (
                "q_dynamic_relative_l2",
                "qdot_relative_l2",
                "qddot_relative_l2",
                "slice_position_H_reconstruction_relative_l2",
                "slice_velocity_H_reconstruction_relative_l2",
                "slice_acceleration_H_reconstruction_relative_l2",
            ):
                self.assertLessEqual(run[key], 1.0e-9, key)

    def test_H_HT_power_and_work_consistency(self):
        result = read_json("modal_energy_work_audit.json")
        self.assertTrue(result["all_power_consistency_pass"])
        for run in result["runs"].values():
            self.assertLessEqual(run["power_consistency"]["relative_direct_minus_H_work"], 1.0e-9)
            self.assertLessEqual(run["power_consistency"]["relative_H_minus_modal_work"], 1.0e-9)
            self.assertGreater(run["totals"]["absolute_direct_Fv_work_J"], 0.0)
            self.assertEqual(len(run["modes"]), 13)

    def test_velocity_attribution_preserves_frozen_metric_and_reports_strict_alignment(self):
        result = read_json("slice_velocity_error_attribution.json")
        self.assertEqual(len(result["pairs"]), 3)
        finest = result["pairs"][-1]
        self.assertAlmostEqual(finest["frozen_v2_reported_slice_velocity_nrmse"], 0.07126413802276343)
        self.assertGreater(finest["timestamp_aligned_full_slice_velocity_nrmse"], 0.08)
        self.assertEqual(finest["time_alignment_max_abs_error_s"], 0.0)
        self.assertIn("modes_6_plus", finest["frequency_bands"])
        self.assertGreater(finest["frequency_bands"]["modes_6_plus"]["fine_band_velocity_rms_mps"], 0.0)
        self.assertEqual(len(finest["largest_five_leave_one_mode_changes"]), 5)

    def test_newmark_all_mode_dispersion_has_six_steps_and_campaign_is_theoretical(self):
        result = read_json("newmark_all_mode_dispersion.json")
        self.assertEqual(result["nElem"], 2)
        self.assertEqual(result["mode_count"], 13)
        self.assertTrue(result["campaign_estimate_is_theoretical_only"])
        for mode in result["modes"]:
            self.assertEqual(len(mode["time_steps"]), 6)
            self.assertGreater(mode["required_dt_for_0p25s_phase_error_le_0p05_rad_s"], 0.0)
            assert_finite(self, mode)

    def test_engineering_bandwidth_and_physical_scaling_are_explicit(self):
        bandwidth = read_json("engineering_bandwidth_candidate.json")
        self.assertEqual(bandwidth["status"], "candidate_not_frozen")
        self.assertEqual(bandwidth["candidate"]["retained_mode_count"], 7)
        self.assertGreaterEqual(bandwidth["candidate"]["displacement_mass_norm_cumulative_fraction"], 0.99)
        self.assertGreaterEqual(bandwidth["candidate"]["kinetic_energy_cumulative_fraction"], 0.99)
        self.assertLessEqual(bandwidth["candidate"]["slice_velocity_rms_reconstruction_error"], 0.01)
        self.assertGreaterEqual(bandwidth["candidate"]["absolute_work_cumulative_fraction"], 0.99)
        scaling = read_json("viv_physical_scaling_audit.json")
        self.assertFalse(scaling["baseline_classification"]["viv_physical_validation_baseline"])
        self.assertGreater(scaling["structural_to_shedding_ratio_first_mode"]["re80"], 150.0)
        self.assertLess(scaling["first_mode_reduced_velocity"]["re120"], 0.1)

    def test_nElem_mismatch_is_rejected_by_audit_contract(self):
        import src.coupling.stage4d_modal_bandwidth_audit.audit as audit

        with self.assertRaises(ValueError):
            audit.modal_system_audit({"nElem": 4}, {"q_static": [0.0]})

    def test_no_real_openfoam_campaign(self):
        candidate = read_json("stage4d_c_a_v3_candidate_summary.json")
        self.assertFalse(candidate["openfoam_invoked"])
        self.assertFalse(candidate["checkMesh_invoked"])
        self.assertFalse(candidate["setFields_invoked"])
        self.assertFalse(candidate["new_real_cfd_campaign_authorized"])
        self.assertTrue(candidate["diagnostic_only"])


if __name__ == "__main__":
    unittest.main()
