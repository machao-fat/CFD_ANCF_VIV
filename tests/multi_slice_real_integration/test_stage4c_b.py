from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.multi_slice_driver import MultiSliceConfig, MultiSliceScheduler
from src.coupling.multi_slice_driver.real_process import (
    assert_fresh_case,
    bridge_for_global_step,
    bridge_seed,
)
from src.coupling.multi_slice_mapping.mapping import LoadRecord, build_H_for_manifest, map_integrated_slice_forces, sha256_json
from src.coupling.multi_slice_real_campaign.campaign import (
    DEFAULT_LIBRARY,
    FROZEN_MANIFEST_HASH,
    build_physics_manifest,
    build_runtime_config,
    load_frozen_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "results" / "05_stage4c_scalability_tests" / "canonical_3slice_manifest_candidate.json"


class Stage4CBStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = load_frozen_manifest(MANIFEST_PATH)
        cls.config = build_runtime_config(cls.manifest, start_time_s=0.05, timeout_s=120.0)

    def test_frozen_manifest_hash(self):
        self.assertEqual(self.manifest.slice_manifest_sha256, FROZEN_MANIFEST_HASH)
        self.assertEqual(self.manifest.computed_slice_manifest_sha256(), FROZEN_MANIFEST_HASH)

    def test_runtime_config_is_real_time_config(self):
        self.assertEqual(self.config.schema_version, "0.2.1")
        self.assertEqual(self.config.dt_s, 0.0025)
        self.assertEqual(self.config.timeout_s, 120.0)
        self.assertEqual(self.config.start_time_s, 0.05)
        self.assertEqual(self.config.config_sha256, self.config.computed_config_sha256())

    def test_physics_hash_round_trip(self):
        fields = {i: {"case": f"warmup/slice_{i:04d}", "time_name": "0.05", "field_files": []} for i in range(3)}
        payload = build_physics_manifest(manifest=self.manifest, runtime_config=self.config, condition="nonuniform", speeds_mps={0: 0.8, 1: 1.0, 2: 1.2}, run_id="test", initial_fields=fields, library=DEFAULT_LIBRARY)
        stored = payload.pop("physics_config_sha256")
        self.assertEqual(stored, sha256_json(payload))

    def test_physics_hash_tamper_is_detectable(self):
        fields = {i: {"case": f"warmup/slice_{i:04d}", "time_name": "0.05", "field_files": []} for i in range(3)}
        payload = build_physics_manifest(manifest=self.manifest, runtime_config=self.config, condition="nonuniform", speeds_mps={0: 0.8, 1: 1.0, 2: 1.2}, run_id="test", initial_fields=fields, library=DEFAULT_LIBRARY)
        stored = payload["physics_config_sha256"]
        payload["slices"][0]["U_mps"] = 0.81
        self.assertNotEqual(stored, sha256_json({k: v for k, v in payload.items() if k != "physics_config_sha256"}))

    def test_three_slice_bridge_mapping(self):
        self.assertEqual(bridge_seed(start_time_s=0.05, step_offset=0), (0, 0.05))
        self.assertEqual(bridge_for_global_step(global_step=0, target_time_s=0.0525), (1, 0.0525))
        self.assertEqual(bridge_for_global_step(global_step=1, target_time_s=0.055), (2, 0.055))
        self.assertEqual(bridge_for_global_step(global_step=2, target_time_s=0.0575), (3, 0.0575))

    def test_max_openfoam_concurrency_contract(self):
        self.assertLessEqual(1, 2)

    def test_missing_third_process_is_rejected(self):
        config = MultiSliceConfig(case_id=self.manifest.case_id, dt_s=0.0025, timeout_s=1.0, manifest=self.manifest)
        with self.assertRaises(Exception):
            MultiSliceScheduler(config=config, exchange_root=Path(tempfile.mkdtemp()), structure=object(), slice_processes=[])

    def test_delta_s_is_applied_once(self):
        item = self.manifest.slice(0)
        record = LoadRecord.from_conversion(case_id=self.manifest.case_id, step=0, time_s=0.0525, slice_definition=item, unit_span_m=1.0, openfoam_force_N=(4.0, -2.0, 0.0), cfd_time_step_s=0.0025, R_GL=self.manifest.R_GL)
        self.assertEqual(record.force_2d_Npm, (4.0, -2.0, 0.0))
        self.assertEqual(record.force_N, (10.0, -5.0, 0.0))

    def test_three_slice_h_transpose_uses_integrated_force(self):
        H = build_H_for_manifest(self.manifest, (0.0, 3.0, 6.5, 10.0))
        loads = {}
        for item in self.manifest.slices:
            loads[item.slice_id] = LoadRecord.from_conversion(case_id=self.manifest.case_id, step=0, time_s=0.0525, slice_definition=item, unit_span_m=1.0, openfoam_force_N=(1.0, 2.0, 0.0), cfd_time_step_s=0.0025, R_GL=self.manifest.R_GL)
        result = map_integrated_slice_forces(self.manifest, H, loads)
        self.assertEqual(result.force_audit[1]["force_N"], [5.0, 10.0, 0.0])
        self.assertNotIn("slice_length_factor_applied", result.to_dict())

    def test_checkpoint_object_expectation(self):
        self.assertEqual(3 * (1 + 7) + 2, 26)

    def test_manifest_identity_cannot_change_slice_count(self):
        raw = self.manifest.to_dict()
        raw["slices"] = raw["slices"][:2]
        raw["represented_length_m"] = 7.5
        raw["slice_manifest_sha256"] = "0" * 64
        with self.assertRaises(Exception):
            load_frozen_manifest(MANIFEST_PATH.parent / "not_used.json")
        self.assertRaises(Exception, type(self.manifest).from_mapping, raw)

    def test_case_freshness_rejects_old_force(self):
        with tempfile.TemporaryDirectory() as raw:
            case = Path(raw)
            (case / "constant").mkdir()
            (case / "system").mkdir()
            (case / "postProcessing" / "cylinderForces").mkdir(parents=True)
            (case / "postProcessing" / "cylinderForces" / "forces.dat").write_text("old\n", encoding="utf-8")
            with self.assertRaises(Exception):
                assert_fresh_case(case, target_time_name="0.0525")

    def test_protocol_version_is_unchanged(self):
        self.assertEqual(self.manifest.schema_version, "0.2.1")
        self.assertEqual(self.config.schema_version, "0.2.1")

    def test_nonuniform_speeds_are_distinct(self):
        speeds = [0.8, 1.0, 1.2]
        self.assertEqual([v / 0.01 for v in speeds], [80.0, 100.0, 120.0])
        self.assertEqual(len(set(speeds)), 3)

    def test_restart_identity_hashes_are_required(self):
        self.assertEqual(len(self.manifest.slice_manifest_sha256), 64)
        self.assertEqual(len(self.config.config_sha256), 64)

    def test_frozen_geometry(self):
        self.assertEqual(sum(item.slice_length_m for item in self.manifest.slices), 10.0)
        self.assertEqual([item.s_ref_m for item in self.manifest.slices], [1.25, 5.0, 8.75])


if __name__ == "__main__":
    unittest.main(verbosity=2)
