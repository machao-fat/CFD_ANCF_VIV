import json
import math
import re
import unittest
from pathlib import Path

import src.coupling.stage4f_lowre_benchmark_design_v2 as stage4f_v2


ROOT = Path(__file__).resolve().parents[2]
RESULT = ROOT / "results" / "11_stage4f_lowre_benchmark_design_v2"


class HygieneTests(unittest.TestCase):
    def test_package_is_discoverable_from_root(self):
        self.assertTrue(hasattr(stage4f_v2, "LowReContract"))

    def test_no_high_re_profile_read_and_no_openfoam_launch(self):
        for label in ("three", "five", "nine"):
            document = json.loads((RESULT / f"{label}_slice_mapping.json").read_text(encoding="utf-8"))
            if document["status"] == "not_run_due_stop_condition_8":
                self.assertFalse(document["formal_mapping_called"])
                continue
            for mesh in document["mesh_results"].values():
                self.assertFalse(mesh["high_re_profile_read"])
                self.assertFalse(mesh["openfoam_started"])
        matlab = json.loads((RESULT / "matlab_execution_audit.json").read_text(encoding="utf-8"))
        self.assertFalse(matlab["openfoam_started"])

    def test_all_json_is_parseable_and_finite(self):
        for path in RESULT.glob("*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"(?<![A-Za-z])(?:NaN|Infinity)(?![A-Za-z])", text), path.name)
            value = json.loads(text)
            self.assertTrue(self._finite(value), path.name)

    def test_v1_and_protected_hashes_unchanged(self):
        audit = json.loads((RESULT / "stage4f_v1_stop_evidence_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["status"], "passed")
        self.assertEqual(audit["mismatches"], [])
        self.assertFalse(audit["v1_files_modified"])

    def test_matlab_process_cleanup_and_runtime(self):
        process = json.loads((RESULT / "process_cleanup_audit.json").read_text(encoding="utf-8"))
        runtime = json.loads((RESULT / "runtime_path_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(process["owned_residual"], 0)
        self.assertFalse(process["cleanup_by_process_name"])
        self.assertTrue(runtime["runtime_on_D_drive"])
        self.assertEqual(runtime["C_drive_project_artifact_count"], 0)

    @classmethod
    def _finite(cls, value):
        if isinstance(value, float):
            return math.isfinite(value)
        if isinstance(value, dict):
            return all(cls._finite(item) for item in value.values())
        if isinstance(value, list):
            return all(cls._finite(item) for item in value)
        return True


if __name__ == "__main__":
    unittest.main()
