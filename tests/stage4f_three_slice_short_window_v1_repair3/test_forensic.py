import copy
import json
import unittest
from pathlib import Path

from src.coupling.stage4f_three_slice_short_window_v1_repair3.forensic import (
    audit_checkpoint_identity, audit_force_row, audit_force_step, audit_motion_state,
)


def force_row(sid=0, step=2, time_s=1.515, raw_x=4999.5):
    length = 50.0 / 3.0
    row = {"slice_id": sid, "step": step, "time_s": time_s, "unit_span_m": 1.0,
           "extrusion_thickness_m": 1.0, "slice_length_m": length}
    for axis, raw in zip("xyz", (raw_x, 3.0, 0.0)):
        row[f"openfoam_force_{axis}_N"] = raw
        row[f"force_2d_{axis}_Npm"] = raw
        row[f"force_{axis}_N"] = raw * length
    return row


class TestForceForensic(unittest.TestCase):
    def test_single_slice_chain(self):
        self.assertTrue(audit_force_row(force_row())["passed"])

    def test_force_coeff_crosscheck(self):
        row = force_row(raw_x=2500.0); row["force_coeff_Cd"] = 5.0
        audit = audit_force_row(row)
        self.assertEqual(audit["Cd_from_raw"], audit["Cd_from_unit_span"])
        self.assertTrue(audit["passed"])

    def test_force_coeff_disagreement_rejected(self):
        row = force_row(raw_x=2500.0); row["force_coeff_Cd"] = 4.0
        self.assertFalse(audit_force_row(row)["passed"])

    def test_extrusion_and_span_are_distinct(self):
        row = force_row(raw_x=1000.0)
        row["extrusion_thickness_m"] = 0.5
        self.assertFalse(audit_force_row(row)["passed"])

    def test_aggregate_does_not_multiply_span_twice(self):
        rows = [force_row(sid=sid, raw_x=30.0) for sid in range(3)]
        audit = audit_force_step(rows, expected_step=2, expected_time_s=1.515)
        self.assertAlmostEqual(audit["aggregate_integrated_force_N"][0], 1500.0)

    def test_cd_just_below_ten_passes(self):
        self.assertTrue(audit_force_row(force_row(raw_x=4999.999999))["passed"])

    def test_cd_above_ten_rejected(self):
        self.assertFalse(audit_force_row(force_row(raw_x=5000.000001))["passed"])

    def test_step_time_misalignment_rejected(self):
        rows = [force_row(sid=sid) for sid in range(3)]
        rows[0]["time_s"] = 1.5125
        self.assertFalse(audit_force_step(rows, expected_step=2, expected_time_s=1.515)["passed"])

    def test_stale_force_rejected(self):
        rows = [force_row(sid=sid) for sid in range(3)]
        rows[1]["step"] = 1
        self.assertFalse(audit_force_step(rows, expected_step=2, expected_time_s=1.515)["passed"])

    def test_duplicate_force_rejected(self):
        rows = [force_row(sid=0), force_row(sid=0), force_row(sid=2)]
        self.assertFalse(audit_force_step(rows, expected_step=2, expected_time_s=1.515)["passed"])

    def test_missing_slice_rejected(self):
        rows = [force_row(sid=0), force_row(sid=2)]
        self.assertFalse(audit_force_step(rows, expected_step=2, expected_time_s=1.515)["passed"])

    def test_repair2_real_step2_still_rejected(self):
        project = Path(__file__).resolve().parents[2]
        summary = json.loads((project / "results/13_stage4f_three_slice_short_window_v1_repair2/real_execution_summary.json").read_text(encoding="utf-8"))
        original = summary["branches"]["A"]["steps"][2]["force_audit"]
        rows = []
        for sid, source in enumerate(original):
            row = {"slice_id": sid, "step": 2, "time_s": 1.515, "unit_span_m": source["unit_span_m"],
                   "extrusion_thickness_m": source["unit_span_m"], "slice_length_m": source["slice_length_m"], "Cd": source["Cd"]}
            for index, axis in enumerate("xyz"):
                row[f"openfoam_force_{axis}_N"] = source["openfoam_force_N"][index]
                row[f"force_2d_{axis}_Npm"] = source["unit_span_force_Npm"][index]
                row[f"force_{axis}_N"] = source["integrated_slice_force_N"][index]
            rows.append(row)
        audit = audit_force_step(rows, expected_step=2, expected_time_s=1.515)
        self.assertFalse(audit["passed"])
        self.assertAlmostEqual(max(row["Cd_from_raw"] for row in audit["slice_audits"]), 11.003110867115256)

    def test_fixture_tampering_cannot_hide_real_failure(self):
        row = force_row(raw_x=5501.555433557628)
        row["force_2d_x_Npm"] = 4999.0
        self.assertFalse(audit_force_row(row)["passed"])


class TestStateAndCheckpoint(unittest.TestCase):
    def setUp(self):
        self.state = {"role": "committed", "step": 2, "time_s": 1.515,
                      "q": [1, 2, 3, 0, 0, 0], "qdot": [0.1, 0.2, 0.3, 0, 0, 0]}
        self.motion = {"step": 2, "time_s": 1.515, "node_index": 0,
                       "position_m": [1, 2, 3], "velocity_mps": [0.1, 0.2, 0.3]}

    def test_matching_committed_state(self):
        self.assertTrue(audit_motion_state(self.motion, self.state, expected_step=2, expected_time_s=1.515, expected_role="committed")["passed"])

    def test_predictor_committed_confusion(self):
        state = dict(self.state, role="predictor")
        self.assertFalse(audit_motion_state(self.motion, state, expected_step=2, expected_time_s=1.515, expected_role="committed")["passed"])

    def test_qdot_node_layout_error(self):
        state = copy.deepcopy(self.state); state["qdot"] = [0.1, 0.2, 0.3]
        with self.assertRaises(ValueError):
            audit_motion_state(self.motion, state, expected_step=2, expected_time_s=1.515, expected_role="committed")

    def test_wrong_time_layer(self):
        state = dict(self.state, time_s=1.5125)
        self.assertFalse(audit_motion_state(self.motion, state, expected_step=2, expected_time_s=1.515, expected_role="committed")["passed"])

    def test_near_zero_velocity_uses_frozen_scale(self):
        state = copy.deepcopy(self.state); state["qdot"] = [0, 0, 0, 0, 0, 0]
        motion = dict(self.motion, velocity_mps=[1e-4, 0, 0])
        audit = audit_motion_state(motion, state, expected_step=2, expected_time_s=1.515, expected_role="committed")
        self.assertAlmostEqual(audit["velocity_difference_over_U"], 1e-4)

    def test_checkpoint_identity(self):
        expected = {"case_id": "c", "slice_manifest_sha256": "m", "config_sha256": "x", "step": 2, "time_s": 1.515, "status": "committed"}
        checkpoint = dict(expected, slices=[{"slice_id": sid} for sid in range(3)])
        self.assertTrue(audit_checkpoint_identity(checkpoint, expected)["passed"])
        checkpoint["config_sha256"] = "wrong"
        self.assertFalse(audit_checkpoint_identity(checkpoint, expected)["passed"])


if __name__ == "__main__":
    unittest.main()
