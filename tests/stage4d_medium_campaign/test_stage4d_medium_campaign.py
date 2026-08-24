from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from pathlib import Path

from src.coupling.process_control.process_limiter import ProcessLimiter
from src.coupling.stage4d_medium_campaign import campaign as c


class Stage4DMediumCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = c.RESULTS_ROOT
        formal_dirs = sorted((p for p in cls.root.iterdir() if p.is_dir() and p.name.startswith("stage4d_b_formal100_")), key=lambda p: p.stat().st_mtime, reverse=True)
        restart_dirs = sorted((p for p in cls.root.iterdir() if p.is_dir() and p.name.startswith("stage4d_b_restart_")), key=lambda p: p.stat().st_mtime, reverse=True)
        cls.formal = formal_dirs[0] if formal_dirs else None
        cls.restart = restart_dirs[0] if restart_dirs else None

    def test_stage4d_a_source_hashes(self):
        audit = c.verify_stage4d_a_inputs()
        self.assertEqual(audit["acceptance"]["schema_version"], "0.2.1")
        self.assertEqual(audit["acceptance"]["slice_manifest_sha256"], c.FROZEN_MANIFEST_HASH)
        self.assertEqual(audit["flows"]["0"]["physical_hash"], "9b010c5d6d71162779ddf7eb4861521ef494de88776ea5f502e9aa0652a9a7e5")
        self.assertEqual(audit["flows"]["1"]["physical_hash"], "2d2fc3edfdbcf12bc461721d3009d90c54801fdd3bd20649bdfc7799f81fd2e5")
        self.assertEqual(audit["flows"]["2"]["physical_hash"], "913e788e29c3ebf1361a4fd422dc8835cbb1b6814f81e51c5c609f9467552136")

    def test_initial_force_applies_length_once(self):
        manifest = c.SliceManifest.from_mapping(c._read_json(c.MANIFEST_PATH))
        values, audit = c._initial_force_records(manifest)
        self.assertAlmostEqual(values[0][0], audit["slices"]["0"]["force_2d_Npm"][0] * 2.5)
        self.assertAlmostEqual(values[1][0], audit["slices"]["1"]["force_2d_Npm"][0] * 5.0)
        self.assertTrue(all(item["length_applied_once"] for item in audit["slices"].values()))

    def test_motion_scale_generation_rule(self):
        self.assertEqual(c._motion_scale_value(0.0, 0.0), 1.0)
        self.assertEqual(c._motion_scale_value(2.5, 0.0), 0.0)
        self.assertTrue(0.0 < c._motion_scale_value(1.5, 0.0) < 1.0)
        self.assertNotEqual(c.OLD_MOTIONSCALE_HASH, "30c7be5c4faa19a5c311e05585d20dcb0fe0af0b5f1292e8600a4cbb0aba046d")

    def test_energy_formula_and_low_work_guard(self):
        data = [{"W_CFD_J": 2.0, "W_structure_J": 1.0, "delta_W_J": 1.0}, {"W_CFD_J": -1.0, "W_structure_J": -0.5, "delta_W_J": -0.5}]
        result = c._energy_summary(data)
        self.assertAlmostEqual(result["E_c"], 0.5 / 3.0)
        self.assertEqual(result["status"], "evaluable")
        low = c._energy_summary([{"W_CFD_J": 0.0, "W_structure_J": 0.0, "delta_W_J": 0.0}])
        self.assertEqual(low["status"], "not_evaluable_low_work")
        self.assertIsNone(low["E_c"])

    def test_process_limiter_three_processes(self):
        limiter = ProcessLimiter(2, run_id="stage4d-b-test-three")
        managed = []
        errors = []

        def launch(sid):
            try:
                item = limiter.launch([sys.executable, "-c", "import time; time.sleep(0.15)"], slice_id=sid, global_step=0, timeout_s=5.0)
                managed.append(item)
                item.wait(timeout=5.0)
            except Exception as exc:  # pragma: no cover - assertion below reports it
                errors.append(exc)

        threads = [threading.Thread(target=launch, args=(sid,)) for sid in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10.0)
        audit = limiter.shutdown(force=True)
        self.assertFalse(errors)
        self.assertEqual(len(managed), 3)
        self.assertEqual(audit["interval_peak_active_count"], 2)
        self.assertFalse(audit["permit_leak"])
        self.assertTrue(all(item["end_time_ns"] >= item["start_time_ns"] for item in audit["records"]))

    def test_process_limiter_max_one_is_enforced(self):
        limiter = ProcessLimiter(1, run_id="stage4d-b-test-one")
        managed = []

        def launch(sid):
            item = limiter.launch([sys.executable, "-c", "import time; time.sleep(0.08)"], slice_id=sid, global_step=0, timeout_s=5.0)
            managed.append(item)
            item.wait(timeout=5.0)

        threads = [threading.Thread(target=launch, args=(sid,)) for sid in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10.0)
        audit = limiter.shutdown(force=True)
        self.assertEqual(len(managed), 2)
        self.assertEqual(audit["interval_peak_active_count"], 1)
        self.assertFalse(audit["permit_leak"])

    def test_process_limiter_timeout_releases_permit(self):
        limiter = ProcessLimiter(1, run_id="stage4d-b-test-timeout")
        item = limiter.launch([sys.executable, "-c", "import time; time.sleep(2)"], slice_id=0, global_step=0, timeout_s=5.0)
        with self.assertRaises(TimeoutError):
            item.wait(timeout=0.05)
        audit = limiter.shutdown(force=True)
        self.assertEqual(audit["active_count"], 0)
        self.assertFalse(audit["permit_leak"])

    def test_process_limiter_failed_process_releases(self):
        limiter = ProcessLimiter(2, run_id="stage4d-b-test-failure")
        item = limiter.launch([sys.executable, "-c", "raise SystemExit(7)"], slice_id=0, global_step=0, timeout_s=5.0)
        self.assertEqual(item.wait(timeout=5.0), 7)
        audit = limiter.shutdown(force=True)
        self.assertFalse(audit["permit_leak"])
        self.assertEqual(audit["records"][0]["exit_code"], 7)

    def test_formal_summary_and_checkpoint_audit(self):
        self.assertIsNotNone(self.formal)
        result = c._read_json(self.formal / "formal100_result.json")
        self.assertEqual(result["summary"]["steps_completed"], 100)
        self.assertEqual(result["summary"]["slice_execution_count"], 300)
        self.assertEqual(result["summary"]["matlab_start_count"], 1)
        self.assertLess(result["summary"]["max_cfl"], 0.8)
        self.assertTrue(result["checkpoint_hash_audit"]["all_valid"])
        self.assertEqual(result["checkpoint_hash_audit"]["checkpoint_count"], 100)
        self.assertEqual(result["checkpoint_hash_audit"]["object_count_total"], 2600)

    def test_restart_identity_audit(self):
        self.assertIsNotNone(self.restart)
        result = c._read_json(self.restart / "restart_result.json")
        self.assertTrue(result["comparisons"]["all_within_thresholds"])
        self.assertTrue(result["comparisons"]["identity"]["all_identity_equal"])
        self.assertEqual(len(result["comparisons"]["rows"]), 10)
        self.assertEqual(result["phase1"]["matlab_start_count"], 1)
        self.assertEqual(result["phase2"]["matlab_start_count"], 1)

    def test_materialization_lineage_is_local_zero_and_fresh(self):
        self.assertIsNotNone(self.formal)
        summary = c._read_json(self.formal / "campaign_summary.json")
        for item in summary["materialization"]["slices"].values():
            lineage = item["lineage"]
            self.assertEqual(lineage["target_time_s"], 0.0)
            self.assertEqual(lineage["source_points_sha256"], c.POINTS_HASH)
            self.assertEqual(lineage["target_points_sha256"], c.POINTS_HASH)
            self.assertFalse(lineage["conversion"].find("setFields") >= 0 and lineage["conversion"].find("no setFields") < 0)
            self.assertEqual(lineage["motionScale"]["point_count"], 10624)


if __name__ == "__main__":
    unittest.main()
