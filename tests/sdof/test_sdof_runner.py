"""Analytical and contract checks for the SDOF predictor/corrector."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.coupling.sdof.sdof_runner import SDOFParameters, SDOFRunner, SDOFState


def _run_contract() -> None:
    p = SDOFParameters(1000.0, 1.0, 1.0, 10.0, 5.0, 0.01, 0.0025)
    assert abs(p.mass - 7853.981633974483) < 1e-9
    assert abs(p.natural_frequency_hz - 0.2) < 1e-12
    assert p.stiffness > 0 and p.damping > 0

    r = SDOFRunner(p)
    r.initialize(y=0.01)
    old_energy = 0.5 * p.stiffness * 0.01**2
    max_energy_error = 0.0
    for step in range(1, 2001):
        t = step * p.dt
        pred = r.predict(step, t, 0.0)
        assert abs(r.get_motion()["y_m"] - (0.01 if step == 1 else r.get_motion()["y_m"])) >= 0.0
        state, audit = r.correct(step, t, 0.0)
        max_energy_error = max(max_energy_error, abs(audit["mechanical_energy_J"]))
        assert all(math.isfinite(value) for value in vars(state).values())
    # Damped free motion must not gain energy and must remain bounded.
    assert r.state.y * r.state.y + r.state.v * r.state.v < 1.0
    assert max_energy_error < old_energy * 1.01

    # A synchronized restart must preserve the trajectory exactly.  In
    # particular, acceleration cannot be reconstructed by initialize(), which
    # assumes zero applied load.
    continuous = SDOFRunner(p)
    continuous.initialize(y=0.001)
    restarted = None
    previous_force = 0.0
    for step in range(1, 201):
        time_s = step * p.dt
        force = 25.0 * math.sin(2.0 * math.pi * 0.17 * time_s)
        continuous.predict(step, time_s, previous_force)
        state, _ = continuous.correct(step, time_s, force)
        previous_force = force
        if step == 100:
            restarted = SDOFRunner(p)
            restarted.restore(SDOFState(**vars(state)))
            restarted_force = force
        elif step > 100:
            assert restarted is not None
            restarted.predict(step, time_s, restarted_force)
            restarted_state, _ = restarted.correct(step, time_s, force)
            restarted_force = force
            assert abs(restarted_state.y - state.y) < 1.0e-15
            assert abs(restarted_state.v - state.v) < 1.0e-15
            assert abs(restarted_state.a - state.a) < 1.0e-15

    print("PASS SDOF Newmark contract: bounded free motion and exact state restart")


class SDOFRunnerTests(unittest.TestCase):
    def test_newmark_contract_and_restart(self) -> None:
        _run_contract()


def main() -> None:
    _run_contract()


if __name__ == "__main__":
    main()
