from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from coupling.cpp_worker_confirm_v1.stabilizer import (
    CausalTimeConsistentLoadStabilizer,
    StabilizerError,
    TAU_S,
)


def _stabilizer(previous):
    return CausalTimeConsistentLoadStabilizer(
        previous_applied_force_N=previous,
        source_step=559,
        source_tick=2_207_500_000,
        run_id="run",
        case_id="case",
        scales_N=(8_333.333333333334,) * 3,
    )


class StabilizerTests(unittest.TestCase):
    def test_matches_first_order_physical_time_update(self):
        previous = ((100.0, 2.0, 0.0),) * 3
        raw = ((200.0, 4.0, 0.0),) * 3
        item = _stabilizer(previous)
        applied, audit = item.apply(step=560, time_s=2.20875,
                                    integer_tick=2_208_750_000, raw_force_N=raw)
        alpha = -math.expm1(-0.00125 / TAU_S)
        self.assertAlmostEqual(applied[0][0], (1 - alpha) * 100 + alpha * 200)
        self.assertAlmostEqual(audit["alpha_dt"], alpha)
        item.commit()
        self.assertEqual(item.state()["last_step"], 560)

    def test_replay_read_only_matlab_force_trace_remains_finite(self):
        root = Path(__file__).resolve().parents[2]
        fixture = root / "runtime/performance_phase_timing_confirm_v1/performance_phase_timing_confirm_001/benchmark_result.json"
        steps = json.loads(fixture.read_text(encoding="utf-8"))["formal_output"]["steps"]
        # The read-only MATLAB export carries the exact in-memory committed
        # stabilizer state used for this replay; keep the source file itself
        # immutable and audit the two identities separately.
        item = _stabilizer(tuple(tuple(float(v) for v in row)
                               for row in steps[0]["stabilizer_state"]["previous_applied_force_N"]))
        self.assertGreaterEqual(len(steps), 40)
        for index, expected in enumerate(steps[:40]):
            current = item.state()["previous_applied_force_N"]
            self.assertTrue(all(math.isfinite(float(value)) for row in current for value in row))
            raw = expected["raw_slice_forces_N"]
            actual_next, _ = item.apply(step=int(expected["step"]), time_s=float(expected["time_s"]),
                                        integer_tick=int(expected["time_tick"]), raw_force_N=raw)
            self.assertTrue(all(math.isfinite(float(value)) for row in actual_next for value in row))
            item.commit()

    def test_fail_closed_for_identity_and_nonfinite(self):
        item = _stabilizer(((1.0, 1.0, 1.0),) * 3)
        with self.assertRaises(StabilizerError):
            item.apply(step=562, time_s=2.20875, integer_tick=2_208_750_000,
                       raw_force_N=((1.0, 1.0, 1.0),) * 3)
        with self.assertRaises(StabilizerError):
            item.apply(step=560, time_s=2.20875, integer_tick=2_208_750_000,
                       raw_force_N=((float("nan"), 1.0, 1.0),) * 3)

    def test_pending_requires_commit_and_tick_is_monotonic(self):
        item = _stabilizer(((1.0, 1.0, 1.0),) * 3)
        item.apply(step=560, time_s=2.20875, integer_tick=2_208_750_000,
                   raw_force_N=((1.0, 1.0, 1.0),) * 3)
        with self.assertRaises(StabilizerError):
            item.apply(step=561, time_s=2.21, integer_tick=2_210_000_000,
                       raw_force_N=((1.0, 1.0, 1.0),) * 3)
        item.rollback()
        applied, _ = item.apply(step=560, time_s=2.20875, integer_tick=2_208_750_000,
                                raw_force_N=((1.0, 1.0, 1.0),) * 3)
        self.assertTrue(all(math.isfinite(value) for row in applied for value in row))


if __name__ == "__main__":
    unittest.main()
