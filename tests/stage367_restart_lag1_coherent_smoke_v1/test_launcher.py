from pathlib import Path
import json
import unittest


class Stage367LauncherTests(unittest.TestCase):
    def test_fresh_lag1_smoke_contract(self):
        root = Path(__file__).resolve().parents[2]
        source = (root / "tools/stage367_restart_lag1_coherent_smoke_v1/run_stage367.py").read_text(encoding="utf-8")
        self.assertIn("run367_restart_lag1_coherent_smoke_v1", source)
        self.assertIn("case367_restart_lag1_coherent_smoke_v1", source)
        self.assertIn("results/350_restart_bootstrap_velocity_v1/restart_bootstrap_state.json", source)
        self.assertIn("STAGE4F_D_RESTART_LAG1_COHERENT_SMOKE_V1_GATE", source)
        self.assertIn("steps=40", source)
        self.assertEqual(source.count("impl.launch("), 1)

    def test_candidate_gate_is_passing_and_zero_process_offline(self):
        root = Path(__file__).resolve().parents[2]
        gate = json.loads((root / "results/366_restart_lag1_coherent_candidate_v1/stage4f_d_restart_lag1_coherent_candidate_v1_gate.json").read_text(encoding="utf-8"))
        self.assertEqual(gate["status"], "pass")
        self.assertEqual(gate["real_process_starts"], {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0})


if __name__ == "__main__":
    unittest.main()
