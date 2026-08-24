from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4e_b1_v3_1_2_closeout.offline import (
    EXPECTED_PAYLOAD_SHA256,
    revalidate_existing_probe,
    validate_exact_release,
    validate_payload,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PAYLOAD = PROJECT_ROOT / "results" / "09_stage4e_b1_v3_1_1_closeout" / "probe_payload.json"
SOURCE_RESULT = PROJECT_ROOT / "results" / "09_stage4e_b1_v3_1_1_closeout" / "matlab_version_license_probe.json"


class OfflineProbeRevalidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(SOURCE_PAYLOAD.read_text(encoding="utf-8"))
        cls.source_result = json.loads(SOURCE_RESULT.read_text(encoding="utf-8"))

    def test_frozen_source_hash_is_exact(self) -> None:
        digest = hashlib.sha256(SOURCE_PAYLOAD.read_bytes()).hexdigest()
        self.assertEqual(digest, EXPECTED_PAYLOAD_SHA256)

    def test_exact_release_value_is_accepted(self) -> None:
        self.assertTrue(validate_exact_release("2021b"))

    def test_display_release_and_nearby_values_are_rejected(self) -> None:
        for value in ("R2021b", "2021a", "2022a", "2021b ", "", None):
            with self.subTest(value=value):
                self.assertFalse(validate_exact_release(value))

    def test_corrected_field_is_release_2021b(self) -> None:
        validation = validate_payload(self.payload, self.source_result, SOURCE_PAYLOAD)
        self.assertTrue(validation["checks"]["release_2021b"])
        self.assertNotIn("release_R2021b", validation["checks"])
        self.assertTrue(validation["all_checks_passed"])

    def test_version_series_is_not_a_loose_prefix(self) -> None:
        for version in ("9.9.0", "9.12.0", "2021b"):
            payload = copy.deepcopy(self.payload)
            payload["version"] = version
            validation = validate_payload(payload, self.source_result, SOURCE_PAYLOAD)
            self.assertFalse(validation["checks"]["version_9_11_series"])

    def test_return_code_and_identity_are_checked(self) -> None:
        result = copy.deepcopy(self.source_result)
        result["return_code"] = 1
        validation = validate_payload(self.payload, result, SOURCE_PAYLOAD)
        self.assertFalse(validation["checks"]["launcher_return_code_zero"])
        result["return_code"] = 0
        result["run_token"] = "other"
        validation = validate_payload(self.payload, result, SOURCE_PAYLOAD)
        self.assertFalse(validation["checks"]["run_token"])

    def test_source_payload_is_not_modified_by_revalidation(self) -> None:
        before = SOURCE_PAYLOAD.read_bytes()
        with tempfile.TemporaryDirectory(dir=str(PROJECT_ROOT / "runtime")) as temp_dir:
            result = revalidate_existing_probe(PROJECT_ROOT, Path(temp_dir))
            self.assertEqual(result["matlab_probe_rerun_count"], 0)
            self.assertFalse(result["matlab_probe_rerun_performed"])
            self.assertTrue(result["original_payload_unchanged"])
        self.assertEqual(SOURCE_PAYLOAD.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
