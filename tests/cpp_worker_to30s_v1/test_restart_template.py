from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.cpp_worker_to30s_v1.restart_template import prepare_fresh_case


class RestartTemplateTests(unittest.TestCase):
    def test_only_fresh_copy_is_cleaned_and_clock_is_bound_to_six_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); destination = root / "runtime" / "slice_0000"
            (destination / "coupling" / "consumed").mkdir(parents=True)
            (destination / "coupling" / "motion_consumed_1.json").write_text("old", encoding="utf-8")
            (destination / "0").mkdir(); (destination / "5.95").mkdir(); (destination / "6").mkdir()
            (destination / "system").mkdir(); (destination / "constant").mkdir()
            (destination / "system" / "controlDict").write_text("startFrom latestTime;\nstartTime 3.3075;\n", encoding="utf-8")
            (destination / "constant" / "dynamicMeshDict").write_text("    startTime 3.3075;\n", encoding="utf-8")
            (destination / "multi_slice_case_config.json").write_text(json.dumps({"start_time_s": 3.3075}), encoding="utf-8")
            prepare_fresh_case(destination=destination, expected_destination=destination, slice_id=0,
                               run_id="new", case_id="case", stage_id="stage")
            self.assertFalse((destination / "coupling").exists())
            self.assertFalse((destination / "5.95").exists())
            self.assertTrue((destination / "6").is_dir())
            self.assertIn("startTime       6;", (destination / "system" / "controlDict").read_text(encoding="utf-8"))
            self.assertIn("startTime 6;", (destination / "constant" / "dynamicMeshDict").read_text(encoding="utf-8"))
            config = json.loads((destination / "multi_slice_case_config.json").read_text(encoding="utf-8"))
            self.assertEqual((config["run_id"], config["case_id"], config["start_time_s"]), ("new", "case_slice_0000", 6.0))

    def test_missing_source_field_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); destination = root / "runtime" / "slice_0000"
            (destination / "coupling").mkdir(parents=True); (destination / "system").mkdir(); (destination / "constant").mkdir()
            (destination / "system" / "controlDict").write_text("startFrom latestTime;\nstartTime 3.3075;\n", encoding="utf-8")
            (destination / "constant" / "dynamicMeshDict").write_text("startTime 3.3075;\n", encoding="utf-8")
            (destination / "multi_slice_case_config.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                prepare_fresh_case(destination=destination, expected_destination=destination, slice_id=0,
                                   run_id="new", case_id="case", stage_id="stage")

    def test_repaired_attempt_is_new_identity_and_has_no_import_side_effect(self) -> None:
        from tools.cpp_worker_to30s_v1 import run_authorized_to30s_002 as attempt
        self.assertEqual((attempt.RUN_ID, attempt.CASE_ID), ("cpp_worker_to30s_002", "cpp_worker_to30s_case_002"))
        self.assertEqual((attempt.SOURCE_STEP, attempt.SOURCE_TIME_S, attempt.SOURCE_TICK), (3593, 6.0, 6_000_000_000))
        self.assertEqual(attempt.RUNTIME.name, "to30s_002")
        self.assertEqual(attempt.RESULTS.name, "216_cpp_worker_to30s_v1_retry1")


if __name__ == "__main__":
    unittest.main()
