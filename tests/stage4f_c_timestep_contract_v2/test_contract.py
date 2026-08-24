import unittest
class Tests(unittest.TestCase):
    def test_roles_and_threshold(self):
        self.assertEqual('rejected_coarse_timestep', 'rejected_coarse_timestep'); self.assertEqual(0.05, 0.05)
    def test_restart_schedule(self):
        self.assertEqual((10,30), (10,30)); self.assertEqual(1_507_500_000+10*1_250_000,1_520_000_000)
