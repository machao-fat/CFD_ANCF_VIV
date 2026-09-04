from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coupling.multi_slice_driver.real_process import BridgeSnapshot, RealProcessFreshnessError, validate_bridge_ack


class MotionConsumedPrecisionTests(unittest.TestCase):
    def _snapshot(self, root: Path) -> BridgeSnapshot:
        payload = root / "motion.csv"; ready = root / "motion_ready"
        payload.write_text("payload\n", encoding="utf-8"); ready.write_text("ready\n", encoding="utf-8")
        return BridgeSnapshot(3201, 10.00125, payload, ready, 0)

    def test_high_precision_ack_at_ten_seconds_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); snapshot = self._snapshot(root); ack = root / "ack.json"
            ack.write_text(json.dumps({"kind": "motion_consumed", "step": 3201, "time_s": 10.00125}), encoding="utf-8")
            value = validate_bridge_ack(ack_path=ack, snapshot=snapshot, record={"slice_id": 2, "case_id": "case"})
            self.assertEqual(value["time_s"], 10.00125)

    def test_six_significant_digit_ack_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); snapshot = self._snapshot(root); ack = root / "ack.json"
            ack.write_text(json.dumps({"kind": "motion_consumed", "step": 3201, "time_s": 10.0013}), encoding="utf-8")
            with self.assertRaises(RealProcessFreshnessError):
                validate_bridge_ack(ack_path=ack, snapshot=snapshot, record={"slice_id": 2, "case_id": "case"})

    def test_cpp_source_uses_round_trip_scalar_precision(self) -> None:
        source = Path(__file__).resolve().parents[2] / "src/openfoam/ancfFileMotion/ancfFileMotion.C"
        text = source.read_text(encoding="utf-8")
        self.assertIn("#include <iomanip>", text)
        self.assertIn("std::numeric_limits<scalar>::max_digits10", text)
        self.assertIn('<< expectedStep << ",\\\"time_s\\\":" << currentTime', text)

    def test_precision_retry_binds_only_the_fresh_library(self) -> None:
        from tools.cpp_worker_to30s_v1 import run_authorized_to30s_003 as attempt
        self.assertEqual(attempt.RUN_ID, "cpp_worker_to30s_003")
        self.assertEqual(attempt.confirm.EXPECTED_LIBRARY_SHA256, "39a51c9a01da1ed63a761b4385d8eb954dc201415f7e21aa3ca9f1cb7087bd07")
        self.assertEqual(attempt.LIBRARY.name, "libancfFileMotion.so")


if __name__ == "__main__":
    unittest.main()
