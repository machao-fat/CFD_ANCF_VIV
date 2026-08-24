from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from coupling.cpp_worker_numerical_equivalence_v1.golden_validator import GoldenValidationError, validate_jsonl


def _record(index: int = 1) -> dict[str, object]:
    vectors = {name: [float(index)] * 102 for name in ("q", "qdot", "qddot", "internal_force", "external_force", "generalized_force", "predictor", "corrector")}
    payload = struct.pack("<" + "d" * 816, *(value for name in vectors for value in vectors[name]))
    return {"run_id": "r", "case_id": "c", "global_step": 559 + index, "case_local_bridge_step": index,
            "time_s": 2.2075 + index * 0.00125, "integer_tick": round((2.2075 + index * 0.00125) * 1e9),
            "sequence": index, "request_id": 510000 + index, "transaction_id": 520000 + index,
            "return_code": 0, "finite_value_audit": True, **vectors,
            "payload_size_bytes": len(payload), "payload_hash": hashlib.sha256(payload).hexdigest(),
            "checkpoint": {"step": 559 + index}}


class GoldenValidatorTests(unittest.TestCase):
    def test_valid_bounded_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "golden.jsonl"
            path.write_text("\n".join(json.dumps(_record(index)) for index in range(1, 41)), encoding="utf-8")
            result = validate_jsonl(path, run_id="r", case_id="c")
            self.assertEqual(result["count"], 40)

    def test_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "golden.jsonl"
            rows = [_record(index) for index in range(1, 41)]
            rows[0]["payload_hash"] = "0" * 64
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            with self.assertRaises(GoldenValidationError):
                validate_jsonl(path, run_id="r", case_id="c")


if __name__ == "__main__":
    unittest.main()
