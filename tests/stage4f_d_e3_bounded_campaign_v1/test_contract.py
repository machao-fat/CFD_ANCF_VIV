import json,unittest
from src.coupling.stage4f_d_e3_bounded_campaign_v1.runner import contract
class TestStage50(unittest.TestCase):
 def test_frozen_contract(self):
  c=contract(); self.assertEqual((c['steps'],c['blocks'],c['block_steps']),(160,16,10)); self.assertEqual(c['first_predicted_step'],160); self.assertEqual(c['source']['step'],159); self.assertEqual(c['source']['tick'],1707500000)
 def test_e3_scope(self): self.assertFalse(contract()['no_e3'])
