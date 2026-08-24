"""Unit coverage for the offline restart-identity comparator."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from .compare import compare_checkpoint_files, compare_checkpoint_payloads


def _payload() -> dict[str, object]:
    digest_a = "a" * 64
    digest_b = "b" * 64
    return {
        "schema_version": "0.2.1",
        "status": "committed",
        "case_id": "unit_case",
        "config_sha256": digest_a,
        "slice_manifest_sha256": digest_b,
        "expected_slice_ids": [0],
        "step": 7,
        "time_s": 1.25,
        "dt_s": 0.125,
        "previous_slice_forces_N": [[1.0, -2.0, 3.0]],
        "structure": {"q": [0.0, 2.0], "qdot": [0.0, 0.5], "qddot": [0.0, -4.0]},
        "slices": [{
            "slice_id": 0,
            "static_files": [{"relative_path": "0/motionScale", "sha256": digest_a}],
            "time_files": [{"relative_path": "1.25/U", "sha256": digest_b}],
        }],
    }


class RestartIdentityComparisonTests(unittest.TestCase):
    def test_identical_payload_passes_all_required_comparisons(self) -> None:
        report = compare_checkpoint_payloads(_payload(), copy.deepcopy(_payload()))
        self.assertTrue(report["passed"])
        self.assertEqual(report["comparisons"]["structure"]["q"]["relative_linf"], 0.0)
        self.assertTrue(report["comparisons"]["cfd_manifest_field_hashes"]["passed"])

    def test_state_force_field_and_time_differences_are_reported(self) -> None:
        candidate = _payload()
        candidate["time_s"] = 1.5
        candidate["previous_slice_forces_N"] = [[1.0, -2.0, 4.0]]
        candidate["structure"]["qdot"][1] = 0.75
        candidate["slices"][0]["time_files"][0]["sha256"] = "c" * 64
        report = compare_checkpoint_payloads(_payload(), candidate)
        checks = report["comparisons"]
        self.assertFalse(report["passed"])
        self.assertFalse(checks["metadata"]["time_s"]["passed"])
        self.assertFalse(checks["structure"]["qdot"]["passed"])
        self.assertFalse(checks["previous_forces"]["passed"])
        self.assertEqual(len(checks["cfd_manifest_field_hashes"]["changed"]), 1)

    def test_expected_restart_lineage_is_enforced(self) -> None:
        candidate = _payload()
        candidate["restart_parent_checkpoint_sha256"] = "d" * 64
        report = compare_checkpoint_payloads(
            _payload(), candidate, expected_lineage={"restart_parent_checkpoint_sha256": "e" * 64}
        )
        self.assertFalse(report["passed"])
        self.assertFalse(report["comparisons"]["lineage"]["restart_parent_checkpoint_sha256"]["passed"])

    def test_file_comparison_records_manifest_file_hashes(self) -> None:
        payload = _payload()
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            checkpoint.write_text(json.dumps(payload), encoding="utf-8")
            report = compare_checkpoint_files(checkpoint, checkpoint)
            self.assertTrue(report["passed"])
            self.assertEqual(report["reference_checkpoint_sha256"], hashlib.sha256(checkpoint.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
