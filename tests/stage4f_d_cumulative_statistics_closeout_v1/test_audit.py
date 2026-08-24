import unittest
from src.coupling.stage4f_d_cumulative_statistics_closeout_v1.audit import validate_windows,status
class CloseoutTests(unittest.TestCase):
    def test_continuity_and_gap(self):
        self.assertTrue(validate_windows([{'start_tick':1,'end_tick':2},{'start_tick':2,'end_tick':3}]))
        self.assertFalse(validate_windows([{'start_tick':1,'end_tick':2},{'start_tick':4,'end_tick':5}]))
    def test_excluded_windows_do_not_bridge(self):
        self.assertTrue(validate_windows([{'start_tick':1,'end_tick':2},{'excluded':True,'start_tick':99,'end_tick':100}]))
    def test_fail_closed_statistics(self):
        self.assertEqual(status(14,500,3,.01,1),'not_evaluable_insufficient_cycles')
        self.assertEqual(status(20,500,3,.06,1),'not_evaluable_frequency_disagreement')
        self.assertEqual(status(20,500,3,.01,0),'not_evaluable_low_amplitude')
    def test_valid_contract(self):
        self.assertEqual(status(15,300,3,.05,1),'evaluable_by_frozen_contract')
