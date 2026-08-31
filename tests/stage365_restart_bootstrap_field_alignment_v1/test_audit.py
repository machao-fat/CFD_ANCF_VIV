from pathlib import Path
import json
import subprocess
import sys
import unittest


class Stage365AlignmentTests(unittest.TestCase):
    def test_lag1_bootstrap_matches_80_field(self):
        root = Path(__file__).resolve().parents[2]
        script = root / "tools/stage365_restart_bootstrap_field_alignment_v1/audit.py"
        result = root / "results/365_restart_bootstrap_field_alignment_v1/stage4f_d_restart_bootstrap_field_alignment_v1_gate.json"
        if not result.is_file():
            completed = subprocess.run([sys.executable, str(script)], cwd=root, check=True, capture_output=True, text=True)
            self.assertIn('"gate": "pass"', completed.stdout)
        gate = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(gate["status"], "pass")
        self.assertTrue(gate["comparison"]["bootstrap_matches_field_geometry"])
        self.assertFalse(gate["comparison"]["final_state_matches_field_geometry"])
        self.assertEqual(gate["real_process_starts"], {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0})
        self.assertTrue(all(row["boundary_displacement_error_max_m"] < 1e-12 for row in gate["slices"]))


if __name__ == "__main__":
    unittest.main()
