import importlib.util
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "src/coupling/stage382_observables_v1/metrics.py"
spec = importlib.util.spec_from_file_location("stage382_metrics", SCRIPT)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Stage382ObservableTests(unittest.TestCase):
    def contract(self):
        return {
            "schema_version": 1, "run_id": "r", "case_id": "c",
            "slice_ids": ["slice_0000", "slice_0001", "slice_0002"],
            "sample_interval_s": 0.05, "window_interval_s": 10.0,
            "force_fields": ["force_y"], "displacement_fields": ["displacement_y"],
            "missing_value_policy": "fail_closed_no_interpolation", "formal_gate_unchanged": True,
        }

    def test_contract_and_metrics(self):
        self.assertEqual(m.validate_contract(self.contract())["status"], "pass")
        t = [i * 0.05 for i in range(400)]
        forces = {f"slice_{i:04d}": [math.sin(x + i * 0.2) for x in t] for i in range(3)}
        result = m.compute_window_metrics(t, forces, [0.2 * math.sin(x) for x in t], start_time_s=0.0, end_time_s=10.0)
        self.assertEqual(result["sample_count"], 200)
        self.assertIn("slice_0000__slice_0001", result["phase"])
        self.assertGreater(result["weighted_force"]["rms"], 0.0)

    def test_missing_stream_fails_closed(self):
        t = [0.0, 0.05, 0.1]
        with self.assertRaises(m.ObservationContractError):
            m.compute_window_metrics(t, {"slice_0000": [1, 2, 3], "slice_0001": [1, 2, 3], "slice_0002": [1, 2]}, [1, 2, 3], start_time_s=0.0, end_time_s=0.1)

    def test_phase_lag_is_reported(self):
        t = [i * 0.05 for i in range(100)]
        left = [math.sin(x) for x in t]
        right = [math.sin(x - 0.1) for x in t]
        out = m.compute_window_metrics(t, {"slice_0000": left, "slice_0001": right, "slice_0002": left}, left, start_time_s=0.0, end_time_s=4.95)
        self.assertIn("lag_time_s", out["phase"]["slice_0000__slice_0001"])


if __name__ == "__main__":
    unittest.main()
