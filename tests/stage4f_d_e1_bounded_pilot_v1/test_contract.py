import unittest
from src.coupling.stage4f_d_e1_bounded_pilot_v1.runner import execution_contract,qualify_source
class TestStage42(unittest.TestCase):
 def test_source_and_contract(self):
  self.assertTrue(qualify_source()['qualified']); c=execution_contract(); self.assertEqual((c['blocks'],c['block_steps'],c['steps']),(4,10,40)); self.assertEqual(c['end_tick'],1607500000)
 def test_scope_and_budget(self):
  c=execution_contract(); self.assertEqual(c['max_wall_clock_s'],14400); self.assertEqual(c['max_disk_gb'],20); self.assertTrue(c['no_step_41']); self.assertEqual(c['dt_s'],.00125)
