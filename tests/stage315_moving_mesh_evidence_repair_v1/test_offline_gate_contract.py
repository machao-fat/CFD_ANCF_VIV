from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "results/315_moving_mesh_evidence_repair_v1/stage4f_d_moving_mesh_adapter_read_path_repair_v1_gate.json"


class OfflineGateContractTests(unittest.TestCase):
    def test_gate_is_explicitly_offline_and_zero_process(self) -> None:
        if not GATE.exists():
            self.skipTest("run_offline_gate.py has not generated the evidence yet")
        data = json.loads(GATE.read_text(encoding="utf-8"))
        self.assertEqual(data["scope"], "offline adapter source/build audit only; no real solver launch")
        self.assertEqual(data["real_process_starts"], {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0})
        self.assertEqual(data["owned_residual"], 0)
        self.assertIn("new fresh short moving-mesh", data["qualification"])


if __name__ == "__main__":
    unittest.main()
