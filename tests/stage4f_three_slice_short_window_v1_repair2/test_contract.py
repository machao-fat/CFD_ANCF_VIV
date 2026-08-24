import copy
import hashlib
import json
import math
import unittest

from src.coupling.stage4f_three_slice_short_window_v1_repair2.contract import (
    BRANCHES, END_TIME_S, START_TIME_S, THRESHOLDS,
    PARENT_CHECKPOINT, build_frozen_contract, scaled_relative, trapezoidal_impulse,
    validate_frozen_contract,
)
from src.coupling.multi_slice_mapping.mapping import sha256_file


class TestFrozenContract(unittest.TestCase):
    def setUp(self):
        self.contract = build_frozen_contract({
            "parent_checkpoint_sha256": sha256_file(PARENT_CHECKPOINT),
            "combined_sha256": "b" * 64,
        })

    @staticmethod
    def _rehash(contract):
        payload = copy.deepcopy(contract)
        payload.pop("contract_sha256", None)
        contract["contract_sha256"] = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")).hexdigest()

    def test_frozen_schedule(self):
        self.assertEqual(BRANCHES["A"]["segments"], [20])
        self.assertEqual(BRANCHES["B"]["segments"], [5, 15])
        self.assertEqual(BRANCHES["C"]["segments"], [40])
        for branch in self.contract["branches"].values():
            self.assertAlmostEqual(branch["times_s"][-1], END_TIME_S)

    def test_window_starts_from_parent_endpoint(self):
        self.assertEqual(START_TIME_S, 1.5075)
        self.assertAlmostEqual(END_TIME_S - START_TIME_S, .05)

    def test_runtime_identity_changes_with_dt(self):
        self.assertNotEqual(self.contract["branches"]["A"]["runtime_config"]["config_sha256"],
                            self.contract["branches"]["C"]["runtime_config"]["config_sha256"])

    def test_contract_hash_detects_mutation(self):
        changed = copy.deepcopy(self.contract)
        changed["thresholds"]["abs_cd_max"] = 11.0
        with self.assertRaises(ValueError):
            validate_frozen_contract(changed)

    def test_contract_rejects_schedule_mutation_even_with_rehashed_shape(self):
        changed = copy.deepcopy(self.contract)
        changed["branches"]["B"]["segments"] = [20]
        self._rehash(changed)
        with self.assertRaises(ValueError):
            validate_frozen_contract(changed)

    def test_contract_rejects_dt_mutation_even_with_rehashed_identity(self):
        changed = copy.deepcopy(self.contract)
        changed["branches"]["C"]["dt_s"] = 0.0025
        self._rehash(changed)
        with self.assertRaises(ValueError):
            validate_frozen_contract(changed)

    def test_contract_rejects_parent_path_mutation_even_with_rehashed_identity(self):
        changed = copy.deepcopy(self.contract)
        changed["parent_checkpoint"] = str(PARENT_CHECKPOINT.with_name("different.json"))
        self._rehash(changed)
        with self.assertRaises(ValueError):
            validate_frozen_contract(changed)

    def test_cfl_gate_is_strict(self):
        self.assertFalse(.8 < THRESHOLDS["cfl_strict_upper"])

    def test_scaled_relative_uses_absolute_scale(self):
        self.assertEqual(scaled_relative(1e-30, -1e-30, 1.0), 2e-30)

    def test_scaled_relative_rejects_nonfinite(self):
        with self.assertRaises(ValueError):
            scaled_relative(float("nan"), 0.0, 1.0)

    def test_trapezoidal_impulse(self):
        result = trapezoidal_impulse([0.0, .5, 1.0], [[0, 0, 0], [2, 4, 0], [0, 0, 0]])
        self.assertEqual(result, [1.0, 2.0, 0.0])

    def test_impulse_rejects_nonmonotone_time(self):
        with self.assertRaises(ValueError):
            trapezoidal_impulse([0.0, 0.0], [[0, 0, 0], [1, 1, 1]])

    def test_scope_exclusions_remain_frozen(self):
        self.assertIn("five_slice", self.contract["scope_exclusions"])
        self.assertIn("stage4e_physical_validation", self.contract["scope_exclusions"])


if __name__ == "__main__":
    unittest.main()
