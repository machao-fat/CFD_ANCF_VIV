import unittest
from coupling.stage4f_d_e5_staged_segment75 import runner

class TestStage75Contract(unittest.TestCase):
    def test_fresh_segment_identity(self):
        runner.configure()
        self.assertEqual(runner.RUN_ID, "stage75_e5_candidate_1_attempt6")
        self.assertTrue(str(runner.RESULT).endswith("75_stage4f_d_e5_candidate_1_attempt6"))
        self.assertTrue(runner.SOURCE.name.startswith("checkpoint_step00000559_"))

if __name__ == "__main__":
    unittest.main()
