import unittest
from src.coupling.stage4f_d_statistics_entry_review_v1.review import evaluate

class StatisticsContractTests(unittest.TestCase):
    def test_insufficient_cycles_fail_closed(self):
        self.assertFalse(evaluate(cycles=14, samples=500, windows=3, relative_difference=0, amplitude=1)["formal_frequency"])
    def test_low_amplitude_fail_closed(self):
        self.assertEqual(evaluate(cycles=20, samples=500, windows=3, relative_difference=0, amplitude=0)["status"], "not_evaluable_low_amplitude")
    def test_window_and_frequency_mismatch_fail_closed(self):
        self.assertFalse(evaluate(cycles=20, samples=500, windows=2, relative_difference=.01, amplitude=1)["formal_frequency"])
        self.assertFalse(evaluate(cycles=20, samples=500, windows=3, relative_difference=.051, amplitude=1)["formal_frequency"])
    def test_valid_contract(self):
        self.assertTrue(evaluate(cycles=20, samples=500, windows=3, relative_difference=.05, amplitude=1)["formal_frequency"])

if __name__ == '__main__':
    unittest.main()
