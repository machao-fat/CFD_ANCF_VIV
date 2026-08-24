import unittest
from src.coupling.stage4f_d_e4_entry_design_v1.design import projection, statistical_status

class E4DesignTests(unittest.TestCase):
    def test_candidate_costs(self):
        self.assertEqual(projection(.1)["steps"], 80)
        self.assertEqual(projection(.2)["blocks"], 16)
        self.assertEqual(projection(.3)["steps"], 240)
    def test_fail_closed_statistics(self):
        self.assertEqual(statistical_status(14, 500, 3, 0, 1), "not_evaluable_insufficient_cycles")
        self.assertEqual(statistical_status(20, 500, 3, .051, 1), "not_evaluable_frequency_disagreement")
        self.assertEqual(statistical_status(20, 500, 3, .01, 0), "not_evaluable_low_amplitude")
    def test_valid_requires_all_gates(self):
        self.assertEqual(statistical_status(15, 300, 3, .05, 1), "evaluable_by_frozen_contract")

if __name__ == '__main__': unittest.main()
