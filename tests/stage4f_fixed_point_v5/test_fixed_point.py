import unittest

from src.coupling.stage4f_fixed_point_v5.fixed_point import integrated_slice_loads
from src.coupling.stage4f_fixed_point_v5.settle import HOLD_END_S, MIGRATION_END_S, MIGRATION_STEPS, MIGRATION_WRITE_INTERVAL, TERMINAL_START_S, TERMINAL_STEPS


class TestFixedPointForceContract(unittest.TestCase):
    def test_applies_slice_length_exactly_once(self):
        rows = integrated_slice_loads([780.0, 3.0, 0.0])
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(rows[0][0], 780.0 * 50.0 / 3.0)
        self.assertEqual(rows[0], rows[1])

    def test_rejects_nonfinite_force(self):
        with self.assertRaises(ValueError):
            integrated_slice_loads([1.0, float("nan"), 0.0])

    def test_exact_geometry_hold_has_positive_duration(self):
        self.assertGreater(HOLD_END_S, MIGRATION_END_S)

    def test_migration_endpoint_is_on_the_write_cadence(self):
        self.assertEqual(MIGRATION_STEPS % MIGRATION_WRITE_INTERVAL, 0)

    def test_terminal_hold_is_a_positive_integer_number_of_steps(self):
        self.assertEqual(TERMINAL_STEPS, round((HOLD_END_S - TERMINAL_START_S) / .0025))
