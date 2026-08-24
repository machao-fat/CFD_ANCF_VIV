from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from coupling.file_exchange.csv_contract import atomic_write_csv  # noqa: E402
from coupling.file_exchange.motion_csv_to_openfoam import main as motion_table_main  # noqa: E402
from coupling.online_file_coupling.protocol import (  # noqa: E402
    FileCouplingError,
    publish_ready,
    read_ready_snapshot,
)


MOTION_FIELDS = (
    "schema_version", "step", "coupling_iteration", "time_s", "slice_id", "s_ref_m",
    "x_m", "y_m", "z_m", "vx_mps", "vy_mps", "vz_mps", "ax_mps2", "ay_mps2", "az_mps2",
)

LOAD_FIELDS = (
    "schema_version", "step", "coupling_iteration", "time_s", "slice_id", "s_ref_m",
    "force_x_N", "force_y_N", "force_z_N",
)


def motion_rows(step: int = 3, time_s: float = 0.03):
    return [
        {
            "schema_version": "0.1.0", "step": step, "coupling_iteration": 0,
            "time_s": time_s, "slice_id": 0, "s_ref_m": 0.0,
            "x_m": 0.0, "y_m": 0.01, "z_m": 0.0,
            "vx_mps": 0.0, "vy_mps": 0.2, "vz_mps": 0.0,
            "ax_mps2": 0.0, "ay_mps2": -0.4, "az_mps2": 0.0,
        },
        {
            "schema_version": "0.1.0", "step": step, "coupling_iteration": 0,
            "time_s": time_s, "slice_id": 1, "s_ref_m": 1.0,
            "x_m": 0.0, "y_m": 0.02, "z_m": 1.0,
            "vx_mps": 0.0, "vy_mps": 0.3, "vz_mps": 0.0,
            "ax_mps2": 0.0, "ay_mps2": -0.5, "az_mps2": 0.0,
        },
    ]


def load_rows(step: int = 3, time_s: float = 0.03, *, refs=(75.0,)):
    return [
        {
            "schema_version": "0.1.0", "step": step, "coupling_iteration": 0,
            "time_s": time_s, "slice_id": index, "s_ref_m": s_ref,
            "force_x_N": 0.0, "force_y_N": 10.0 + index, "force_z_N": 0.0,
        }
        for index, s_ref in enumerate(refs)
    ]


