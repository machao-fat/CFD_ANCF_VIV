import copy
import unittest

from src.coupling.stage4f_c_fixed_point_diagnostic_v1.contract import build_contract, validate_contract
from src.coupling.stage4f_c_fixed_point_diagnostic_v1.runner import _difference, _relax


class FixedPointDiagnosticTests(unittest.TestCase):
    def test_contract(self):
        validate_contract(build_contract("abc"))

    def test_contract_tamper(self):
        value = build_contract("abc"); value["max_iterations"] = 5
        with self.assertRaises(ValueError): validate_contract(value)

    def test_relaxation(self):
        self.assertEqual(_relax([[0, 2, 4]], [[4, 6, 8]], .25), [[1, 3, 5]])

    def test_difference(self):
        self.assertEqual(_difference([[1, 2, 3]], [[2, -1, 3]]), 3)


if __name__ == "__main__": unittest.main()
