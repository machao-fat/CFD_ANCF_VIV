import json
import unittest
from pathlib import Path

class Dt2ContractTests(unittest.TestCase):
    def test_dt2_contract_is_frozen(self):
        p=Path('results/21_stage4f_c_dt2_validation_v1/dt2_comparison_contract.json')
        d=json.loads(p.read_text(encoding='utf-8'))
        self.assertEqual(d['dt_global_s'],0.00125); self.assertEqual(d['steps'],40)
        self.assertEqual(d['start_time_s'],1.5075); self.assertEqual(d['end_time_s'],1.5575)
        self.assertEqual(d['branch_C_only'],True)

if __name__=='__main__': unittest.main()
