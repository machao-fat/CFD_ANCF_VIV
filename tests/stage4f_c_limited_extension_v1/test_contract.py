import copy
import unittest

from src.coupling.stage4f_c_limited_extension_v1.contract import build_contract, validate_contract


class LimitedExtensionContractTests(unittest.TestCase):
    def test_exact_frozen_contract_passes(self):
        contract = build_contract()
        validate_contract(contract)
        self.assertEqual(contract["continuous_global_steps"], list(range(10, 20)))
        self.assertEqual(contract["restart_global_steps"], list(range(15, 20)))
        self.assertEqual(contract["end_tick_ns"], 1_520_000_000)

    def test_threshold_or_timing_change_is_rejected(self):
        for key, value in (("final_max_abs_Cd", 10.1), ("dt_tick_ns", 624_999), ("end_tick_ns", 1_520_625_000)):
            changed = copy.deepcopy(build_contract())
            changed[key] = value
            with self.assertRaises(ValueError):
                validate_contract(changed)

    def test_restart_cannot_precede_continuous_success(self):
        contract = build_contract()
        self.assertTrue(contract["continuous_failure_forbids_restart"])
        self.assertEqual(contract["restart_parent_global_step"], 14)

    def test_forbidden_scope_is_explicit(self):
        forbidden = set(build_contract()["forbidden_scope"])
        self.assertTrue({"five_slice", "nine_slice", "long_time_VIV", "physical_validation"} <= forbidden)


if __name__ == "__main__":
    unittest.main()
