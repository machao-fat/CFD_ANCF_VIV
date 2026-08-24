import copy
import json
import unittest
from pathlib import Path

from src.coupling.multi_slice_mapping.mapping import RuntimeConfig, SliceManifest
from src.coupling.stage4e_physical_baseline_v3_2_2.materialize_final_nine_identity import (
    FINAL_CASE_ID,
    SELECTED_CANDIDATE,
    OUT,
    assert_final_nine_identity,
    canonical_json_bytes,
    sha256_json,
)


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


class FinalNineMaterializationTests(unittest.TestCase):
    def test_selected_candidate_and_all_slice_counts_are_nine(self):
        summary = read("stage4e_a_v3_2_2_final_candidate_summary.json")
        identity = read("final_candidate_identity.json")
        flow = read("route_G_flow_profile_candidate.json")
        checkpoint = read("route_G_checkpoint_binding_candidate.json")
        compatibility = read("official_0_2_1_compatibility.json")
        self.assertEqual(summary["v3_2_2_implemented"], "yes")
        self.assertEqual(summary["selected_candidate"], SELECTED_CANDIDATE)
        self.assertEqual(summary["final_manifest_slice_count"], 9)
        self.assertEqual(summary["final_flow_profile_slice_count"], 9)
        self.assertEqual(summary["final_checkpoint_binding_slice_count"], 9)
        self.assertEqual(identity["case_id"], FINAL_CASE_ID)
        self.assertEqual(len(compatibility["formal_manifest"]["slices"]), 9)
        self.assertEqual(len(flow["slices"]), 9)
        self.assertEqual(len(checkpoint["slices"]), 9)
        self.assertEqual(compatibility["formal_manifest"]["case_id"], FINAL_CASE_ID)
        self.assertEqual(compatibility["formal_runtime_config"]["case_id"], FINAL_CASE_ID)

    def test_production_0_2_1_roundtrips_and_hashes(self):
        compatibility = read("official_0_2_1_compatibility.json")
        self.assertTrue(compatibility["manifest_roundtrip_parse"])
        self.assertTrue(compatibility["runtime_roundtrip_parse"])
        self.assertTrue(compatibility["manifest_hash_recomputed"])
        self.assertTrue(compatibility["config_hash_recomputed"])
        self.assertFalse(compatibility["route_G_fields_injected"])
        manifest = SliceManifest.from_mapping(compatibility["formal_manifest"])
        runtime = RuntimeConfig.from_mapping(compatibility["formal_runtime_config"])
        self.assertEqual(len(manifest.slices), 9)
        self.assertEqual(runtime.slice_manifest_sha256, manifest.slice_manifest_sha256)

    def test_h_identity_is_the_existing_nine_slice_result(self):
        h = read("final_candidate_formal_H_projection.json")
        self.assertEqual(h["selected_candidate"], SELECTED_CANDIDATE)
        self.assertEqual(h["slice_count"], 9)
        self.assertTrue(h["all_targets_pass"])
        self.assertFalse(h["h_recomputed"])
        self.assertEqual(h["H_shape_by_nElem"]["8"], [9, 3, 54])
        self.assertEqual(h["H_shape_by_nElem"]["16"], [9, 3, 102])
        self.assertEqual(h["target_mesh_recommendation"], "nElem=8")


class CrossArtifactIdentityTests(unittest.TestCase):
    def test_all_artifacts_bind_the_same_nine_slice_identity(self):
        compatibility = read("official_0_2_1_compatibility.json")
        flow = read("route_G_flow_profile_candidate.json")
        checkpoint = read("route_G_checkpoint_binding_candidate.json")
        h = read("final_candidate_formal_H_projection.json")
        assert_final_nine_identity(compatibility, flow, checkpoint, h)
        identity = read("cross_artifact_identity_audit.json")
        self.assertEqual(identity["cross_artifact_identity"], "passed")
        self.assertTrue(all(identity["checks"].values()))

    def test_seven_slice_artifact_cannot_masquerade_as_final_nine(self):
        compatibility = read("official_0_2_1_compatibility.json")
        flow = read("route_G_flow_profile_candidate.json")
        checkpoint = read("route_G_checkpoint_binding_candidate.json")
        h = read("final_candidate_formal_H_projection.json")
        forged = copy.deepcopy(compatibility)
        forged["formal_manifest"]["slices"] = forged["formal_manifest"]["slices"][:7]
        with self.assertRaises(ValueError):
            assert_final_nine_identity(forged, flow, checkpoint, h)
        forged_flow = copy.deepcopy(flow)
        forged_flow["slices"] = forged_flow["slices"][:7]
        with self.assertRaises(ValueError):
            assert_final_nine_identity(compatibility, forged_flow, checkpoint, h)
        forged_checkpoint = copy.deepcopy(checkpoint)
        forged_checkpoint["slices"] = forged_checkpoint["slices"][:7]
        with self.assertRaises(ValueError):
            assert_final_nine_identity(compatibility, flow, forged_checkpoint, h)

    def test_flow_and_checkpoint_hashes_are_distinct_from_config_hash(self):
        compatibility = read("official_0_2_1_compatibility.json")
        flow = read("route_G_flow_profile_candidate.json")
        checkpoint = read("route_G_checkpoint_binding_candidate.json")
        self.assertNotEqual(flow["flow_profile_sha256"], compatibility["formal_runtime_config"]["config_sha256"])
        self.assertNotEqual(checkpoint["checkpoint_binding_sha256"], compatibility["formal_runtime_config"]["config_sha256"])
        self.assertEqual(checkpoint["flow_profile_sha256"], flow["flow_profile_sha256"])


class IdentityHashTests(unittest.TestCase):
    def test_flow_profile_hash_recomputes_without_absolute_paths(self):
        flow = read("route_G_flow_profile_candidate.json")
        keys = ("schema_version", "case_id", "protocol_version", "selected_candidate", "slice_geometry_sha256", "slice_manifest_sha256", "source_profile_sha256", "benchmark_Umax_mps", "diameter_m", "kinematic_viscosity_m2ps", "slices")
        content = {key: flow[key] for key in keys}
        self.assertEqual(flow["flow_profile_sha256"], sha256_json(content))
        self.assertNotIn("D:\\", canonical_json_bytes(content).decode("utf-8"))
        self.assertTrue(all(flow["flow_profile_hash_mutation_checks"].values()))

    def test_checkpoint_binding_hash_recomputes(self):
        checkpoint = read("route_G_checkpoint_binding_candidate.json")
        content = {key: checkpoint[key] for key in ("schema_version", "case_id", "protocol_version", "selected_candidate", "slice_geometry_sha256", "slice_manifest_sha256", "flow_profile_sha256", "slices", "restart_identity_policy", "production_checkpoint_module_modified")}
        self.assertEqual(checkpoint["checkpoint_binding_sha256"], sha256_json(content))
        self.assertFalse(checkpoint["production_checkpoint_module_modified"])

    def test_utf8_json_and_no_nonfinite_values(self):
        for path in OUT.glob("*.json"):
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            self.assertIsNotNone(payload)
            self.assertNotIn("�", raw)


if __name__ == "__main__":
    unittest.main()
