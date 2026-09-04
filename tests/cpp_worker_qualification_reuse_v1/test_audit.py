from __future__ import annotations

import unittest

from coupling.cpp_worker_qualification_reuse_v1 import assess_reuse


def identity() -> dict[str, object]:
    return {
        "worker_sha256": "a" * 64,
        "worker_size_bytes": 100,
        "worker_mtime_ns": 200,
        "library_sha256": "b" * 64,
        "model_contract_sha256": "c" * 64,
        "gauss_order": 3,
        "max_newton": 40,
        "global_dt_s": 0.00125,
        "formal_protocol": "0.2.1",
    }


class QualificationReuseTests(unittest.TestCase):
    def test_all_pinned_identities_allow_reuse(self) -> None:
        value = identity()
        qualification = {**value, "dual_run_status": "pass", "numerical_core_status": "validated"}
        result = assess_reuse(qualification, value)
        self.assertTrue(result["reuse_eligible"])
        self.assertEqual(result["C++_ANCF_NUMERICAL_CORE_STATUS"], "qualified_by_reuse")

    def test_missing_worker_hash_is_fail_closed(self) -> None:
        value = identity()
        qualification = {**value, "dual_run_status": "pass", "numerical_core_status": "validated"}
        qualification.pop("worker_sha256")
        result = assess_reuse(qualification, value)
        self.assertFalse(result["reuse_eligible"])
        self.assertIn("missing identity: worker_sha256", result["errors"])

    def test_numerical_contract_mismatch_is_fail_closed(self) -> None:
        value = identity()
        qualification = {**value, "dual_run_status": "pass", "numerical_core_status": "validated", "gauss_order": 5}
        result = assess_reuse(qualification, value)
        self.assertFalse(result["reuse_eligible"])
        self.assertIn("identity mismatch: gauss_order", result["errors"])

