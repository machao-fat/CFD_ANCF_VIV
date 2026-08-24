import math
import unittest

from src.coupling.strong_coupling.aitken import AitkenRelaxer


class AitkenModuleTests(unittest.TestCase):
    def test_bounded_and_reduces_scalar_fixed_point_residual(self):
        controller = AitkenRelaxer(omega=0.2, omega_min=0.05, omega_max=0.8)
        x = 0.0
        target = 1.0
        errors = []
        for _ in range(12):
            raw = 0.5*x + 0.5*target
            x = controller.relax((x,), (raw,))[0]
            errors.append(abs(target-x))
            self.assertTrue(0.05 <= controller.omega <= 0.8)
        self.assertTrue(all(math.isfinite(e) for e in errors))
        self.assertLess(errors[-1], errors[0])

    def test_rejects_nonfinite_residual(self):
        controller = AitkenRelaxer()
        with self.assertRaises(ValueError):
            controller.update((float("nan"),))

    def test_uses_previous_residual_in_dynamic_update(self):
        controller = AitkenRelaxer(omega=0.2, omega_min=0.01, omega_max=10.0)
        x = 0.0
        raw = 0.5*x + 0.5
        x = controller.relax((x,), (raw,))[0]
        raw = 0.5*x + 0.5
        x = controller.relax((x,), (raw,))[0]
        self.assertAlmostEqual(controller.omega, 2.0, places=12)
        self.assertAlmostEqual(x, 1.0, places=12)

    def test_reset_restores_initial_relaxation_and_clears_history(self):
        controller = AitkenRelaxer(omega=0.2, omega_min=0.05, omega_max=0.8)
        controller.previous_residual = (1.0,)
        controller.omega = 0.7
        controller.reset()
        self.assertIsNone(controller.previous_residual)
        self.assertAlmostEqual(controller.omega, 0.2)


def test_aitken_is_bounded_and_reduces_scalar_fixed_point_residual():
    controller = AitkenRelaxer(omega=0.2, omega_min=0.05, omega_max=0.8)
    x = 0.0
    target = 1.0
    errors = []
    for _ in range(12):
        raw = 0.5*x + 0.5*target
        x = controller.relax((x,), (raw,))[0]
        errors.append(abs(target-x))
        assert 0.05 <= controller.omega <= 0.8
    assert all(math.isfinite(e) for e in errors)
    assert errors[-1] < errors[0]


def test_aitken_rejects_nonfinite_residual():
    controller = AitkenRelaxer()
    try:
        controller.update((float("nan"),))
    except ValueError:
        pass
    else:
        raise AssertionError("NaN residual was accepted")


def test_aitken_uses_previous_residual_in_dynamic_update():
    # For x~=0.5*x+0.5, scalar Aitken gives omega=2 after the second
    # residual and reaches the fixed point exactly.  Wide bounds make this
    # test distinguish the standard formula from the former r_k numerator.
    controller = AitkenRelaxer(omega=0.2, omega_min=0.01, omega_max=10.0)
    x = 0.0
    raw = 0.5*x + 0.5
    x = controller.relax((x,), (raw,))[0]
    raw = 0.5*x + 0.5
    x = controller.relax((x,), (raw,))[0]
    assert math.isclose(controller.omega, 2.0, rel_tol=0.0, abs_tol=1.0e-12)
    assert math.isclose(x, 1.0, rel_tol=0.0, abs_tol=1.0e-12)


def test_aitken_reset_restores_initial_relaxation_and_clears_history():
    controller = AitkenRelaxer(omega=0.2, omega_min=0.05, omega_max=0.8)
    controller.previous_residual = (1.0,)
    controller.omega = 0.7
    controller.reset()
    assert controller.previous_residual is None
    assert math.isclose(controller.omega, 0.2)
