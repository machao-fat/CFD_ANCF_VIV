import json,unittest
from pathlib import Path
class ContractTests(unittest.TestCase):
 def test_frozen_schedule_and_thresholds(self):
  p=Path('results/19_stage4f_c_full_short_window_v1/immutable_comparison_contract.json');d=json.loads(p.read_text(encoding='utf-8'));self.assertEqual(d['branches']['A']['steps'],20);self.assertEqual(d['branches']['B']['segments'],[5,15]);self.assertEqual(d['branches']['C']['steps'],40);self.assertEqual(d['stabilizer']['alpha'],.1);self.assertEqual(d['hard_gates']['raw_abs_cd_max'],10)
if __name__=='__main__':unittest.main()
