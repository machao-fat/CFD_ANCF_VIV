import json
import math
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_three_slice_timestep_diagnostic_v3.bridge_precision import (
    audit_source,
    serialize_consumed,
    validate_round_trip,
)


class TestBridgePrecision(unittest.TestCase):
    def test_d2_time_round_trips(self):
        expected = 1.5081250000000002
        payload = serialize_consumed(step=1, time_s=expected)
        self.assertEqual(validate_round_trip(payload, expected_step=1, expected_time_s=expected)["time_s"], expected)

    def test_legacy_six_digit_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact binary64"):
            validate_round_trip('{"step":1,"time_s":1.50813}', expected_step=1, expected_time_s=1.5081250000000002)

    def test_wrong_step_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "step"):
            validate_round_trip(serialize_consumed(step=2, time_s=1.508125), expected_step=1, expected_time_s=1.508125)

    def test_nonfinite_is_rejected(self):
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token), self.assertRaisesRegex(ValueError, "non-finite"):
                validate_round_trip('{"step":1,"time_s":%s}' % token, expected_step=1, expected_time_s=1.0)

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ValueError):
            serialize_consumed(step=-1, time_s=1.0)
        with self.assertRaises(ValueError):
            serialize_consumed(step=1, time_s=math.nan)

    def test_source_audit_requires_precision_headers_and_manipulator(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "motion.C"
            source.write_text("std::ostringstream consumed;", encoding="utf-8")
            self.assertFalse(audit_source(source)["passed"])

    def test_source_audit_accepts_repaired_source(self):
        source = Path(__file__).resolve().parents[2] / "src" / "openfoam" / "ancfFileMotion_stage4f_c_v3" / "ancfFileMotion.C"
        self.assertTrue(audit_source(source)["passed"])


if __name__ == "__main__":
    unittest.main()
