import unittest

from coupling.multi_slice_driver.restart_bridge_mapping import (
    RestartBridgeContractError, RestartBridgeMapping,
)


class TestRestartBridgeMapping(unittest.TestCase):
    def setUp(self):
        self.m = RestartBridgeMapping.from_source(
            source_global_step=559, source_time_s=2.2075,
            source_tick=2207500000, dt_s=0.00125)

    def test_source_to_target_mapping(self):
        self.assertEqual(self.m.target_global_step, 560)
        self.assertEqual(self.m.target_tick, 2208750000)
        self.assertAlmostEqual(self.m.target_time_s, 2.20875)
        self.assertEqual((self.m.case_local_seed_step, self.m.case_local_target_step), (0, 1))

    def test_current_seed(self):
        self.m.validate_seed(global_step=559, time_s=2.2075,
                             tick=2207500000, bridge_step=0)

    def test_target_motion(self):
        self.m.validate_target(global_step=560, time_s=2.20875,
                               tick=2208750000, bridge_step=1)

    def test_consumed_ack(self):
        self.m.validate_ack(bridge_step=1, time_s=2.20875,
                            tick=2208750000, global_step=560, consumed=True)

    def test_stale_motion_ready_rejected(self):
        with self.assertRaises(RestartBridgeContractError):
            self.m.validate_target(global_step=560, time_s=2.2075,
                                   tick=2207500000, bridge_step=1)

    def test_seed_time_mismatch_rejected(self):
        with self.assertRaises(RestartBridgeContractError):
            self.m.validate_seed(global_step=559, time_s=2.20875,
                                 tick=2208750000, bridge_step=0)

    def test_tick_mismatch_rejected(self):
        with self.assertRaises(RestartBridgeContractError):
            self.m.validate_target(global_step=560, time_s=2.20875,
                                   tick=2207500000, bridge_step=1)

    def test_old_or_duplicate_ack_rejected(self):
        with self.assertRaises(RestartBridgeContractError):
            self.m.validate_ack(bridge_step=0, time_s=2.2075,
                                tick=2207500000, global_step=559, consumed=True)

    def test_out_of_range_step_rejected(self):
        with self.assertRaises(RestartBridgeContractError):
            self.m.validate_target(global_step=561, time_s=2.21,
                                   tick=2210000000, bridge_step=2)

    def test_not_consumed_ack_rejected_without_process(self):
        with self.assertRaises(RestartBridgeContractError):
            self.m.validate_ack(bridge_step=1, time_s=2.20875,
                                tick=2208750000, global_step=560, consumed=False)


if __name__ == "__main__":
    unittest.main()
