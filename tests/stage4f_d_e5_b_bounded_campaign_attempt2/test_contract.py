import unittest
from coupling.stage4f_d_e5_b_bounded_campaign_attempt2 import runner


class Attempt2ContractTests(unittest.TestCase):
    def test_isolated_paths_and_frozen_window(self):
        runner.configure()
        contract = runner.base.execution_contract()
        self.assertEqual(contract["run_id"], runner.RUN_ID)
        self.assertEqual(contract["first_target_step"], 520)
        self.assertEqual(contract["last_target_step"], 559)
        self.assertEqual(contract["authorized_steps"], 40)
        self.assertTrue(contract["no_same_runtime_retry"])
        self.assertTrue(contract["source"]["qualified"])
        self.assertIn("attempt2", str(runner.base.RESULT))


if __name__ == "__main__":
    unittest.main()
