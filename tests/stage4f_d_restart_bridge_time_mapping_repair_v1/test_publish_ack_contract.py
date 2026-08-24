import json
import tempfile
import unittest
from pathlib import Path

from coupling.multi_slice_driver.real_process import (
    RealProcessFreshnessError,
    materialize_legacy_motion_bridge,
    validate_bridge_ack,
)


def record(step=560, time_s=2.20875):
    return {
        "step": step, "time_s": time_s, "slice_id": 0,
        "case_id": "case-restart-1", "s_ref_m": 1.0,
        "x_m": 0.0, "y_m": 0.1, "z_m": 1.0,
        "vx_mps": 0.0, "vy_mps": 0.0, "vz_mps": 0.0,
        "ax_mps2": 0.0, "ay_mps2": 0.0, "az_mps2": 0.0,
    }


class TestBridgePublishAckContract(unittest.TestCase):
    def test_source_seed_and_target_are_case_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp)
            seed = dict(record(step=559, time_s=2.2075))
            seed_snapshot = materialize_legacy_motion_bridge(
                record=seed, case=case, exchange_dir="coupling", seed=True,
                seed_time_s=2.2075, seed_step_offset=0,
            )
            self.assertEqual(seed_snapshot.bridge_step, 0)
            target_snapshot = materialize_legacy_motion_bridge(
                record=record(), case=case, exchange_dir="coupling",
                target_bridge_step=1,
            )
            self.assertEqual(target_snapshot.bridge_step, 1)
            self.assertAlmostEqual(target_snapshot.bridge_time_s, 2.20875)

    def test_ack_must_be_new_and_match_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp)
            snap = materialize_legacy_motion_bridge(
                record=record(), case=case, exchange_dir="coupling",
                target_bridge_step=1,
            )
            ack = case / "coupling" / "consumed" / "motion_consumed_1.json"
            ack.parent.mkdir(parents=True, exist_ok=True)
            ack.write_text(json.dumps({"step": 1, "time_s": 2.20875,
                                       "slice_id": 0, "case_id": "case-restart-1"}),
                           encoding="utf-8")
            validate_bridge_ack(ack_path=ack, snapshot=snap, record=record())

    def test_old_ack_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp)
            snap = materialize_legacy_motion_bridge(
                record=record(), case=case, exchange_dir="coupling",
                target_bridge_step=1,
            )
            ack = case / "coupling" / "consumed" / "motion_consumed_1.json"
            ack.parent.mkdir(parents=True, exist_ok=True)
            ack.write_text(json.dumps({"step": 0, "time_s": 2.2075}),
                           encoding="utf-8")
            with self.assertRaises(RealProcessFreshnessError):
                validate_bridge_ack(ack_path=ack, snapshot=snap, record=record())


if __name__ == "__main__":
    unittest.main()
