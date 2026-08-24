import unittest
from src.coupling.stage4f_d_e4_cumulative_review_v2.review import timeline_ok,evaluate
class ReviewTests(unittest.TestCase):
    def test_gap_duplicate_rejected(self):
        self.assertTrue(timeline_ok([{'end_tick':2},{'start_tick':2,'end_tick':3}]))
        self.assertFalse(timeline_ok([{'end_tick':2},{'start_tick':4,'end_tick':5}]))
    def test_fail_closed_statistics(self):
        self.assertEqual(evaluate(14,500,3,.01,1),'not_evaluable_insufficient_cycles')
        self.assertEqual(evaluate(20,500,3,.06,1),'not_evaluable_frequency_disagreement')
        self.assertEqual(evaluate(20,500,3,.01,0),'not_evaluable_low_amplitude')
    def test_global_steps_do_not_equal_cycles(self):
        self.assertNotEqual(400,15)
    def test_valid_contract(self):
        self.assertEqual(evaluate(15,300,3,.05,1),'evaluable_by_frozen_contract')
