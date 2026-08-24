import unittest
from src.coupling.stage4f_c_stabilized_protocol_candidate_v1.fake_adapter import FakeAdapter

class TestFakeAdapter(unittest.TestCase):
    def adapter(self): return FakeAdapter('case','run')
    def test_accept_commit_binds_identity_and_forces(self):
        a=self.adapter(); row=a.execute(step=0,time_tick=1508125000,raw_force=(10,20,30),previous_applied=(0,0,0),max_cd=2,velocity_error=.002,max_cfl=.1)
        self.assertTrue(row['committed']); self.assertEqual(row['state'],'COMMITTED'); self.assertEqual(row['raw_force'],[10,20,30]); self.assertEqual(row['applied_force'],[1,2,3]); self.assertEqual(len(a.checkpoints),1)
    def test_reject_has_zero_commit_and_retains_raw_evidence(self):
        a=self.adapter(); row=a.execute(step=0,time_tick=1508125000,raw_force=(100,200,300),previous_applied=(0,0,0),max_cd=11,velocity_error=.02,max_cfl=.1)
        self.assertFalse(row['committed']); self.assertEqual(row['raw_force'],[100,200,300]); self.assertEqual(len(a.checkpoints),0)
    def test_duplicate_consumption_rejected(self):
        a=self.adapter(); kw=dict(step=0,time_tick=1508125000,raw_force=(1,2,3),previous_applied=(0,0,0),max_cd=1,velocity_error=0,max_cfl=.1)
        a.execute(**kw)
        with self.assertRaisesRegex(ValueError,'duplicate'): a.execute(**kw)
    def test_restart_lineage_and_wrong_target(self):
        a=self.adapter(); one=a.execute(step=0,time_tick=1508125000,raw_force=(1,2,3),previous_applied=(0,0,0),max_cd=1,velocity_error=0,max_cfl=.1)
        two=a.execute(step=1,time_tick=1508750000,raw_force=(2,3,4),previous_applied=one['applied_force'],max_cd=2,velocity_error=.001,max_cfl=.1)
        self.assertEqual(two['parent_checkpoint'],one['checkpoint_id']); self.assertEqual(a.restart(two['checkpoint_id']),two)
        with self.assertRaises(ValueError): a.restart('missing')

if __name__=='__main__': unittest.main()
