import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "tools/stage373_convergence_evidence_audit_v1/audit_stage372.py"
SPEC = importlib.util.spec_from_file_location("stage373_audit", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class Stage373AuditTest(unittest.TestCase):
    def test_positive_peak_detector_rejects_negative_local_maxima(self) -> None:
        times = [float(index) for index in range(17)]
        values = [0.0, 1.0, 0.0, -1.0, -0.2, -1.0, 0.0, 1.1, 0.0, -1.0, -0.1, -1.0, 0.0, 0.9, 0.0, -1.0, 0.0]
        peaks = MODULE.positive_peaks(times, values, smoothing_s=1.0, minimum_separation_s=4.0)
        self.assertEqual([peak["time_s"] for peak in peaks], [7.0, 13.0])
        self.assertTrue(all(peak["value"] > 0.0 for peak in peaks))


    def test_relative_delta_uses_median_scale(self) -> None:
        self.assertLess(MODULE.relative_delta([0.16, 0.16, 0.1616]), 0.05)
        self.assertGreater(MODULE.relative_delta([0.24, 0.31, 0.35]), 0.05)
