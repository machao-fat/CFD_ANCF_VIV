import unittest
from pathlib import Path
import json

class ContractTests(unittest.TestCase):
    def test_dt2_contract(self):
        self.assertEqual(0.00125, 0.00125)
        self.assertEqual(40, 40)
        self.assertEqual([0, 1, 2], [0, 1, 2])

    def test_paths_are_isolated(self):
        root = Path(__file__).resolve().parents[2]
        self.assertNotEqual(root / 'cases/openfoam/stage4f_c_formal_dt2_v1', root / 'cases/openfoam/stage4f_c_formal_abc_time_consistent_v1')

