import unittest
from src.coupling.stage4f_d_e2_motion_initialization_repair_v1.runner import contract,qualify
class TestStage46(unittest.TestCase):
 def test_source_and_binding(self):
  self.assertTrue(qualify()['qualified']); c=contract(); self.assertEqual((c['steps'],c['blocks'],c['block_steps']),(80,8,10)); self.assertEqual(c['source_step'],79); self.assertEqual(c['first_predicted_step'],80); self.assertEqual(c['seed_tick'],1607500000)
 def test_reject_time_layers(self):
  c=contract(); self.assertNotEqual(c['source_step'],c['first_predicted_step']); self.assertEqual(c['seed_time_s'],1.6075)
 def test_scope(self):
  c=contract(); self.assertEqual(c['dt_s'],.00125); self.assertTrue(c['no_e3']); self.assertEqual(c['frequency_status'],'not_evaluable_or_diagnostic_by_frozen_contract')
