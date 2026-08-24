import unittest
from src.coupling.stage4f_c_restart_vs_continuous_forensic_v1.forensic import maxdiff
class Tests(unittest.TestCase):
    def test_equal_state(self): self.assertEqual(maxdiff([1,2],[1,2])['relative'],0)
    def test_length_mismatch(self): self.assertEqual(maxdiff([1],[1,2])['relative'],float('inf'))
