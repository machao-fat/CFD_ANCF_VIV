from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class Stage363CandidateTests(unittest.TestCase):
    def test_candidate_is_offline_and_binds_80s_source(self) -> None:
        root = Path(__file__).resolve().parents[2]
        script = root / "tools/stage363_restart_coherent_candidate_v1/prepare.py"
        candidate = root / "runtime/stage363_restart_coherent_candidate_v1/candidate_manifest.json"
        if not candidate.is_file():
            result = subprocess.run([sys.executable, str(script)], cwd=root, check=True, capture_output=True, text=True)
            self.assertIn('"gate": "pass"', result.stdout)
        gate = json.loads((root / "results/363_restart_coherent_candidate_v1/stage4f_d_restart_coherent_candidate_v1_gate.json").read_text(encoding="utf-8"))
        self.assertTrue(gate["candidate_only"])
        self.assertTrue(gate["source_runtime_read_only"])
        self.assertEqual(gate["source_global_step"], 16000)
        self.assertEqual(gate["source_time_s"], 80.0)
        self.assertEqual(gate["real_process_starts"], {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0})
        self.assertTrue(gate["repair_contract"]["preserve_U_cylinder_boundary_from_source"])
        self.assertTrue(gate["repair_contract"]["require_first_step_mesh_quality_audit"])


if __name__ == "__main__":
    unittest.main()
