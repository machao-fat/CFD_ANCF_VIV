from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from src.coupling.stage4e_b1_regression_closeout import REQUIRED_CLOSEOUT_ARTIFACTS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT_ROOT / "results" / "09_stage4e_b1_regression_closeout"


class Stage4EB1RegressionCloseoutTests(unittest.TestCase):
    def read(self, name: str):
        return json.loads((RESULTS / name).read_text(encoding="utf-8"))

    def test_required_hygiene_artifacts_exist_and_are_utf8_json(self):
        for name in REQUIRED_CLOSEOUT_ARTIFACTS:
            path = RESULTS / name
            self.assertTrue(path.is_file(), name)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsNotNone(payload)

    def test_owned_processes_are_closed_and_runtime_is_clean(self):
        registry = self.read("owned_process_registry.json")
        after = self.read("process_inventory_after.json")
        self.assertEqual(registry["task_owned_residual_process_count"], 0)
        self.assertEqual(registry["started_count"], registry["closed_count"])
        self.assertEqual(after["task_owned_residual_process_count"], 0)
        self.assertEqual(after["project_runtime_process_count"], 0)

    def test_d_drive_and_c_drive_gates_are_explicit(self):
        paths = self.read("runtime_path_audit.json")
        c_drive = self.read("c_drive_write_diff.json")
        self.assertTrue(paths["all_controlled_paths_on_d_drive"])
        self.assertEqual(paths["c_drive_project_artifacts_created"], 0)
        self.assertEqual(c_drive["task_controlled_c_drive_artifact_count"], 0)

    def test_no_nonfinite_values_in_closeout_json(self):
        def visit(value):
            if isinstance(value, float):
                self.assertTrue(math.isfinite(value))
            elif isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        for path in RESULTS.glob("*.json"):
            visit(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
