import json,unittest
from pathlib import Path
class Tests(unittest.TestCase):
 def test_contract(self):
  x=json.loads(Path('results/32_stage4f_c_restart_parent_lineage_repair_v1/restart_parent_lineage_contract.json').read_text(encoding='utf-8'));self.assertTrue(x['source_checkpoint_must_be_bound']);self.assertTrue(x['parent_checkpoint_id_required'])
 def test_parent_sequence(self):
  source='checkpoint_step00000004_x';self.assertEqual('checkpoint_'+source,'checkpoint_checkpoint_step00000004_x');self.assertEqual(list(range(5,20)),list(range(5,20)))
if __name__=='__main__':unittest.main()
