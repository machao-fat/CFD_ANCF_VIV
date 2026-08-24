import unittest
from coupling.stage4f_d_e5_b_attempt2_closeout_v1.audit import run

class TestCloseout(unittest.TestCase):
    def test_partial_attempt_is_closed_fail_closed(self):
        a = run()
        self.assertEqual(a["gate"], "do_not_pass")
        self.assertEqual(a["completed_blocks"], 3)
        self.assertEqual(a["committed_steps"], 30)
        self.assertEqual((a["step_min"], a["step_max"]), (520, 549))
        self.assertEqual(a["checkpoints"], 32)
        self.assertTrue(a["partial_runtime_excluded"])
