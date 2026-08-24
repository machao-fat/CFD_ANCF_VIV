import unittest
from src.coupling.stage4f_d_e5_b_bounded_campaign_v1.runner import execution_contract, frozen_contract, qualify_source
from src.coupling.stage4f_d_e4_campaign_orchestration_repair_v1.gate import Gate, TERMINAL
class Stage66Tests(unittest.TestCase):
    def test_contract(self):
        c=execution_contract(); self.assertEqual((c['authorized_blocks'],c['steps_per_block'],c['authorized_steps']),(4,10,40)); self.assertEqual((c['first_target_step'],c['last_target_step']),(520,559)); self.assertEqual((c['first_target_tick'],c['last_target_tick']),(2158750000,2207500000)); self.assertTrue(qualify_source()['qualified'])
    def test_internal_stop(self):
        g=Gate(frozen_contract())
        for s in range(520,560): g.commit_step(s)
        self.assertEqual(g.state,TERMINAL)
        with self.assertRaises(RuntimeError): g.commit_step(560)
        with self.assertRaises(RuntimeError): g.begin_block(4)
