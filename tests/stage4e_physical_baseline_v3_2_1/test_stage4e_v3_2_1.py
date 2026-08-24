import json
import unittest
from pathlib import Path

import numpy as np

from src.coupling.multi_slice_mapping.mapping import RuntimeConfig, SchemaError, SliceManifest
from src.coupling.stage4e_physical_baseline_v3_2_1.correct_stage4e_v3_2_1 import (
    DEPTH_NOMINAL,
    DIGITIZED_MAX_MMPS,
    OUT,
    UMAX_MPS,
    VELOCITY_SCALE,
    canonical_json_bytes,
    sample_coordinates,
    sha256_json,
)


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


class CorrectedVelocityTests(unittest.TestCase):
    def test_fixed_digitized_max_maps_exactly_to_benchmark(self):
        data = read("corrected_velocity_profile.json")
        self.assertEqual(data["fixed_scale_mps_per_mmps"], VELOCITY_SCALE)
        self.assertEqual(data["ratio_before_to_corrected"], 0.48 / 1.365)
        self.assertTrue(data["nominal_max_mapping_exact"])
        self.assertAlmostEqual(data["nominal_profile_max_abs_mps"], UMAX_MPS, places=14)
        self.assertEqual(data["formula"], "U(s) = 0.48 * U_digitized(s) / 1365")

    def test_slice_centers_are_bounded_and_have_reynolds_fields(self):
        data = read("corrected_seven_nine_slice_candidates.json")
        for item in data["candidates"].values():
            self.assertIn("slices", item)
            for slice_item in item["slices"]:
                self.assertLessEqual(abs(slice_item["U_global_mps"]), UMAX_MPS + 1e-15)
                self.assertGreater(slice_item["slice_length_m"], 0.0)
                self.assertIn("s_over_L", slice_item)
                self.assertIn("s_ref_m", slice_item)
                self.assertIn("flow_sign", slice_item)
                self.assertIn("active", slice_item)
                self.assertAlmostEqual(slice_item["local_Reynolds"], abs(slice_item["U_global_mps"]) * 0.02841 / 1e-6)

    def test_candidate_counts_and_single_length_audit(self):
        data = read("corrected_seven_nine_slice_candidates.json")
        self.assertEqual(len(data["candidates"]["uniform_7_point_sampling"]["slices"]), 7)
        self.assertEqual(len(data["candidates"]["uniform_9_point_sampling"]["slices"]), 9)
        for item in data["candidates"].values():
            self.assertTrue(item["delta_s_applied_once"])
            self.assertTrue(item["geometry_audit"]["strictly_increasing"])
            self.assertTrue(item["geometry_audit"]["no_gaps"])
            self.assertTrue(item["geometry_audit"]["no_overlap"])
            self.assertTrue(item["geometry_audit"]["covers_full_riser"])
            self.assertTrue(item["geometry_audit"]["total_length_equals_L"])
            self.assertTrue(all(item["slice_lengths_m"]))


class CorrectedUncertaintyTests(unittest.TestCase):
    def test_fixed_seed_and_no_sample_self_normalization(self):
        data = read("corrected_profile_uncertainty.json")
        self.assertEqual(data["seed"], 20260812)
        self.assertEqual(data["sample_count"], 1000)
        self.assertFalse(data["fixed_normalization"]["sample_self_normalization"])
        self.assertAlmostEqual(data["velocity_perturbation_physical_mps"][1], 25.0 / 1365.0 * 0.48)
        self.assertTrue(data["fixed_candidate_boundaries"])

    def test_perturbed_coordinates_are_strict_and_used_directly(self):
        data = read("corrected_profile_uncertainty.json")
        policy = data["depth_coordinate_policy"]
        self.assertTrue(policy["endpoints_fixed"])
        self.assertTrue(policy["strictly_increasing_required"])
        self.assertFalse(policy["duplicate_coordinates_allowed"])
        self.assertFalse(policy["maximum_accumulate_used"])
        coordinates = np.asarray(data["first_sample_preview"]["perturbed_depth_fraction"])
        self.assertEqual(coordinates[0], 0.0)
        self.assertEqual(coordinates[-1], 1.0)
        self.assertTrue(np.all(np.diff(coordinates) > 0.0))
        self.assertEqual(len(data["per_method"]["linear"]), 4)
        self.assertEqual(len(data["per_method"]["pchip"]), 4)

    def test_fixed_seed_coordinate_sampler_is_reproducible(self):
        a, rejected_a, attempts_a = sample_coordinates(np.random.default_rng(20260812))
        b, rejected_b, attempts_b = sample_coordinates(np.random.default_rng(20260812))
        np.testing.assert_array_equal(a, b)
        self.assertEqual(rejected_a, rejected_b)
        self.assertEqual(attempts_a, attempts_b)

    def test_a_9_slice_scheme_satisfies_both_interpolation_thresholds(self):
        data = read("corrected_profile_uncertainty.json")
        for method in ("linear", "pchip"):
            item = data["per_method"][method]["zero_crossing_aware_9_point_sampling"]
            self.assertTrue(item["robust_pass"])
            self.assertLessEqual(item["global_integral_error_aggregate"]["p95"], 0.05)
            self.assertLessEqual(item["modal_error_aggregate"]["p95"], 0.10)
            self.assertEqual(item["slice_center_direction_changes"], 0)


