import importlib.util
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/stage380_convergence_audit_repair_v1/audit_merged.py"
spec = importlib.util.spec_from_file_location("stage380_audit", SCRIPT)
assert spec and spec.loader
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class Stage380AuditTests(unittest.TestCase):
    def test_negative_local_maxima_are_ignored(self):
        times = [float(i) for i in range(0, 40)]
        values = [0.5 * math.sin(i / 3.0) for i in range(0, 40)]
        peaks = audit.positive_peaks(times, values, smoothing_s=0.0, minimum_separation_s=4.0)
        self.assertTrue(all(value > 0 for _, value in peaks))

    def test_missing_quality_is_not_interpolated(self):
        result = audit.audit_quality(Path("Z:/does-not-exist"), 0.0, 1.0)
        self.assertFalse(result["slice_0000"]["complete"])
        self.assertGreater(result["slice_0000"]["missing_fields"]["courant_max"], 0)

    def test_declared_sampling_interval(self):
        self.assertEqual(audit.DT, 0.005)
        self.assertEqual(audit.SAMPLE_EVERY_STEPS, 10)
        self.assertEqual(audit.QUALITY_FIELDS[-1], "iterations_max")


if __name__ == "__main__":
    unittest.main()
