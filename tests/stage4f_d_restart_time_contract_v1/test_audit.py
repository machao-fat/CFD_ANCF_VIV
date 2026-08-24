import unittest
from coupling.stage4f_d_restart_time_contract_v1.audit import run

class TestRestartTimeContract(unittest.TestCase):
    def test_offline_contract(self):
        value = run()
        self.assertEqual(value["mode"], "offline_only")
        self.assertEqual(value["real_processes_started"], 0)
        self.assertIn("bridge step is case-local and separately mapped from global step", value["required_invariants"])

if __name__ == "__main__": unittest.main()
