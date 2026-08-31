from pathlib import Path
import json
import subprocess
import sys
import unittest


class Stage366CandidateTests(unittest.TestCase):
    def test_candidate_binds_lag1_state_to_80_field(self):
        root = Path(__file__).resolve().parents[2]
        script = root / "tools/stage366_restart_lag1_coherent_candidate_v1/prepare.py"
        manifest = root / "runtime/stage366_restart_lag1_coherent_candidate_v1/candidate_manifest.json"
        if not manifest.is_file():
            completed = subprocess.run([sys.executable, str(script)], cwd=root, check=True, capture_output=True, text=True)
            self.assertIn('"gate": "pass"', completed.stdout)
        gate = json.loads((root / "results/366_restart_lag1_coherent_candidate_v1/stage4f_d_restart_lag1_coherent_candidate_v1_gate.json").read_text(encoding="utf-8"))
        self.assertTrue(gate["candidate_only"])
        self.assertEqual(gate["field_time_s"], 80.0)
        self.assertEqual(gate["structure_state_time_s"], 79.995)
        self.assertTrue(gate["checks"]["all_three_bootstrap_geometries_aligned"])
        self.assertTrue(gate["checks"]["all_three_source_U_boundaries_nonuniform"])
        self.assertEqual(gate["real_process_starts"], {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0})


if __name__ == "__main__":
    unittest.main()
