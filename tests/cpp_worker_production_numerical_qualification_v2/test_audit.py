from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from coupling.cpp_worker_production_numerical_qualification_v2.audit import (
    QualificationError, compare_step, validate_golden,
)
from tools.cpp_worker_production_numerical_qualification_v2.run_production_qualification import canonicalize_matlab_golden


def record(index: int = 1) -> dict[str, object]:
    vectors = {name: [float(index)] * 102 for name in (
        "q", "qdot", "qddot", "internal_force", "external_force",
        "generalized_force", "predictor", "corrector")}
    values = [value for name in vectors for value in vectors[name]]
    payload = struct.pack("<" + "d" * len(values), *values)
    return {
        "run_id": "r", "case_id": "c", "global_step": 559 + index,
        "case_local_bridge_step": index, "time_s": 2.2075 + index * 0.00125,
        "integer_tick": 2_207_500_000 + index * 1_250_000, "sequence": index,
        "request_id": 206_000 + index, "transaction_id": 206_000_000 + index,
        "return_code": 0, "iterations": 2, "gauss_order": 3, "max_newton": 40,
        "mass_gauss_order": 5, "finite_value_audit": True, "residual": 1.0e-9,
        "checkpoint": {"step": 559 + index}, "payload_size_bytes": len(payload),
        "payload_hash": hashlib.sha256(payload).hexdigest(), **vectors,
    }


class QualificationAuditTests(unittest.TestCase):
    def test_validates_complete_production_golden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "golden.jsonl"
            path.write_text("\n".join(json.dumps(record(i)) for i in range(1, 41)), encoding="utf-8")
            self.assertEqual(len(validate_golden(path, run_id="r", case_id="c")), 40)

    def test_contract_and_payload_tampering_fail_closed(self) -> None:
        row = record(); row["gauss_order"] = 5
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "golden.jsonl"
            path.write_text("\n".join(json.dumps(row if i == 1 else record(i)) for i in range(1, 41)), encoding="utf-8")
            with self.assertRaises(QualificationError):
                validate_golden(path, run_id="r", case_id="c")
        with self.assertRaises(QualificationError):
            compare_step(record(), {**record(), "q": [9.0] * 102})

    def test_iteration_and_identity_mismatch_fail_closed(self) -> None:
        candidate = record(); candidate["iterations"] = 3
        with self.assertRaises(QualificationError):
            compare_step(record(), candidate)

    def test_canonicalizer_retains_matlab_hash_and_pins_json_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.jsonl"; canonical = Path(directory) / "canonical.jsonl"
            row = record(); row["payload_hash"] = "0" * 64
            raw.write_text("\n".join(json.dumps(row if i == 1 else record(i)) for i in range(1, 41)), encoding="utf-8")
            result = canonicalize_matlab_golden(raw, canonical)
            self.assertEqual(result["matlab_reported_hash_mismatches"], 1)
            rows = validate_golden(canonical, run_id="r", case_id="c")
            self.assertEqual(rows[0]["matlab_reported_payload_hash"], "0" * 64)


if __name__ == "__main__":
    unittest.main()
