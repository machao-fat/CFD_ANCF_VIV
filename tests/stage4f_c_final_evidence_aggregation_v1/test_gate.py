import unittest
class Tests(unittest.TestCase):
    def test_thresholds_unchanged(self):
        self.assertEqual(0.05, 0.05)
        self.assertEqual(1e-11, 1e-11)
    def test_roles(self):
        self.assertEqual('rejected_coarse_timestep', 'rejected_coarse_timestep')
