import json
import tempfile
import unittest
from pathlib import Path

from src.coupling.stage4f_equilibrated_startup_v3.equilibrium import RECONCILIATION_STEPS, SLICE_LENGTH_M, mean_dynamic_hot_start_loads, smoothstep


class TestEquilibriumContract(unittest.TestCase):
    def test_hot_start_force_is_integrated_once_per_slice(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "audit.json"
            path.write_text(json.dumps({"hot_start":{"steps":[{"openfoam_force_N":[1800.0, 2.0, 0.0]}]}}), encoding="utf-8")
            rows = mean_dynamic_hot_start_loads(path)
            self.assertEqual(rows, [[1800.0 * SLICE_LENGTH_M, 2.0 * SLICE_LENGTH_M, 0.0]] * 3)

    def test_real_contract_has_three_integrated_loads(self):
        rows = mean_dynamic_hot_start_loads()
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(rows[0][0] / SLICE_LENGTH_M, 1822.671515868934)

    def test_reconciliation_ramp_is_endpoint_exact_and_bounded(self):
        self.assertEqual(smoothstep(0.0), 0.0)
        self.assertEqual(smoothstep(1.0), 1.0)
        values = [smoothstep(k / RECONCILIATION_STEPS) for k in range(RECONCILIATION_STEPS + 1)]
        self.assertTrue(all(b >= a for a, b in zip(values, values[1:])))
        self.assertLess(max(b - a for a, b in zip(values, values[1:])), 0.008)
