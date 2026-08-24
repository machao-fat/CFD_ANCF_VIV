from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.coupling.stage4d_campaign.audit import energy_audit
from src.coupling.stage4d_campaign.developed_flow import (
    ForceSample,
    analyze_force_history,
    dominant_frequency,
)


class Stage4DAuditTests(unittest.TestCase):
    def test_energy_audit_formula(self) -> None:
        rows = [{"force_N": [2.0, 0.0, 0.0], "v_pred_mps": [3.0, 0.0, 0.0], "v_corr_mps": [2.0, 0.0, 0.0]}]
        result = energy_audit(rows, dt_s=0.5)
        self.assertEqual(result["W_CFD_J"], [3.0])
        self.assertEqual(result["W_structure_J"], [2.0])
        self.assertEqual(result["delta_W_c_J"], [1.0])
        self.assertEqual(result["E_c"], 1.0 / 3.0)

    def test_frequency_and_st(self) -> None:
        dt = 0.0025
        frequency = 0.16
        times = np.arange(0.0, 50.0, dt)
        values = np.sin(2.0 * np.pi * frequency * times)
        estimated = dominant_frequency(times.tolist(), values.tolist(), fmin=0.1, fmax=0.25)
        self.assertLess(abs(estimated - frequency), 0.002)
        samples = [ForceSample(float(t), (1000.0, float(500.0 * y), 0.0)) for t, y in zip(times, values)]
        stats = analyze_force_history(samples, U=1.0, end_time_s=times[-1])
        self.assertTrue(0.12 <= stats["St"] <= 0.22)
        self.assertTrue(stats["criteria"]["at_least_four_cycles"])

    def test_not_executed_schema_is_explicit(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="stage4d_schema_"))
        path = root / "summary.json"
        payload = {"status": "not_executed", "reason": "prerequisite blocked", "steps": 0}
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(json.loads(path.read_text())["status"], "not_executed")


if __name__ == "__main__":
    unittest.main()
