"""Stage-two CSV contract tests; runnable with the Python standard library."""

from __future__ import annotations

import csv
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXCHANGE = ROOT / "src" / "coupling" / "file_exchange"
sys.path.insert(0, str(EXCHANGE))

from csv_contract import (  # noqa: E402
    ContractError,
    LOAD_REQUIRED,
    MOTION_REQUIRED,
    atomic_write_csv,
    validate_load_csv,
    validate_motion_csv,
)


def motion_row(step: int = 0, time_s: float = 0.0, y: float = 0.0, vy: float = 0.0, ay: float = 0.0):
    return {
        "schema_version": "0.1.0",
        "step": step,
        "coupling_iteration": 0,
        "time_s": time_s,
        "slice_id": 0,
        "s_ref_m": 0.0,
        "x_m": 0.0,
        "y_m": y,
        "z_m": 0.0,
        "vx_mps": 1.0,
        "vy_mps": vy,
        "vz_mps": 0.0,
        "ax_mps2": 0.0,
        "ay_mps2": ay,
        "az_mps2": 0.0,
    }


def load_row(step: int, time_s: float, force_y: float, force_x: float = 0.0):
    return {
        "schema_version": "0.1.0",
        "step": step,
        "coupling_iteration": 0,
        "time_s": time_s,
        "slice_id": 0,
        "s_ref_m": 0.0,
        "force_representation": "integrated_N",
        "unit_span_m": 1.0,
        "slice_length_m": 0.25,
        "force_x_N": force_x,
        "force_y_N": force_y,
        "force_z_N": 0.0,
        "pressure_force_x_N": 0.0,
        "pressure_force_y_N": force_y,
        "pressure_force_z_N": 0.0,
        "viscous_force_x_N": force_x,
        "viscous_force_y_N": 0.0,
        "viscous_force_z_N": 0.0,
        "moment_x_Nm": 0.0,
        "moment_y_Nm": 0.0,
        "moment_z_Nm": 0.0,
        "cfd_time_step_s": 0.01,
        "status": "complete",
    }


class CsvContractTests(unittest.TestCase):
    def test_static_cylinder_motion_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "motion_static.csv"
            atomic_write_csv(path, MOTION_REQUIRED, [motion_row()])
            rows = validate_motion_csv(path, expected_s_ref_m=[0.0])
            self.assertEqual(len(rows), 1)
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_sinusoidal_motion_snapshot(self):
        omega = 2.0 * math.pi * 0.16
        t = 0.37
        row = motion_row(
            step=37,
            time_s=t,
            y=0.1 * math.sin(omega * t),
            vy=0.1 * omega * math.cos(omega * t),
            ay=-0.1 * omega * omega * math.sin(omega * t),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "motion_sine.csv"
            atomic_write_csv(path, MOTION_REQUIRED, [row])
            self.assertEqual(validate_motion_csv(path)[0]["step"], "37")

    def test_constant_virtual_force_history(self):
        rows = [load_row(i, i * 0.01, force_y=2.5) for i in range(5)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "loads.csv"
            atomic_write_csv(path, list(rows[0]), rows)
            checked = validate_load_csv(path)
            self.assertEqual(len(checked), 5)
            self.assertTrue(all(float(row["force_y_N"]) == 2.5 for row in checked))

    def test_force_conversion_applies_slice_length_once(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            forces = folder / "forces.dat"
            forces.write_text(
                "# Time forces moments\n"
                "0.0 ((1 2 0) (3 4 0)) ((0 0 0) (0 0 0))\n"
                "0.1 ((2 1 0) (4 3 0)) ((0 0 0) (0 0 0))\n",
                encoding="utf-8",
            )
            output = folder / "loads.csv"
            converter = EXCHANGE / "convert_openfoam_forces.py"
            subprocess.run(
                [
                    sys.executable,
                    str(converter),
                    "--forces",
                    str(forces),
                    "--output",
                    str(output),
                    "--unit-span-m",
                    "1",
                    "--slice-length-m",
                    "0.25",
                    "--dt",
                    "0.1",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            with output.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertAlmostEqual(float(rows[0]["force_x_N"]), 1.0)
            self.assertAlmostEqual(float(rows[0]["force_y_N"]), 1.5)
            self.assertEqual(rows[0]["force_representation"], "integrated_N")

    def test_motion_snapshot_conversion_to_openfoam_table(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            snapshots = folder / "motion"
            snapshots.mkdir()
            for step in range(2):
                atomic_write_csv(
                    snapshots / f"motion_{step:08d}.csv",
                    MOTION_REQUIRED,
                    [motion_row(step=step, time_s=step * 0.1, y=step * 0.01)],
                )
            output = folder / "motion_table.dat"
            converter = EXCHANGE / "motion_csv_to_openfoam.py"
            subprocess.run(
                [sys.executable, str(converter), "--input", str(snapshots), "--output", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            lines = output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 5)
            self.assertEqual(lines[0], "2")
            self.assertEqual(lines[1], "(")
            self.assertTrue(lines[2].startswith("(0 ((0 0 0)"))
            self.assertTrue(lines[3].startswith("(0.10000000000000001 ((0 0.01 0)"))
            self.assertEqual(lines[4], ")")

    def test_bad_slice_id_nan_and_nonmonotonic_time_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            motion = folder / "bad_motion.csv"
            bad = motion_row()
            bad["slice_id"] = 2
            atomic_write_csv(motion, MOTION_REQUIRED, [bad])
            with self.assertRaises(ContractError):
                validate_motion_csv(motion)

            loads = folder / "bad_loads.csv"
            rows = [load_row(0, 0.1, 1.0), load_row(1, 0.0, 1.0)]
            rows[0]["force_y_N"] = "nan"
            atomic_write_csv(loads, list(rows[0]), rows)
            with self.assertRaises(ContractError):
                validate_load_csv(loads)

            rows[0]["force_y_N"] = 1.0
            atomic_write_csv(loads, list(rows[0]), rows)
            with self.assertRaises(ContractError):
                validate_load_csv(loads)


if __name__ == "__main__":
    unittest.main(verbosity=2)
