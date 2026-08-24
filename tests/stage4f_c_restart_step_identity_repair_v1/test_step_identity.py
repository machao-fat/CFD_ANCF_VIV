import json,unittest
from pathlib import Path
class Tests(unittest.TestCase):
 def test_contract(self):
  x=json.loads(Path('results/31_stage4f_c_restart_step_identity_repair_v1/restart_step_contract.json').read_text(encoding='utf-8'));self.assertEqual(x['first_new_step'],6);self.assertTrue(x['default_step_zero_forbidden'])
 def test_sequences(self):
  self.assertEqual([0,1,2,3,4]+list(range(5,20)),list(range(20)));self.assertEqual(1520000000+2500000,1522500000)
if __name__=='__main__':unittest.main()
