import json
import unittest
from pathlib import Path
from src.coupling.stage4f_c_stabilized_protocol_candidate_v1.offline_replay import *

ROOT=Path(__file__).resolve().parents[2]
class TestOfflineReplay(unittest.TestCase):
    def read(self,path): return json.loads((ROOT/path).read_text(encoding='utf-8'))
    def test_repair2_rejects_frozen_step2(self):
        rows=repair2_rows(self.read(Path('results/13_stage4f_three_slice_short_window_v1_repair2/real_execution_summary.json')))
        result=replay(rows)
        self.assertEqual(result['accepted_steps'],2); self.assertEqual(result['first_rejected']['step'],2)
        self.assertEqual(result['first_rejected']['reasons'],['raw_abs_Cd','velocity_consistency']); self.assertFalse(result['probe_authorized'])
    def test_d1_rejects_frozen_step2(self):
        rows=d1_rows(self.read(Path('results/13_stage4f_three_slice_timestep_diagnostic_v2/d1_diagnostic_summary.json')))
        result=replay(rows)
        self.assertEqual(result['accepted_steps'],2); self.assertEqual(result['first_rejected']['step'],2); self.assertFalse(result['probe_authorized'])
    def test_replay_does_not_relax_failed_raw_load(self):
        result=replay([{'step':0,'Cd':[11,1,1],'velocity_error':0,'max_cfl':.1}])
        self.assertEqual(result['accepted_steps'],0); self.assertEqual(result['accepted'],[])

if __name__=='__main__': unittest.main()
