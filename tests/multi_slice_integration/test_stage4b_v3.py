from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from src.coupling.multi_slice_driver.real_process import (
    RealProcessFreshnessError,
    assert_fresh_case,
    bridge_for_global_step,
    bridge_seed,
    fingerprint,
    materialize_legacy_motion_bridge,
    parse_force_exact,
    validate_bridge_ack,
    validate_initial_state,
)


class Stage4BV3FreshnessTests(unittest.TestCase):
    def _record(self, *, step: int = 0, time_s: float = 0.0025) -> dict[str, object]:
        return {
            "schema_version": "0.2.1", "case_id": "fresh_case", "step": step,
            "coupling_iteration": 0, "time_s": time_s, "slice_id": 0,
            "s_ref_m": 2.5, "slice_length_m": 5.0, "x_ref_m": 0.0,
            "y_ref_m": 0.0, "z_ref_m": 2.5, "ux_m": 0.0, "uy_m": 0.0,
            "uz_m": 0.0, "x_m": 0.0, "y_m": 0.0, "z_m": 2.5,
            "vx_mps": 0.0, "vy_mps": 0.0, "vz_mps": 0.0,
            "ax_mps2": 0.0, "ay_mps2": 0.0, "az_mps2": 0.0,
            "status": "complete",
        }

    def test_seed_and_target_bridge_are_not_off_by_one(self):
        self.assertEqual(bridge_seed(start_time_s=0.0025), (0, 0.0025))
        self.assertEqual(bridge_for_global_step(global_step=0, target_time_s=0.005), (1, 0.005))
        self.assertEqual(bridge_for_global_step(global_step=1, target_time_s=0.0075), (2, 0.0075))

    def test_bridge_ack_requires_current_step_time_and_mtime(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            record = self._record(step=0, time_s=0.005)
            snapshot = materialize_legacy_motion_bridge(record=record, case=root, exchange_dir="coupling")
            ack = root / "coupling" / "consumed" / "motion_consumed_1.json"
            ack.parent.mkdir(parents=True, exist_ok=True)
            ack.write_text(json.dumps({"kind": "motion_consumed", "step": 1, "time_s": 0.005}), encoding="utf-8")
            os.utime(ack, ns=(snapshot.published_ns + 1, snapshot.published_ns + 1))
            self.assertEqual(validate_bridge_ack(ack_path=ack, snapshot=snapshot, record=record)["step"], 1)
            ack.write_text(json.dumps({"kind": "motion_consumed", "step": 0, "time_s": 0.005}), encoding="utf-8")
            os.utime(ack, ns=(snapshot.published_ns + 2, snapshot.published_ns + 2))
            with self.assertRaises(RealProcessFreshnessError):
                validate_bridge_ack(ack_path=ack, snapshot=snapshot, record=record)

    def test_force_parser_requires_exact_target_and_new_file(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "forces.dat"
            path.write_text(
                "# Forces\n0.0025 ((1 2 3) (4 5 6)) ((0 0 0) (0 0 0))\n",
                encoding="utf-8",
            )
            self.assertIsNone(parse_force_exact(path, target_time_s=0.005))
            path.write_text(
                "# Forces\n0.005 ((1 2 3) (4 5 6)) ((0 0 0) (0 0 0))\n",
                encoding="utf-8",
            )
            current = parse_force_exact(path, target_time_s=0.005)
            self.assertIsNotNone(current)
            self.assertIsNone(parse_force_exact(path, target_time_s=0.0075, previous=None))
            self.assertIsNone(parse_force_exact(path, target_time_s=0.005, previous=fingerprint(path)))

    def test_freshness_rejects_old_artifacts(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "postProcessing" / "cylinderForces" / "0").mkdir(parents=True)
            (root / "postProcessing" / "cylinderForces" / "0" / "forces.dat").write_text("old", encoding="utf-8")
            with self.assertRaises(RealProcessFreshnessError):
                assert_fresh_case(root, target_time_name="0.005")

    def test_initial_seed_has_zero_in_plane_increment(self):
        record = self._record(step=0, time_s=0.0)
        self.assertEqual(
            validate_initial_state(reference_positions={0: (0.0, 0.0, 2.5)}, seed_records=[record])["slices"][0]["displacement_m"],
            [0.0, 0.0, 0.0],
        )
        record["y_m"] = 0.1
        with self.assertRaises(RealProcessFreshnessError):
            validate_initial_state(reference_positions={0: (0.0, 0.0, 2.5)}, seed_records=[record])

    def test_generator_does_not_copy_runtime_history_and_rejects_existing_output(self):
        project = Path(__file__).resolve().parents[2]
        generator = project / "cases" / "openfoam" / "multi_slice_template" / "generate_case.py"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "reference"
            (source / "constant").mkdir(parents=True)
            (source / "system").mkdir(parents=True)
            (source / "0").mkdir()
            (source / "constant" / "mesh.txt").write_text("mesh", encoding="utf-8")
            (source / "system" / "fvSolution").write_text("solution", encoding="utf-8")
            (source / "0" / "U").write_text("initial", encoding="utf-8")
            (source / "postProcessing" / "cylinderForces" / "0").mkdir(parents=True)
            (source / "postProcessing" / "cylinderForces" / "0" / "forces.dat").write_text("old", encoding="utf-8")
            output = root / "new_case"
            command = [sys.executable, str(generator), "--output", str(output), "--reference-case", str(source), "--case-id", "fresh", "--slice-id", "0", "--s-ref-m", "2.5", "--slice-length-m", "5", "--start-time", "0", "--end-time", "0.005", "--delta-t", "0.0025"]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse((output / "postProcessing" / "cylinderForces" / "0" / "forces.dat").exists())
            self.assertFalse((output / "coupling" / "motion.csv").exists())
            self.assertTrue((output / "case_provenance.json").is_file())
            second = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertNotEqual(second.returncode, 0)


if __name__ == "__main__":
    unittest.main()
