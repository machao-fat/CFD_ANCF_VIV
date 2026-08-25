from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "184_cpp_worker_numerical_forensic_repair_v1"
TRACE = ROOT / "runtime" / "cpp_worker_numerical_forensic_repair_v1" / "stage184_forensic" / "step560_cpp_trace.txt"


def _points():
    rows = []
    for line in TRACE.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if fields and fields[0] == "point":
            # point e k xi x, then a(3), b(3), v(3), a2,v2,eps,
            # ga_b(3), gb_b(3), ga(3), gb(3), bga(12), cgb(12), contribution(12)
            rows.append((int(fields[1]), [float(value) for value in fields[3:]]))
    return rows


class ForensicTraceTests(unittest.TestCase):
    def test_forensic_trace_has_all_element_gauss_points(self):
        fixture = json.loads((ROOT / "runtime" / "cpp_worker_comprehensive_audit_repair_v1" /
                              "stage179_strict_dual" / "cpp_input_fixture_step559.json").read_text())
        points = _points()
        self.assertEqual(len(points), fixture["elements"] * fixture["gauss_order"])
        self.assertTrue(all(len(values) == 62 for _, values in points))

    def test_forensic_trace_contribution_is_finite(self):
        for _, values in _points():
            self.assertTrue(all(value == value and abs(value) != float("inf") for value in values))

    def test_gate_keeps_strict_status_closed(self):
        gate = json.loads((RESULTS / "independent_gate.json").read_text())
        self.assertTrue(gate["gate"].endswith("do_not_pass"))
        self.assertEqual(gate["C++_ANCF_NUMERICAL_CORE_STATUS"], "not_completed")
        self.assertEqual(gate["real_process_starts"], {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0})
        self.assertEqual(gate["owned_residual"], 0)
