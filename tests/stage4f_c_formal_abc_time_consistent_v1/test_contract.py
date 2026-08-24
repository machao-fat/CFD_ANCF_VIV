import json,unittest
from pathlib import Path
class Tests(unittest.TestCase):
 def test_contract_is_frozen(self):
  p=Path('results/30_stage4f_c_formal_abc_time_consistent_v1/formal_abc_contract.json');x=json.loads(p.read_text(encoding='utf-8'));self.assertTrue(x['frozen_before_run']);self.assertEqual(x['branches']['C']['steps'],40)
 def test_independent_identities(self):
  x=json.loads(Path('results/30_stage4f_c_formal_abc_time_consistent_v1/formal_abc_contract.json').read_text(encoding='utf-8'));ids=[v['run_id'] for v in x['branches'].values()];self.assertEqual(len(ids),len(set(ids)));self.assertNotEqual(x['branches']['A']['case_id'],x['branches']['B']['case_id'])
if __name__=='__main__':unittest.main()
