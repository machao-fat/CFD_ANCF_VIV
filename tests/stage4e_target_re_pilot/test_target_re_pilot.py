import json
import math
import unittest
from pathlib import Path

from src.coupling.stage4e_target_re_pilot.case_generator import _control_dict, _p_field, _u_field
from src.coupling.stage4e_target_re_pilot.identity import (
    EXPECTED_CASE_ID,
    EXPECTED_FLOW_PROFILE_SHA256,
    EXPECTED_MANIFEST_SHA256,
    choose_representative_cases,
    load_formal_flow_profile,
    sha256_json,
)
from src.coupling.stage4e_target_re_pilot.pilot_runner import case_freshness


class TargetRePilotTests(unittest.TestCase):
    def test_parent_flow_profile_is_frozen_nine_slice_identity(self):
        profile = load_formal_flow_profile()
        self.assertEqual(profile["case_id"], EXPECTED_CASE_ID)
        self.assertEqual(profile["flow_profile_sha256"], EXPECTED_FLOW_PROFILE_SHA256)
        self.assertEqual(profile["slice_manifest_sha256"], EXPECTED_MANIFEST_SHA256)
        self.assertEqual(len(profile["slices"]), 9)

    def test_representative_selection_is_reproducible(self):
        profile = load_formal_flow_profile()
        first = choose_representative_cases(profile)
        second = choose_representative_cases(json.loads(json.dumps(profile)))
        self.assertEqual(first, second)
        self.assertEqual([first[name]["source_slice_id"] for name in ("low", "middle", "high")], [4, 6, 0])

    def test_re_uses_absolute_speed_and_frozen_units(self):
        cases = choose_representative_cases(load_formal_flow_profile())
        for item in cases.values():
            self.assertGreater(item["pilot_U_mps"], 0.0)
            self.assertAlmostEqual(item["Re"], item["pilot_U_mps"] * 0.02841 / 1e-6)
            self.assertTrue(math.isfinite(item["Re"]))

    def test_signed_source_speed_is_retained(self):
        cases = choose_representative_cases(load_formal_flow_profile())
        self.assertLess(cases["low"]["source_signed_U_global_mps"], 0.0)
        self.assertGreater(cases["high"]["source_signed_U_global_mps"], 0.0)
        self.assertEqual(cases["low"]["source_flow_sign"], -1)

    def test_positive_and_negative_velocity_fields_keep_internal_sign(self):
        positive = _u_field(0.2, 1)
        negative = _u_field(0.2, -1)
        self.assertIn("left { type fixedValue", positive)
        self.assertIn("right { type fixedValue", negative)
        self.assertIn("internalField uniform (0.2 0 0)", positive)
        self.assertIn("internalField uniform (-0.2 0 0)", negative)

    def test_pressure_role_follows_velocity_role(self):
        self.assertIn("left { type zeroGradient", _p_field(1))
        self.assertIn("right { type fixedValue", _p_field(1))
        self.assertIn("right { type zeroGradient", _p_field(-1))
        self.assertIn("left { type fixedValue", _p_field(-1))

    def test_force_dictionary_is_global_and_unrotated(self):
        text = _control_dict(0.4, 0.0005, 4.0, "kOmegaSST", 1, "baseline", "medium")
        self.assertIn("dragDir (1 0 0)", text)
        self.assertIn("liftDir (0 1 0)", text)
        self.assertIn("CofR (0 0 0)", text)
        self.assertNotIn("coordinateRotation", text)
        self.assertNotIn("rotationTensor", text)

    def test_case_freshness_rejects_existing_solver_artifacts(self):
        case = Path(__file__).resolve().parents[2] / "openfoam" / "stage4e_target_re_fixed_cylinder" / "not_a_case"
        # The helper must not silently report a missing case as a fresh generated case.
        self.assertFalse(case_freshness(case).get("passed", True))

    def test_canonical_hash_is_order_independent(self):
        self.assertEqual(sha256_json({"b": 2, "a": 1}), sha256_json({"a": 1, "b": 2}))

    def test_nan_and_inf_are_not_accepted(self):
        from src.coupling.stage4e_target_re_pilot.identity import canonical_json_bytes
        with self.assertRaises(ValueError):
            canonical_json_bytes({"bad": float("nan")})
        with self.assertRaises(ValueError):
            canonical_json_bytes({"bad": float("inf")})

    def test_pilot_does_not_claim_official_config_hash(self):
        profile = load_formal_flow_profile()
        self.assertNotEqual(profile["flow_profile_sha256"], "config_sha256")


if __name__ == "__main__":
    unittest.main()
