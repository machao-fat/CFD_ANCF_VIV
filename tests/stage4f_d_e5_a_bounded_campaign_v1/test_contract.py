import unittest

from src.coupling.stage4f_d_e5_a_bounded_campaign_v1.runner import execution_contract, frozen_contract, qualify_source


class Stage65ContractTests(unittest.TestCase):
    def test_frozen_window_and_source(self):
        c = execution_contract()
        self.assertEqual((c["authorized_blocks"], c["steps_per_block"], c["authorized_steps"]), (4, 10, 40))
        self.assertEqual((c["first_target_step"], c["last_target_step"]), (480, 519))
        self.assertEqual((c["first_target_tick"], c["last_target_tick"]), (2108750000, 2157500000))
        self.assertTrue(c["no_auto_continuation"])
        self.assertTrue(c["next_segment_requires_new_authorization"])
        self.assertTrue(qualify_source()["qualified"])

    def test_stage57_internal_gate_rejects_overrun(self):
        from src.coupling.stage4f_d_e4_campaign_orchestration_repair_v1.gate import Gate, TERMINAL
        g = Gate(frozen_contract())
        for step in range(480, 520):
            g.commit_step(step)
        self.assertEqual(g.state, TERMINAL)
        with self.assertRaises(RuntimeError):
            g.commit_step(520)
        with self.assertRaises(RuntimeError):
            g.begin_block(4)


if __name__ == "__main__":
    unittest.main()
