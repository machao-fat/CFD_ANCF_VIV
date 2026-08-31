from pathlib import Path
import unittest


class Stage364LauncherTests(unittest.TestCase):
    def test_binds_final_state_at_80s_and_forbids_continuation(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / "tools/stage364_restart_coherent_smoke_v1/run_stage364.py").read_text(encoding="utf-8")
        self.assertIn('"final_q": source["final_q"]', text)
        self.assertIn('source_time=80.0', text)
        self.assertIn('"continuation_started": False', text)
        self.assertIn('STAGE4F_D_RESTART_COHERENT_SMOKE_V1_GATE', text)


if __name__ == "__main__":
    unittest.main()
