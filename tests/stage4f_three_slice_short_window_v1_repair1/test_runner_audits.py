import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_three_slice_short_window_v1_repair1.analysis import _endpoint_norm
from src.coupling.stage4f_three_slice_short_window_v1_repair1.contract import PARENT_CASE_ROOT
from src.coupling.stage4f_three_slice_short_window_v1_repair1.runner import _force_audit, _log_audit, cylinder_center


def load_row(raw_x=500.0, unit_x=500.0, integrated_x=500.0 * 50.0 / 3.0):
    row = {"unit_span_m": 1.0, "slice_length_m": 50.0 / 3.0}
    for axis, raw, unit, integrated in (("x", raw_x, unit_x, integrated_x), ("y", 0.0, 0.0, 0.0), ("z", 0.0, 0.0, 0.0)):
        row[f"openfoam_force_{axis}_N"] = raw
        row[f"force_2d_{axis}_Npm"] = unit
        row[f"force_{axis}_N"] = integrated
    return row


class TestRunnerAudits(unittest.TestCase):
    def test_force_conversion_passes(self):
        self.assertTrue(_force_audit(load_row())["passed"])

    def test_force_conversion_detects_double_length(self):
        row = load_row(integrated_x=500.0 * (50.0 / 3.0) ** 2)
        self.assertFalse(_force_audit(row)["passed"])

    def test_force_conversion_near_zero_uses_frozen_scales(self):
        row = load_row(raw_x=0.0, unit_x=1.0e-8, integrated_x=0.0)
        audit = _force_audit(row)
        raw_to_unit = audit["conversion_errors"][0]
        integrated = audit["conversion_errors"][1]
        self.assertEqual(raw_to_unit["frozen_absolute_scale"], 500.0)
        self.assertAlmostEqual(raw_to_unit["relative_error"], 2.0e-11)
        self.assertEqual(integrated["frozen_absolute_scale"], 25000.0)
        self.assertAlmostEqual(integrated["relative_error"], (1.0e-8 * 50.0 / 3.0) / 25000.0)

    def test_force_scale_detects_large_cd(self):
        self.assertFalse(_force_audit(load_row(raw_x=5001.0, unit_x=5001.0, integrated_x=5001.0 * 50.0 / 3.0))["passed"])

    def test_log_gate_passes_finite_end(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log"
            path.write_text("Courant Number mean: 0.1 max: 0.799\nEnd\n", encoding="utf-8")
            self.assertTrue(_log_audit([str(path)])["passed"])

    def test_log_gate_rejects_cfl_equal_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log"
            path.write_text("Courant Number mean: 0.1 max: 0.8\nEnd\n", encoding="utf-8")
            self.assertFalse(_log_audit([str(path)])["passed"])

    def test_log_gate_rejects_fatal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log"
            path.write_text("Courant Number mean: 0.1 max: 0.2\nFOAM FATAL ERROR\nEnd\n", encoding="utf-8")
            self.assertFalse(_log_audit([str(path)])["passed"])

    def test_parent_cylinder_center_matches_last_motion(self):
        center = cylinder_center(PARENT_CASE_ROOT / "slice_0000", "1.5075")
        self.assertAlmostEqual(center[0], 0.10412569394841097, places=13)
        self.assertAlmostEqual(center[1], 0.0003617471072853974, places=13)

    def test_endpoint_norm_uses_node_triplets(self):
        a = [0, 0, 0, 0, 0, 0, 3, 4, 0, 0, 0, 0]
        b = [0] * 12
        self.assertEqual(_endpoint_norm(a, b, 1.0), 5.0)


if __name__ == "__main__":
    unittest.main()
