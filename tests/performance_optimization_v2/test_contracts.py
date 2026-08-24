from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from coupling.performance_optimization_v2.contracts import BenchmarkContract, ContractError, validate_serialized_contract


class ContractTests(unittest.TestCase):
    def test_bounded_contract_hash_and_scope(self):
        root = Path("D:/CFD_ANCF_VIV")
        contract = BenchmarkContract("stage95", "run95", "case95", root / "runtime", root / "source.mat", 559, 2.2075, 2207500000)
        value = contract.to_dict(); validate_serialized_contract(value, root)
        self.assertEqual(value["steps"], 40)

    def test_scope_expansion_rejected(self):
        root = Path("D:/CFD_ANCF_VIV")
        contract = BenchmarkContract("stage95", "run95b", "case95b", root / "runtime", root / "source.mat", 559, 2.2075, 2207500000)
        value = contract.to_dict(); value["scope"]["no_e5c"] = False
        with self.assertRaises(ContractError): validate_serialized_contract(value, root)

    def test_factor_and_window_immutable(self):
        root = Path("D:/CFD_ANCF_VIV")
        with self.assertRaises(ContractError):
            BenchmarkContract("stage95", "run95c", "case95c", root / "runtime", root / "source.mat", 559, 2.2075, 2207500000, steps=39).validate(root)
