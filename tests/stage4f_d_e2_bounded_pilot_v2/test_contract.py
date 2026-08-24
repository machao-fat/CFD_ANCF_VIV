import json,unittest
from src.coupling.stage4f_d_e2_bounded_pilot_v2.runner import contract
class TestStage50(unittest.TestCase):
 def test_frozen_contract(self):
  c=contract(); self.assertEqual((c['steps'],c['blocks'],c['block_steps']),(80,8,10)); self.assertEqual(c['first_predicted_step'],80); self.assertEqual(c['source']['step'],79); self.assertEqual(c['source']['tick'],1607500000)
 def test_no_e3(self): self.assertTrue(contract()['no_e3'])
