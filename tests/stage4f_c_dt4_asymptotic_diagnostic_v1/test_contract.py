import unittest
from src.coupling.stage4f_c_dt4_asymptotic_diagnostic_v1.runner import RUN_ID

class Tests(unittest.TestCase):
    def test_frozen_dt4(self):
        self.assertEqual(RUN_ID, 'stage36_dt4_diagnostic_v1')
        self.assertEqual(0.000625, 0.000625)
        self.assertEqual(80, 80)

    def test_ticks(self):
        self.assertEqual(1507500000 + 80 * 625000, 1557500000)
