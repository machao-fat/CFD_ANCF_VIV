import unittest
from src.coupling.stage4f_d_e5_staged_entry_design_v1.design import candidate,status
class E5Tests(unittest.TestCase):
    def test_candidates(self):
        self.assertEqual(candidate(.05)['steps'],40); self.assertEqual(candidate(.1)['blocks'],8)
    def test_fail_closed(self):
        self.assertEqual(status(14,500,3,.01,1),'not_evaluable_insufficient_cycles')
        self.assertEqual(status(20,500,3,.06,1),'not_evaluable_frequency_disagreement')
        self.assertEqual(status(20,500,3,.01,0),'not_evaluable_low_amplitude')
    def test_valid_requires_all(self):
        self.assertEqual(status(15,300,3,.05,1),'evaluable_by_frozen_contract')
