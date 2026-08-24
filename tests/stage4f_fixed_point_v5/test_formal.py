import unittest
from src.coupling.stage4f_fixed_point_v5.formal import DT_S, START_TIME_S, STEPS

class TestFormalContract(unittest.TestCase):
    def test_bounded_three_step_contract(self):
        self.assertEqual(STEPS, 3)
        self.assertGreater(START_TIME_S, 0.0)
        self.assertGreater(DT_S, 0.0)

    def test_explicit_preflight_has_no_restart_steps(self):
        self.assertEqual(STEPS, 3)
