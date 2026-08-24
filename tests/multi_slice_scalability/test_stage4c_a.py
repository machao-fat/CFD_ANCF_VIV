from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.multi_slice_campaign import (
    CampaignDefinition,
    SyntheticLoadModel,
    build_candidate_definition,
    load_candidate_pair,
    map_spatial_loads,
    run_failure_injection_matrix,
    run_mock_campaign,
    run_restart_comparison,
    serialize_candidate_pair,
    validate_slice_coverage,
)
from src.coupling.multi_slice_mapping.mapping import (
    IDENTITY_R_GL,
    MappingError,
    SCHEMA_VERSION,
    SliceDefinition,
    SliceManifest,
    build_H_for_manifest,
    map_integrated_slice_forces,
    sha256_file,
)


class Stage4CScalabilityTests(unittest.TestCase):
    def test_three_slice_manifest_is_formal_and_legal(self):
        definition = build_candidate_definition(3)
        manifest = definition.manifest()
        self.assertEqual(manifest.schema_version, "0.2.1")
        self.assertEqual([item.slice_id for item in manifest.slices], [0, 1, 2])
        self.assertEqual([item.s_ref_m for item in manifest.slices], [1.25, 5.0, 8.75])

    def test_five_slice_manifest_is_formal_and_legal(self):
        definition = build_candidate_definition(5)
        manifest = definition.manifest()
        self.assertEqual(manifest.schema_version, "0.2.1")
        self.assertEqual([item.slice_id for item in manifest.slices], list(range(5)))
        self.assertEqual([item.slice_length_m for item in manifest.slices], [1.0, 2.0, 3.0, 2.5, 1.5])

    def test_candidate_serialization_and_hashes_round_trip(self):
        with tempfile.TemporaryDirectory() as raw:
            summary = serialize_candidate_pair(build_candidate_definition(3), Path(raw))
            manifest, config = load_candidate_pair(summary["manifest_path"], summary["config_path"])
            self.assertTrue(summary["stored_and_recomputed_match"]["manifest"])
            self.assertTrue(summary["stored_and_recomputed_match"]["config"])
            self.assertEqual(manifest.slice_manifest_sha256, summary["slice_manifest_sha256"])
            self.assertEqual(config.config_sha256, summary["config_sha256"])

    def test_total_lengths_and_contiguous_coverage(self):
        for number in (3, 5):
            audit = build_candidate_definition(number).geometry_audit()
            self.assertEqual(audit["sum_slice_length_m"], 10.0)
            self.assertTrue(audit["contiguous"])
            self.assertFalse(audit["overlap"])
            self.assertFalse(audit["gap"])

    def test_overlap_is_rejected_by_campaign_geometry_audit(self):
        manifest = SliceManifest(
            SCHEMA_VERSION,
            "overlap",
            2.5,
            3.0,
            (SliceDefinition(0, 1.0, 2.0, 1.0), SliceDefinition(1, 2.0, 1.0, 1.0)),
            IDENTITY_R_GL,
        )
        with self.assertRaises(ValueError):
            validate_slice_coverage(manifest)

    def test_gap_is_rejected_by_campaign_geometry_audit(self):
        manifest = SliceManifest(
            SCHEMA_VERSION,
            "gap",
            2.1,
            2.0,
            (SliceDefinition(0, 0.5, 1.0, 1.0), SliceDefinition(1, 1.6, 1.0, 1.0)),
            IDENTITY_R_GL,
        )
        with self.assertRaises(ValueError):
            validate_slice_coverage(manifest)

    def test_duplicate_slice_id_is_rejected(self):
        raw = build_candidate_definition(3).manifest().to_dict()
        raw["slices"][1]["slice_id"] = 0
        with self.assertRaises(Exception):
            SliceManifest.from_mapping(raw)

    def test_input_permutation_preserves_physical_mapping(self):
        result = map_spatial_loads(build_candidate_definition(5), profile="non_monotonic")
        self.assertTrue(result["permutation_invariant"])
        self.assertEqual(result["generalized_force"], result["shuffled_generalized_force"])

    def test_three_slice_uniform_force_conversion(self):
        result = map_spatial_loads(build_candidate_definition(3), profile="uniform")
        self.assertEqual(result["unit_forces_2d_Npm"]["0"], [2.0, -1.0, 0.5])
        self.assertEqual(result["integrated_slice_forces_N"]["1"], [10.0, -5.0, 2.5])
        self.assertTrue(result["delta_s_audit"]["integrated_force_equals_unit_force_times_slice_length_once"])

    def test_three_slice_linear_force_has_analytic_totals(self):
        result = map_spatial_loads(build_candidate_definition(3), profile="linear")
        expected_x = sum((1.2 + 0.35 * s) * length for s, length in ((1.25, 2.5), (5.0, 5.0), (8.75, 2.5)))
        expected_y = sum((-0.8 + 0.22 * s) * length for s, length in ((1.25, 2.5), (5.0, 5.0), (8.75, 2.5)))
        self.assertAlmostEqual(result["global_total_integrated_force_N"][0], expected_x)
        self.assertAlmostEqual(result["global_total_integrated_force_N"][1], expected_y)
        self.assertNotEqual(result["unit_forces_2d_Npm"]["0"], result["unit_forces_2d_Npm"]["2"])

    def test_five_slice_nonmonotonic_forces_are_not_copied(self):
        result = map_spatial_loads(build_candidate_definition(5), profile="non_monotonic")
        unit = list(result["unit_forces_2d_Npm"].values())
        integrated = list(result["integrated_slice_forces_N"].values())
        self.assertGreater(len({tuple(row) for row in unit}), 1)
        self.assertGreater(len({tuple(row) for row in integrated}), 1)
        self.assertNotEqual(result["generalized_force"], map_spatial_loads(build_candidate_definition(5), profile="uniform")["generalized_force"])

    def test_delta_s_is_applied_once_for_both_candidates(self):
        for number in (3, 5):
            for profile in ("uniform", "linear", "non_monotonic"):
                result = map_spatial_loads(build_candidate_definition(number), profile=profile)
                self.assertTrue(result["delta_s_audit"]["integrated_force_equals_unit_force_times_slice_length_once"])
                self.assertTrue(result["delta_s_audit"]["mapping_applies_no_slice_length_factor"])

    def test_three_slice_virtual_work(self):
        result = map_spatial_loads(build_candidate_definition(3), profile="linear")
        self.assertLessEqual(result["virtual_work"]["error_rel"], 1.0e-12)
        self.assertLessEqual(result["virtual_work"]["error_abs_J"], 1.0e-12)

    def test_five_slice_virtual_work(self):
        result = map_spatial_loads(build_candidate_definition(5), profile="non_monotonic")
        self.assertLessEqual(result["virtual_work"]["error_rel"], 1.0e-12)
        self.assertLessEqual(result["virtual_work"]["error_abs_J"], 1.0e-12)

    def test_non_node_matching_H_interpolation(self):
        definition = build_candidate_definition(5)
        H = build_H_for_manifest(definition.manifest(), (0.0, 3.0, 6.5, 10.0))
        self.assertEqual(set(H), set(range(5)))
        self.assertTrue(any(0.0 < value < 1.0 for row in H[0] for value in row))
        self.assertEqual(len([item.s_ref_m for item in definition.specs if item.s_ref_m not in (0.0, 3.0, 6.5, 10.0)]), 5)

    def test_three_slice_ten_step_time_barrier_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as raw:
            result = run_mock_campaign(build_candidate_definition(3), Path(raw), steps=10)
            self.assertTrue(result["time_barrier_pass"])
            self.assertEqual(result["completed_steps"], 10)
            self.assertEqual(result["files"]["motion_csv"], 30)
            self.assertEqual(result["files"]["load_csv"], 30)
            self.assertEqual(result["files"]["committed_manifest_count"], 10)

    def test_five_slice_ten_step_time_barrier_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as raw:
            result = run_mock_campaign(build_candidate_definition(5), Path(raw), steps=10)
            self.assertTrue(result["time_barrier_pass"])
            self.assertEqual(result["completed_steps"], 10)
            self.assertEqual(result["files"]["motion_csv"], 50)
            self.assertEqual(result["files"]["load_csv"], 50)
            self.assertEqual(result["files"]["committed_manifest_count"], 10)

    def test_three_slice_restart_matches_continuous(self):
        with tempfile.TemporaryDirectory() as raw:
            result = run_restart_comparison(build_candidate_definition(3), Path(raw))
            self.assertTrue(result["bitwise_selected_state_equal"])
            self.assertEqual(result["selected_manifest_max_abs_error"], 0.0)
            self.assertTrue(result["manifest_hash_equal"])
            self.assertTrue(result["config_hash_equal"])

    def test_five_slice_restart_matches_continuous(self):
        with tempfile.TemporaryDirectory() as raw:
            result = run_restart_comparison(build_candidate_definition(5), Path(raw))
            self.assertTrue(result["bitwise_selected_state_equal"])
            self.assertEqual(result["selected_manifest_max_abs_error"], 0.0)
            self.assertEqual(result["continuous_final_step"], 9)
            self.assertEqual(result["segmented_final_step"], 9)

    def test_failure_matrix_covers_all_required_classes_and_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            result = run_failure_injection_matrix(build_candidate_definition(3), Path(raw))
            self.assertEqual(result["case_count"], 29)
            self.assertTrue(result["all_fail_closed"])
            self.assertTrue(result["all_precommit_no_committed_manifest"])
            self.assertFalse(result["structure_advanced_on_failure"])
            self.assertTrue(result["post_commit_recovery_required"])
            self.assertTrue(result["restart_order_identity_preserved"])

    def test_five_slice_failure_matrix_is_also_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            result = run_failure_injection_matrix(build_candidate_definition(5), Path(raw))
            self.assertTrue(result["all_fail_closed"])
            self.assertTrue(result["all_precommit_no_committed_manifest"])
            self.assertFalse(result["structure_advanced_on_failure"])
            self.assertTrue(result["post_commit_recovery_required"])

    def test_missing_slice_transaction_is_rejected(self):
        definition = build_candidate_definition(3)
        manifest = definition.manifest()
        H = build_H_for_manifest(manifest, (0.0, 3.0, 6.5, 10.0))
        with self.assertRaises(MappingError):
            map_integrated_slice_forces(manifest, {0: H[0], 1: H[1], 2: H[2]}, {0: (1.0, 0.0, 0.0), 1: (1.0, 0.0, 0.0)})

    def test_checkpoint_hash_audit_is_recomputed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = run_mock_campaign(build_candidate_definition(3), root, steps=1)
            checkpoint = json.loads(Path(result["step_results"][0]["checkpoint_path"]).read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["status"], "committed")
            for entry in checkpoint["slices"]:
                for file_entry in entry["static_files"] + entry["time_files"]:
                    actual = root / "cases" / entry["case_relative_path"] / file_entry["relative_path"]
                    self.assertEqual(file_entry["sha256"], sha256_file(actual))

    def test_gate4a_evidence_is_read_only_and_unchanged_in_scope(self):
        project = Path(__file__).resolve().parents[2]
        evidence = json.loads((project / "results" / "05_multi_slice_integration_tests_v3" / "stage4_gate4a_sol_acceptance.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["schema_version"], "0.2.1")
        self.assertEqual(evidence["tests"]["failed"], 0)
        self.assertFalse(evidence["physical_viv_validation_completed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
