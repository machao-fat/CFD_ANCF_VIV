from __future__ import annotations

import unittest

from coupling.cpp_worker_confirm_v1.coordinator import _fixture
from coupling.cpp_worker_confirm_v1.numerical_contract import (
    ANCF_GAUSS_ORDER, ANCF_MAX_NEWTON, normalize_model,
)


class NumericalContractTests(unittest.TestCase):
    def test_real_confirm_normalizes_fixture_only_at_contract_boundary(self):
        model, *_ = _fixture()
        normalized = normalize_model(model)
        self.assertEqual((normalized.gauss_order, normalized.max_newton), (3, 40))
        self.assertEqual((model.gauss_order, model.max_newton), (5, 50))
        for field in ("length_m", "diameter_m", "inner_diameter_m", "top_tension_N",
                      "youngs_modulus_Pa", "material_density", "fluid_density", "gravity",
                      "beta", "gamma", "newton_tolerance", "damping_alpha", "damping_beta",
                      "slice_positions_m"):
            self.assertEqual(getattr(normalized, field), getattr(model, field), field)

    def test_contract_constants_are_explicit(self):
        self.assertEqual(ANCF_GAUSS_ORDER, 3)
        self.assertEqual(ANCF_MAX_NEWTON, 40)


if __name__ == "__main__":
    unittest.main()
