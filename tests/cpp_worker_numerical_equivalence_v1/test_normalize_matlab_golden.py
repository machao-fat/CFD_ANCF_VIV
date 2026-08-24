from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coupling.cpp_worker_numerical_equivalence_v1.golden_validator import validate_jsonl
from tools.cpp_worker_numerical_equivalence_v1.normalize_matlab_golden import normalize


VECTOR_FIELDS = (
    "q",
    "qdot",
    "qddot",
    "internal_force",
    "external_force",
    "generalized_force",
    "predictor",
    "corrector",
)


def _raw_record(index: int) -> dict[str, object]:
    value = float(index)
    vectors = {field: [value] * 102 for field in VECTOR_FIELDS}
    time_s = 2.2075 + index * 0.00125
    return {
        "run_id": "r",
        "case_id": "c",
        "global_step": 559 + index,
        "case_local_bridge_step": index,
        "time_s": time_s,
        "integer_tick": round(time_s * 1e9),
        "sequence": index,
        "request_id": 510000 + index,
        "transaction_id": 520000 + index,
        "return_code": 0,
        "finite_value_audit": True,
        "checkpoint": {"step": 559 + index},
        "payload_hash": f"matlab-hash-{index}",
        "payload_size_bytes": 0,
        **vectors,
    }


class NormalizeMatlabGoldenTests(unittest.TestCase):
    def test_matlab_float_identity_fields_are_canonicalized_to_int(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [_raw_record(index) for index in range(1, 41)]
            rows[0]["global_step"] = 560.0
            rows[0]["case_local_bridge_step"] = 1.0
            rows[0]["integer_tick"] = 2208750000.0
            raw = root / "raw.jsonl"
            normalized = root / "normalized.jsonl"
            raw.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            self.assertEqual(normalize(raw, normalized), 40)
            first = json.loads(normalized.read_text(encoding="utf-8").splitlines()[0])
            self.assertIsInstance(first["global_step"], int)
            self.assertIsInstance(first["case_local_bridge_step"], int)
            self.assertIsInstance(first["integer_tick"], int)
            self.assertEqual(first["integer_tick"], 2208750000)

    def test_fractional_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = _raw_record(1)
            row["integer_tick"] = 2208750000.5
            raw = root / "raw.jsonl"
            normalized = root / "normalized.jsonl"
            raw.write_text("\n".join(json.dumps(_raw_record(index)) if index != 1 else json.dumps(row)
                                       for index in range(1, 41)), encoding="utf-8")
            with self.assertRaises(ValueError):
                normalize(raw, normalized)

    def test_normalized_payload_is_validator_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.jsonl"
            normalized = root / "normalized.jsonl"
            raw.write_text("\n".join(json.dumps(_raw_record(index)) for index in range(1, 41)), encoding="utf-8")

            self.assertEqual(normalize(raw, normalized), 40)
            rows = [json.loads(line) for line in normalized.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["matlab_payload_hash_original"], "matlab-hash-1")
            self.assertNotEqual(rows[0]["payload_hash"], rows[0]["matlab_payload_hash_original"])
            self.assertEqual(validate_jsonl(normalized, run_id="r", case_id="c")["count"], 40)


if __name__ == "__main__":
    unittest.main()