class FileProtocolTests(unittest.TestCase):
    def test_publish_and_read_requires_exact_step_time_and_digest(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "motion.csv"
            marker = root / "motion_ready"
            atomic_write_csv(payload, MOTION_FIELDS, motion_rows())
            metadata = publish_ready(payload, marker, kind="motion", expected_s_ref_m=[0.0, 1.0])
            self.assertEqual(metadata["step"], 3)
            rows = read_ready_snapshot(
                payload, marker, kind="motion", expected_step=3,
                expected_time_s=0.03, expected_coupling_iteration=0,
                expected_s_ref_m=[0.0, 1.0],
            )
            self.assertEqual(len(rows), 2)
            with self.assertRaisesRegex(FileCouplingError, "step mismatch"):
                read_ready_snapshot(
                    payload, marker, kind="motion", expected_step=4,
                    expected_time_s=0.03, expected_s_ref_m=[0.0, 1.0],
                )

    def test_marker_and_payload_coupling_iteration_must_match(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "motion.csv"
            marker = root / "motion_ready"
            atomic_write_csv(payload, MOTION_FIELDS, motion_rows())
            publish_ready(payload, marker, kind="motion", expected_s_ref_m=[0.0, 1.0])
            data = json.loads(marker.read_text(encoding="utf-8"))
            data["coupling_iteration"] = 1
            marker.write_text(json.dumps(data) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(FileCouplingError, "coupling_iteration mismatch"):
                read_ready_snapshot(
                    payload, marker, kind="motion", expected_step=3,
                    expected_time_s=0.03, expected_coupling_iteration=0,
                    expected_s_ref_m=[0.0, 1.0],
                )

    def test_payload_change_after_ready_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "motion.csv"
            marker = root / "motion_ready"
            atomic_write_csv(payload, MOTION_FIELDS, motion_rows())
            publish_ready(payload, marker, kind="motion", expected_s_ref_m=[0.0, 1.0])
            changed = motion_rows()
            changed[0]["y_m"] = 0.011
            atomic_write_csv(payload, MOTION_FIELDS, changed)
            with self.assertRaisesRegex(FileCouplingError, "payload changed"):
                read_ready_snapshot(
                    payload, marker, kind="motion", expected_step=3,
                    expected_time_s=0.03, expected_s_ref_m=[0.0, 1.0],
                )

    def test_nan_and_missing_marker_fail_without_fallback(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "load.csv"
            marker = root / "load_ready"
            row = {
                "schema_version": "0.1.0", "step": 3, "coupling_iteration": 0,
                "time_s": 0.03, "slice_id": 0, "s_ref_m": 0.0,
                "force_x_N": "nan", "force_y_N": 0.0, "force_z_N": 0.0,
            }
            atomic_write_csv(payload, LOAD_FIELDS, [row])
            with self.assertRaises(FileCouplingError):
                publish_ready(payload, marker, kind="load", expected_s_ref_m=[0.0])
            row["force_x_N"] = 1.0
            atomic_write_csv(payload, LOAD_FIELDS, [row])
            with self.assertRaisesRegex(FileCouplingError, "missing ready marker"):
                read_ready_snapshot(
                    payload, marker, kind="load", expected_step=3,
                    expected_time_s=0.03, expected_s_ref_m=[0.0],
                )

    def test_load_s_ref_is_required_and_checked(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "load.csv"
            marker = root / "load_ready"
            atomic_write_csv(payload, LOAD_FIELDS, load_rows(refs=(75.0,)))
            publish_ready(payload, marker, kind="load", expected_s_ref_m=[75.0])
            rows = read_ready_snapshot(
                payload, marker, kind="load", expected_step=3,
                expected_time_s=0.03, expected_s_ref_m=[75.0],
            )
            self.assertEqual(float(rows[0]["s_ref_m"]), 75.0)
            with self.assertRaisesRegex(FileCouplingError, "s_ref_m"):
                read_ready_snapshot(
                    payload, marker, kind="load", expected_step=3,
                    expected_time_s=0.03, expected_s_ref_m=[0.0],
                )

    def test_load_coordinate_rewrite_after_marker_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "load.csv"
            marker = root / "load_ready"
            atomic_write_csv(payload, LOAD_FIELDS, load_rows(refs=(75.0,)))
            publish_ready(payload, marker, kind="load", expected_s_ref_m=[75.0])
            changed = load_rows(refs=(0.0,))
            atomic_write_csv(payload, LOAD_FIELDS, changed)
            with self.assertRaisesRegex(FileCouplingError, "s_ref_m"):
                read_ready_snapshot(
                    payload, marker, kind="load", expected_step=3,
                    expected_time_s=0.03, expected_s_ref_m=[75.0],
                )

    def test_multi_slice_load_coordinates_follow_slice_id(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            payload = root / "load.csv"
            marker = root / "load_ready"
            rows = load_rows(refs=(75.0, 120.0))
            rows.reverse()
            atomic_write_csv(payload, LOAD_FIELDS, rows)
            publish_ready(payload, marker, kind="load", expected_s_ref_m=[75.0, 120.0])
            accepted = read_ready_snapshot(
                payload, marker, kind="load", expected_step=3,
                expected_time_s=0.03, expected_s_ref_m=[75.0, 120.0],
            )
            self.assertEqual({int(float(row["slice_id"])): float(row["s_ref_m"]) for row in accepted}, {0: 75.0, 1: 120.0})

    def test_native_openfoam_table_has_supported_tabulated6dof_format(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            snapshots = root / "snapshots"
            snapshots.mkdir()
            for step, time_s in enumerate((0.0, 0.01, 0.02)):
                path = snapshots / f"motion_{step:08d}.csv"
                rows = [motion_rows(step, time_s)[0]]
                atomic_write_csv(path, MOTION_FIELDS, rows)
            output = root / "motion.dat"
            old_argv = sys.argv
            try:
                sys.argv = [
                    "motion_csv_to_openfoam.py", "--input", str(snapshots),
                    "--output", str(output), "--slice-id", "0",
                ]
                motion_table_main()
            finally:
                sys.argv = old_argv
            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "3")
            self.assertEqual(lines[1], "(")
            self.assertEqual(lines[-1], ")")
            self.assertIn("((0 0.01 0) (0 0 0))", lines[3])
            self.assertIn("(0.02 ((0 0.01 0) (0 0 0)))", lines[4])


if __name__ == "__main__":
    unittest.main()
