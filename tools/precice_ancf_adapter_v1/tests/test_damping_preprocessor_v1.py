from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tools.precice_ancf_adapter_v1.ancf_case_config_v1 import CaseConfig  # noqa: E402
from tools.precice_ancf_adapter_v1.ancf_damping_preprocessor_v1 import (  # noqa: E402
    RayleighPreprocessorError,
    canonical_damping_block,
    preprocess_damping,
)


FIXTURE = Path(__file__).with_name("fixtures") / "generic_case_config_v1.json"


def _modal_targets(alpha: float, beta: float, frequencies: tuple[float, float]):
    return [
        {
            "frequency_hz": frequency,
            "zeta": alpha / (2.0 * (2.0 * math.pi * frequency))
            + beta * (2.0 * math.pi * frequency) / 2.0,
        }
        for frequency in frequencies
    ]


class RayleighPreprocessorTests(unittest.TestCase):
    def test_explicit_pass_through_and_production_identity(self):
        spec = {"mode": "explicit_coefficients", "alpha_mass_per_s": 0.25,
                "beta_stiffness_s": 1.0e-7}
        result = preprocess_damping(spec)
        self.assertEqual(result["input_mode"], "explicit_coefficients")
        self.assertEqual(result["canonical_damping"]["mode"], "rayleigh_coefficients")
        self.assertEqual(result["alpha_mass_per_s"], 0.25)
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        raw["damping"] = result["canonical_damping"]
        resolved = CaseConfig.from_mapping(raw, base_dir=FIXTURE.parent)
        direct = copy.deepcopy(raw)
        direct["damping"] = {
            **result["canonical_damping"],
            "alpha_mass_per_s": 0.25,
            "beta_stiffness_s": 1.0e-7,
        }
        direct_config = CaseConfig.from_mapping(direct, base_dir=FIXTURE.parent)
        self.assertEqual(resolved.damping_identity_sha256,
                         direct_config.damping_identity_sha256)

    def test_modal_pair_round_trip_and_target_reconstruction(self):
        alpha, beta = 0.25, 1.0e-7
        result = preprocess_damping({"mode": "modal_pair",
                                     "targets": _modal_targets(alpha, beta, (1.5, 4.0))})
        self.assertAlmostEqual(result["alpha_mass_per_s"], alpha, places=12)
        self.assertAlmostEqual(result["beta_stiffness_s"], beta, places=16)
        for target in result["target_reconstruction"]:
            self.assertLessEqual(target["absolute_error"], 1.0e-15)

    def test_modal_pair_multiple_round_trips(self):
        for alpha, beta, frequencies in (
            (0.1, 2.0e-8, (0.75, 2.5)),
            (0.8, 4.0e-7, (3.0, 8.0)),
        ):
            with self.subTest(alpha=alpha, beta=beta, frequencies=frequencies):
                result = preprocess_damping({
                    "mode": "modal_pair",
                    "targets": _modal_targets(alpha, beta, frequencies),
                })
                self.assertAlmostEqual(result["alpha_mass_per_s"], alpha, places=12)
                self.assertAlmostEqual(result["beta_stiffness_s"], beta, places=15)

    def test_modal_pair_order_invariance(self):
        targets = _modal_targets(0.4, 2.0e-7, (1.0, 3.5))
        first = preprocess_damping({"mode": "modal_pair", "targets": targets})
        second = preprocess_damping({"mode": "modal_pair", "targets": list(reversed(targets))})
        self.assertAlmostEqual(first["alpha_mass_per_s"], second["alpha_mass_per_s"], places=14)
        self.assertAlmostEqual(first["beta_stiffness_s"], second["beta_stiffness_s"], places=18)
        self.assertEqual(first["damping_preprocess_identity_sha256"],
                         second["damping_preprocess_identity_sha256"])

    def test_single_target_assumptions(self):
        mass = preprocess_damping({"mode": "mass_proportional_single_target",
                                   "frequency_hz": 2.0, "zeta": 0.01})
        omega = 4.0 * math.pi
        self.assertAlmostEqual(mass["alpha_mass_per_s"], 2.0 * 0.01 * omega)
        self.assertEqual(mass["beta_stiffness_s"], 0.0)
        self.assertEqual(mass["assumption"], "mass_proportional_only")
        stiffness = preprocess_damping({"mode": "stiffness_proportional_single_target",
                                        "frequency_hz": 2.0, "zeta": 0.01})
        self.assertEqual(stiffness["alpha_mass_per_s"], 0.0)
        self.assertAlmostEqual(stiffness["beta_stiffness_s"], 2.0 * 0.01 / omega)
        self.assertEqual(stiffness["assumption"], "stiffness_proportional_only")

    def test_negative_modal_coefficient_rejected(self):
        with self.assertRaisesRegex(RayleighPreprocessorError,
                                     "RAYLEIGH_MODAL_PAIR_NEGATIVE_COEFFICIENT"):
            preprocess_damping({"mode": "modal_pair", "targets": [
                {"frequency_hz": 1.0, "zeta": 0.02},
                {"frequency_hz": 2.0, "zeta": 0.001},
            ]})

    def test_invalid_inputs(self):
        invalid = [
            {"mode": "unknown"},
            {"mode": "explicit_coefficients", "alpha_mass_per_s": -1.0,
             "beta_stiffness_s": 0.0},
            {"mode": "explicit_coefficients", "alpha_mass_per_s": math.inf,
             "beta_stiffness_s": 0.0},
            {"mode": "modal_pair", "targets": [{"frequency_hz": 1.0, "zeta": 0.01}]},
            {"mode": "modal_pair", "targets": [
                {"frequency_hz": 1.0, "zeta": 0.01},
                {"frequency_hz": 2.0, "zeta": 0.01},
                {"frequency_hz": 3.0, "zeta": 0.01},
            ]},
            {"mode": "modal_pair", "targets": [
                {"frequency_hz": 1.0, "zeta": 0.01},
                {"frequency_hz": 1.0 + 1.0e-14, "zeta": 0.01},
            ]},
            {"mode": "mass_proportional_single_target", "zeta": 0.01},
            {"mode": "stiffness_proportional_single_target", "frequency_hz": 1.0,
             "zeta": -0.01},
            {"mode": "modal_pair", "targets": [
                {"frequency_hz": 1.0, "zeta": 0.01},
                {"frequency_hz": 2.0, "zeta": math.nan},
            ]},
        ]
        for spec in invalid:
            with self.subTest(spec=spec):
                with self.assertRaises(RayleighPreprocessorError):
                    preprocess_damping(spec)

    def test_frequency_and_zeta_domain_rejections(self):
        for frequency in (0.0, -1.0, math.nan, math.inf):
            with self.subTest(frequency=frequency):
                with self.assertRaises(RayleighPreprocessorError):
                    preprocess_damping({
                        "mode": "mass_proportional_single_target",
                        "frequency_hz": frequency,
                        "zeta": 0.01,
                    })
        for zeta in (-0.01, math.nan, math.inf):
            with self.subTest(zeta=zeta):
                with self.assertRaises(RayleighPreprocessorError):
                    preprocess_damping({
                        "mode": "stiffness_proportional_single_target",
                        "frequency_hz": 1.0,
                        "zeta": zeta,
                    })

    def test_zeta_without_frequency_has_explicit_error(self):
        with self.assertRaisesRegex(RayleighPreprocessorError,
                                     "DAMPING_TARGET_FREQUENCY_REQUIRED"):
            preprocess_damping({"mode": "mass_proportional_single_target", "zeta": 0.01})

    def test_canonical_block_is_production_compatible(self):
        block = canonical_damping_block({"mode": "modal_pair", "targets": [
            {"frequency_hz": 1.0, "zeta": 0.004},
            {"frequency_hz": 3.0, "zeta": 0.012},
        ]})
        self.assertEqual(block["mode"], "rayleigh_coefficients")
        self.assertEqual(block["reference_state"], "dynamic_initial")
        self.assertGreaterEqual(block["alpha_mass_per_s"], 0.0)
        self.assertGreaterEqual(block["beta_stiffness_s"], 0.0)


if __name__ == "__main__":
    unittest.main()
