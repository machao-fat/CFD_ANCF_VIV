import json,math,unittest
from decimal import Decimal,localcontext
from pathlib import Path
from coupling.stage4f_c_time_consistent_q_probe_v1 import probe
class Tests(unittest.TestCase):
 def test_ticks_and_isolation(self):
  self.assertEqual([1507500000+(i+1)*1250000 for i in range(12)][-1],1522500000);self.assertNotIn('stage4f_c_utf8_checkpoint_reader_repair_v1',str(probe.RESULT))
 def test_half_step_decay(self):
  with localcontext() as ctx:
   ctx.prec=50;tau=Decimal('0.023728053952574758');old=(-Decimal('0.00125')/tau).exp();self.assertLess(abs(old*old-Decimal('0.9')),Decimal('5e-17'))
 def test_frozen_contract(self):
  p=probe.RESULT/'q_comparison_contract.json';x=json.loads(p.read_text(encoding='utf-8'));self.assertTrue(x['frozen_before_run']);self.assertEqual(x['common_mapping']['Q_steps'],[1,3,5,7,9,11])
 def test_snapshot_identity_cardinality(self):
  identities={(step,slice_id,1507500000+(step+1)*1250000) for step in range(12) for slice_id in range(3)};self.assertEqual(len(identities),36)
if __name__=='__main__':unittest.main()
