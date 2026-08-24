import math
import unittest

from coupling.stage4f_c_time_consistent_stabilizer_design_v1.replay import (
    ReplayError, TAU_S, alpha_for_dt, common_time_differences, replay,
)


def row(step, tick, raw=10.0):
    return {"step": step, "time_tick": tick, "time_s": tick / 1e9,
            "raw_slice_forces_N": [[raw, 1.0, 0.0]]}


class TimeConsistentReplayTests(unittest.TestCase):
    def test_equal_elapsed_time_is_equivalent_for_constant_raw(self):
        initial = [[0.0, 0.0, 0.0]]
        a = replay([row(0, 2_500_000)], mode="exponential_time", initial=initial, initial_tick=0)
        c = replay([row(0, 1_250_000), row(1, 2_500_000)], mode="exponential_time", initial=initial, initial_tick=0)
        self.assertAlmostEqual(a[-1]["applied"][0][0], c[-1]["applied"][0][0], places=12)

    def test_fixed_step_is_not_time_equivalent(self):
        initial = [[0.0, 0.0, 0.0]]
        a = replay([row(0, 2_500_000)], mode="fixed_step", initial=initial, initial_tick=0)
        c = replay([row(0, 1_250_000), row(1, 2_500_000)], mode="fixed_step", initial=initial, initial_tick=0)
        self.assertNotEqual(a[-1]["applied"], c[-1]["applied"])

    def test_exponential_composition_and_nonuniform_dt(self):
        self.assertAlmostEqual((1-alpha_for_dt(.001))*(1-alpha_for_dt(.0015)), math.exp(-.0025/TAU_S), places=15)

    def test_invalid_parameters_fail_closed(self):
        for value in (0.0, -1.0, float("nan"), float("inf")):
            with self.assertRaises(ReplayError): alpha_for_dt(.001, value)

    def test_duplicate_time_reversal_and_nonfinite_rejected(self):
        initial = [[0.0, 0.0, 0.0]]
        with self.assertRaises(ReplayError): replay([row(0, 1), row(1, 1)], mode="fixed_step", initial=initial, initial_tick=0)
        with self.assertRaises(ReplayError): replay([row(0, 1, float("nan"))], mode="fixed_step", initial=initial, initial_tick=0)

    def test_missing_common_time_rejected(self):
        a=[{"step":0,"time_tick":2,"time_s":2e-9,"applied":[[1,1,0]]}]
        c=[{"step":0,"time_tick":1,"time_s":1e-9,"applied":[[1,1,0]]}]
        with self.assertRaises(ReplayError): common_time_differences(a,c,"applied")

    def test_state_hash_deterministic_and_raw_separate(self):
        h1=replay([row(0,1)],mode="fixed_step",initial=[[0,0,0]],initial_tick=0)
        h2=replay([row(0,1)],mode="fixed_step",initial=[[0,0,0]],initial_tick=0)
        self.assertEqual(h1[0]["state_hash"],h2[0]["state_hash"])
        self.assertNotEqual(h1[0]["raw"],h1[0]["applied"])

    def test_rollback_and_restart_restore_exact_state(self):
        first=replay([row(0,1_000_000)],mode="exponential_time",initial=[[0,0,0]],initial_tick=0)[-1]
        restarted=replay([row(1,2_000_000)],mode="exponential_time",initial=first["applied"],initial_tick=first["time_tick"])
        continuous=replay([row(0,1_000_000),row(1,2_000_000)],mode="exponential_time",initial=[[0,0,0]],initial_tick=0)
        self.assertEqual(restarted[-1]["applied"],continuous[-1]["applied"])

if __name__ == "__main__":
    unittest.main()