class FormalHAndProtocolTests(unittest.TestCase):
    def test_final_seven_and_nine_use_formal_h_with_holdout_alignment(self):
        data = read("final_candidate_formal_H_projection.json")
        self.assertEqual(data["alignment_grid"]["point_count"], 401)
        self.assertFalse(data["alignment_grid"]["candidate_centers_used_for_alignment"])
        self.assertEqual(data["formal_mapping_call"]["function"], "src.coupling.multi_slice_mapping.mapping.build_H_for_manifest")
        self.assertEqual(data["formal_mapping_call"]["internal_function"], "ancf_hermite_H")
        for name, expected_count in (("zero_crossing_aware_7_point_sampling", 7), ("zero_crossing_aware_9_point_sampling", 9)):
            self.assertEqual(data["candidates"][name]["slice_count"], expected_count)
            self.assertTrue(data["candidates"][name]["all_targets_pass"])
            for target in data["candidates"][name]["targets"].values():
                self.assertLessEqual(target["target_frequency_max_relative_difference"], 0.02)
                self.assertGreaterEqual(target["dense_grid_subspace"]["subspace_MAC_min"], 0.95)
                self.assertLessEqual(target["candidate_center_max_shape_scaled_relative_error"], 0.01)

    def test_h_dimensions_and_basis_checks(self):
        data = read("final_candidate_formal_H_projection.json")
        self.assertEqual(data["qmode_dimensions"]["8"], [54, 12])
        self.assertEqual(data["qmode_dimensions"]["16"], [102, 12])
        self.assertLess(data["basis_tests"]["rigid_translation_max_error_m"], 1e-12)
        self.assertLess(data["basis_tests"]["linear_axis_z_max_error_m"], 1e-12)
        self.assertTrue(data["basis_tests"]["slope_columns_nonzero"])

    def test_official_protocol_rejects_route_g_fields_and_recomputes_hashes(self):
        data = read("official_0_2_1_compatibility.json")
        self.assertEqual(data["protocol_version"], "0.2.1")
        self.assertTrue(data["manifest_roundtrip_parse"])
        self.assertTrue(data["runtime_roundtrip_parse"])
        self.assertTrue(data["manifest_hash_recomputed"])
        self.assertTrue(data["config_hash_recomputed"])
        self.assertFalse(data["route_G_fields_injected"])
        self.assertTrue(data["route_G_extra_field_tests"]["manifest_route_G_extra_field_rejected"])
        self.assertTrue(data["route_G_extra_field_tests"]["runtime_route_G_extra_field_rejected"])
        self.assertEqual(set(data["manifest_fields"]), {"schema_version", "case_id", "reference_length_m", "represented_length_m", "R_GL", "slices", "slice_manifest_sha256"})
        self.assertEqual(set(data["runtime_config_fields"]), {"schema_version", "case_id", "dt_s", "timeout_s", "start_time_s", "coupling_iteration", "coupling_scheme", "slice_manifest_sha256", "config_sha256"})
        SliceManifest.from_mapping(data["formal_manifest"])
        RuntimeConfig.from_mapping(data["formal_runtime_config"])


class RouteGAndEncodingTests(unittest.TestCase):
    def test_flow_profile_hash_and_restart_mutations(self):
        flow = read("route_G_flow_profile_candidate.json")
        content = {key: flow[key] for key in ("schema_version", "case_id", "protocol_version", "slice_manifest_sha256", "source_profile_sha256", "benchmark_Umax_mps", "diameter_m", "kinematic_viscosity_m2ps", "slices")}
        self.assertEqual(flow["flow_profile_sha256"], sha256_json(content))
        self.assertNotIn("config_sha256", flow)
        self.assertEqual(flow["route_G_status"], "provisional_pending_reverse_flow_smoke")
        binding = read("route_G_checkpoint_binding_candidate.json")
        self.assertIn("slice_id_change", binding["mutation_checks"])
        for check in binding["mutation_checks"].values():
            self.assertTrue(check["changed_identity"])
            self.assertTrue(check["restart_rejected"])

    def test_route_l_is_not_frozen_and_json_is_utf8(self):
        route_l = read("route_L_0_2_2_candidate.json")
        self.assertEqual(route_l["candidate_schema_version"], "0.2.2-candidate")
        self.assertFalse(route_l["protocol_upgrade"] == "performed")
        raw = (OUT / "stage4e_a_v3_2_1_final_candidate_summary.json").read_text(encoding="utf-8")
        self.assertIn("建议通过", raw)
        json.loads(raw)


if __name__ == "__main__":
    unittest.main()
