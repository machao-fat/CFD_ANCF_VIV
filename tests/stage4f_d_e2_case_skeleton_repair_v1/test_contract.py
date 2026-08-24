import json,unittest
from src.coupling.stage4f_d_e2_case_skeleton_repair_v1.runner import contract,SOURCE,SOURCE_SHA
class TestStage48(unittest.TestCase):
 def test_binding(self):
  c=contract(); p=json.loads(SOURCE.read_text(encoding='utf-8-sig')); self.assertEqual(p['step'],79); self.assertEqual(p['time_tick'],1607500000); self.assertEqual(c['first_predicted_step'],80); self.assertEqual(c['dt_s'],.00125)
 def test_scope(self): self.assertNotIn('stage4f_d_e2_motion_initialization_repair_v1',str(contract()['run_id']))
