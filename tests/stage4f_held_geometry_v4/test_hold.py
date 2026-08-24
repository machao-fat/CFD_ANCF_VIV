import unittest
from src.coupling.stage4f_held_geometry_v4.hold import HOLD_END_S, HOLD_START_S, HOLD_STEPS


class TestHeldGeometryContract(unittest.TestCase):
    def test_hold_has_positive_duration_and_no_motion_steps_are_required(self):
        self.assertGreater(HOLD_END_S, HOLD_START_S)
        self.assertEqual(HOLD_STEPS, round((HOLD_END_S - HOLD_START_S) / .0025))
