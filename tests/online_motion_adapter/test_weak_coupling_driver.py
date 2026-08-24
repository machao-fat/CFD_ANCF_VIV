from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from src.coupling.file_exchange.csv_contract import LOAD_REQUIRED, MOTION_REQUIRED, atomic_write_csv
from src.coupling.online_file_coupling import OnePassWeakCoupling, publish_ready


class WeakCouplingDriverTests(unittest.TestCase):
    def test_one_pass_order_and_audit_fields(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            motion = root / "motion.csv"
            motion_ready = root / "motion_ready"
            load = root / "load.csv"
            load_ready = root / "load_ready"
            events: list[str] = []

            def build_motion(path: Path, marker: Path, step: int, time_s: float):
                events.append("motion")
                atomic_write_csv(
                    path,
                    MOTION_REQUIRED,
                    [{
                        "schema_version": "0.1.0", "step": step,
                        "coupling_iteration": 0, "time_s": time_s,
                        "slice_id": 0, "s_ref_m": 0.0,
                        "x_m": 0.0, "y_m": 0.01, "z_m": 0.0,
                        "vx_mps": 0.2, "vy_mps": 0.0, "vz_mps": 0.0,
                        "ax_mps2": 0.0, "ay_mps2": 0.0, "az_mps2": 0.0,
                    }],
                )
                return {
                    "x_m": 0.0, "y_m": 0.01, "z_m": 0.0,
                    "vx_mps": 0.2, "vy_mps": 0.0, "vz_mps": 0.0,
                }

            def run_cfd(step: int, time_s: float) -> None:
                events.append("cfd")
                atomic_write_csv(
                    load,
                    LOAD_REQUIRED,
                    [{
                        "schema_version": "0.1.0", "step": step,
                        "coupling_iteration": 0, "time_s": time_s,
                        "slice_id": 0, "s_ref_m": 0.0,
                        "force_x_N": 2.0, "force_y_N": -3.0, "force_z_N": 0.0,
                    }],
                )
                publish_ready(load, load_ready, kind="load", expected_s_ref_m=[0.0])

            def correct(load_row):
                events.append("correct")
                return {
                    "x_m": 0.001, "y_m": 0.01, "z_m": 0.0,
                    "vx_mps": 0.1, "vy_mps": 0.0, "vz_mps": 0.0,
                }

            driver = OnePassWeakCoupling(
                motion_csv=motion, motion_ready=motion_ready,
                load_csv=load, load_ready=load_ready, s_ref_m=[0.0],
            )
            record = driver.exchange_step(
                step=1, time_s=0.1, motion_builder=build_motion,
                cfd_runner=run_cfd, corrector=correct,
            )
            self.assertEqual(events, ["motion", "cfd", "correct"])
            self.assertAlmostEqual(record.predicted_position_residual_m, 0.001)
            self.assertAlmostEqual(record.predicted_velocity_residual_mps, 0.1)
            self.assertAlmostEqual(record.force_change_N, (2.0**2 + 3.0**2) ** 0.5)
            self.assertAlmostEqual(record.instantaneous_power_W, 0.2)


if __name__ == "__main__":
    unittest.main()
