from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from coupling.convergence_observability_v1 import ConvergenceAccumulator, ObservationError, OpenFOAMLogParser, StepObservation


SLICES = ("slice_0000", "slice_0001", "slice_0002")


def obs(step: int, value: float, *, residual: float | None = 1.0e-8, courant: float | None = 0.2,
        continuity: float | None = 1.0e-10) -> StepObservation:
    return StepObservation(
        global_step=step,
        case_local_bridge_step=step // 10,
        time_s=step * 0.005,
        integer_tick=int(round(step * 0.005 * 1.0e9)),
        slice_force_y={sid: value for sid in SLICES},
        q_norm=1.0,
        qdot_norm=0.1,
        worker_residual=residual,
        worker_iterations=3,
        courant_max=courant,
        continuity_global=continuity,
        virtual_work_error=1.0e-8,
    )


class ConvergenceTests(unittest.TestCase):
    def test_fifteen_cycles_and_three_windows_pass_with_quality_scalars(self):
        audit = ConvergenceAccumulator(dt_s=0.005, slice_ids=SLICES, sample_every_steps=10)
        for step in range(10, 20001, 10):
            t = step * 0.005
            audit.observe(obs(step, math.sin(2.0 * math.pi * 0.2 * t)))
        result = audit.finalize()
        self.assertEqual(result["formal_convergence"], "pass")
        self.assertGreaterEqual(result["cycle_count"], 15)
        self.assertEqual(len(result["windows"]), 3)
        self.assertIn("courant_max", result["quality_observables"])

    def test_time_tick_and_stale_observations_fail_closed(self):
        audit = ConvergenceAccumulator(dt_s=0.005, slice_ids=SLICES, sample_every_steps=10)
        audit.observe(obs(10, 0.0))
        with self.assertRaises(ObservationError):
            audit.observe(obs(10, 0.1))
        bad = obs(20, 0.0)
        bad = StepObservation(**{**bad.__dict__, "integer_tick": bad.integer_tick + 1})
        with self.assertRaises(ObservationError):
            audit.observe(bad)

    def test_drifting_signal_is_not_formally_converged(self):
        audit = ConvergenceAccumulator(dt_s=0.005, slice_ids=SLICES, sample_every_steps=10)
        for step in range(10, 20001, 10):
            t = step * 0.005
            amplitude = 0.1 + 0.01 * t
            audit.observe(obs(step, amplitude * math.sin(2.0 * math.pi * (0.2 + 0.0005 * t) * t)))
        result = audit.finalize()
        self.assertEqual(result["formal_convergence"], "not_completed")
        self.assertTrue(any("drift" in reason for reason in result["reasons"]))

    def test_missing_quality_observables_are_explicit(self):
        audit = ConvergenceAccumulator(dt_s=0.005, slice_ids=SLICES, sample_every_steps=10)
        for step in range(10, 20001, 10):
            t = step * 0.005
            item = obs(step, math.sin(2.0 * math.pi * 0.2 * t), residual=None, courant=None, continuity=None)
            audit.observe(StepObservation(**{**item.__dict__, "virtual_work_error": None}))
        result = audit.finalize()
        self.assertIn("missing quality observables", " ".join(result["reasons"]))


class OpenFOAMParserTests(unittest.TestCase):
    def test_extracts_compact_solver_quality_scalars(self):
        parser = OpenFOAMLogParser()
        for line in (
            "Time = 0.005s",
            "Courant Number mean: 0.015 max: 0.156",
            "GAMG:  Solving for p, Initial residual = 1, Final residual = 0.0001, No Iterations 8",
            "time step continuity errors : sum local = 2e-8, global = -3e-10, cumulative = 1e-8",
            "Time = 0.010s",
        ):
            parser.feed(line)
        records = parser.finalize()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["courant_max"], 0.156)
        self.assertEqual(records[0]["iterations_max"], 8)
        self.assertAlmostEqual(records[0]["continuity_global"], -3.0e-10)


if __name__ == "__main__":
    unittest.main()
